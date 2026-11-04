"""
`dry-lint bench --replay N`: what `check` would have done on each of the last N commits of the default branch, with
the settings and judging preset this checkout has now. A team can see, on its own history, how many pull requests
would have failed or warned, which findings they would have read and what the judges would have cost, before it
turns dry-lint on or changes a preset or a threshold.

Each first-parent commit is checked against its parent, as `check` runs on a pull request, with a judging budget of
its own as each check has, oldest first, so the
verdict store fills as it would have if dry-lint had run on every one of them: it keeps one verdict per pair, the
latest. The replay checks commits out in a temporary worktree, never in yours, and removes it when it is done.
Replaying again with another `fail_at` judges nothing new, and a later `check` reuses the verdicts.
"""

import shutil
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from pydantic import BaseModel, Field

from dry_lint.costs import Ledger, combined
from dry_lint.detector import Detector, changed_lines, touched
from dry_lint.functions import extractor_for, repository_functions, tracked_files
from dry_lint.git import git
from dry_lint.judging import Judging
from dry_lint.labelling import Labels
from dry_lint.models import Function, Run, Versioned
from dry_lint.plugins import load
from dry_lint.report import Finding, JudgingSummary, Report
from dry_lint.settings import Settings
from dry_lint.store import VerdictStore


class ReplayedCommit(BaseModel):
    """One commit, checked against its first parent: the report `check` would have written."""

    commit: str
    subject: str
    report: Report

    @property
    def fails(self) -> bool:
        return any(f.blocking for f in self.report.findings)

    @property
    def warns(self) -> bool:
        return not self.fails and any(f.reported for f in self.report.findings)


class Replay(Versioned):
    """`dry-lint bench --replay --format json`."""

    ref: str = Field(description="The branch replayed, as given.")
    head: str = Field(description="The commit it pointed at.")
    commits: list[ReplayedCommit] = Field(default_factory=list, description="Oldest first, in the order replayed.")
    judging: JudgingSummary | None = Field(
        default=None, description="Judges, thresholds, budget and cost, for all commits."
    )
    labels: Labels | None = Field(default=None, description="With --label: the gold set and what it says.")

    def findings(self) -> list[tuple[ReplayedCommit, Finding]]:
        return [(c, f) for c in self.commits for f in c.report.findings]

    def as_text(self, limit: int = 20) -> str:
        found = self.findings()
        reported = [(c, f) for c, f in found if f.reported]
        blocking = sum(f.blocking for _, f in reported)
        changed = [c for c in self.commits if c.report.changed]
        fresh = sum(f.verdict is not None and not f.cached for _, f in found)
        lines = [
            f"dry-lint replay: the last {len(self.commits)} commits of {self.ref} ({self.head[:9]}), checked as "
            "`check` would have checked them, with these settings"
        ]
        for commit in changed:
            report = commit.report
            shown = sum(f.reported for f in report.findings)
            verdict = "fails" if commit.fails else "warns" if commit.warns else "passes"
            lines.append(
                f"  {commit.commit[:9]}  {verdict:6} {report.changed:3} changed, {len(report.findings):2} "
                f"candidates, {shown} reported  {commit.subject[:60]}"
            )
        lines += [
            f"commits: {len(self.commits)} replayed, {len(changed)} with changed functions, "
            f"{sum(c.fails for c in self.commits)} would fail, {sum(c.warns for c in self.commits)} would only warn",
            f"pairs: {len(found)} candidates ({sum(len(c.report.filtered) for c in self.commits)} more settled by a rule): "
            f"{fresh} judged now, {sum(f.cached for _, f in found)} from the store, "
            f"{sum(f.deferred for _, f in found)} not judged (budget)",
            f"findings: {len(reported)} reported, {blocking} of them blocking",
        ]
        if self.judging:
            lines.append(f"judging: {self.judging.line()}")
            checked = [c for c in self.commits if c.report.findings]
            reached = sum(bool(c.report.judging and c.report.judging.skipped) for c in checked)
            usd = self.judging.usd
            lines.append(
                f"  per check: a ${self.judging.budget_usd:g} budget, reached by {reached} of {len(checked)} "
                "checks with candidates"
                + (f"; est. ${usd / len(checked):.4f} each on average" if usd is not None and checked else "")
            )
        if reported:
            lines.append("")
            lines.append(f"reported findings ({min(limit, len(reported))} of {len(reported)}, blocking first):")
            for commit, finding in sorted(reported, key=lambda cf: (not cf[1].blocking, -cf[1].verdict.score))[:limit]:
                where = finding.candidate.new
                lines.append(
                    f"  {commit.commit[:9]} {where.path}:{where.line}: {finding.headline()}"
                    + (" [blocks]" if finding.blocking else "")
                )
                lines.append(f"    {finding.advice(commit.report.relatives(finding))}")
        if self.labels:
            lines.append(self.labels.as_text())
        return "\n".join(lines)


@contextmanager
def worktree(root: Path, commit: str) -> Iterator[Path]:
    """A temporary detached checkout of the repository, removed afterwards whatever happens."""
    folder = Path(tempfile.mkdtemp(prefix="dry-lint-replay-"))
    tree = folder / "tree"
    git(root, "worktree", "add", "--detach", "--quiet", str(tree), commit)
    try:
        yield tree
    finally:
        git(root, "worktree", "remove", "--force", str(tree), check=False)
        shutil.rmtree(folder, ignore_errors=True)
        git(root, "worktree", "prune", check=False)


def analysed(tree: Path, lines: dict[str, set[int]], settings: Settings, extractors: list) -> bool:
    """Whether the change touched any file `check` reads."""
    read = set(tracked_files(tree, settings.include, settings.exclude))
    return any(extractor_for(path, extractors) for path in set(lines) & read)


def replay(
    root: Path,
    settings: Settings,
    store: VerdictStore,
    count: int,
    ref: str,
    progress: Callable[[str], None] | None = None,
) -> Replay:
    """Check each of the last `count` first-parent commits of `ref` against its parent, oldest first."""
    head = git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
    if not head:
        raise ValueError(f"Cannot replay {ref!r}: no such branch or commit")
    history = git(root, "rev-list", "--first-parent", "--reverse", f"--max-count={count}", head).split()
    judging = Judging.configured(settings, store)
    extractors = [load("extractors", choice) for choice in settings.extractors]
    cache: dict[tuple[str, str], list[Function]] = {}
    commits, spent = [], []
    with worktree(root, head) as tree:
        for number, commit in enumerate(history, 1):
            git(tree, "checkout", "--quiet", "--detach", commit)
            parents = git(root, "rev-list", "--parents", "-n", "1", commit).split()[1:]
            run = Run(head=commit, base=parents[0] if parents else "")
            lines = changed_lines(tree, parents[0]) if parents else {}
            functions = (
                repository_functions(tree, settings.include, settings.exclude, extractors, cache)
                if lines and analysed(tree, lines, settings, extractors)
                else []
            )
            changed = touched(functions, lines)
            candidates = (
                Detector(functions, settings, load("comparers", settings.comparer), extractors).candidates(changed)
                if changed
                else []
            )
            judging.ledger = Ledger(settings)  # each pull request's check has a budget of its own
            report = Report.build(
                judging.findings(candidates, source=run),
                settings,
                filtered=[c for c in candidates if c.filtered],
                run=run,
                changed=len(changed),
                judge=judging.name,
                functions=len(functions),
                judging=judging.summary(),
            )
            spent += judging.ledger.spend.values()
            commits.append(
                ReplayedCommit(commit=commit, subject=git(root, "log", "-1", "--format=%s", commit), report=report)
            )
            if progress:
                progress(
                    f"replay {number}/{len(history)} {commit[:9]}: {len(changed)} changed, "
                    f"{len(report.findings)} candidates, {sum(f.reported for f in report.findings)} reported"
                )
    summary = judging.summary().model_copy(update={"spend": combined(spent)})
    return Replay(ref=ref, head=head, commits=commits, judging=summary)
