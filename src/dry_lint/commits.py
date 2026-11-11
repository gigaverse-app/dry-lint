"""
What the pre-commit hook no longer reported before a commit, carried to the pull request's sticky in commit trailers.

The hook remembers reported pairs in the git directory. When a later completed staged check no longer reports
one, it records absence, or dismissal when an explicit rule settles it. This is not proof of consolidation.
Only a check staging the pair's file can settle it; unstaging alone settles nothing. CI's observed findings win.

Trailers carry those observations between machines and into the PR ledger:

    Dry-Lint-Not-Reported: ab7719f1ec3f9b70 repository_counter_name ≈ counter_key (4 lines)
    Dry-Lint-Dismissed: 5c0e2f6a91d3b7e4 parse_date ≈ parse_timestamp (9 lines)

Legacy Dry-Lint-Kept-Out trailers used the same absence test and are read as not-reported, without cleanup credit.
"""

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from dry_lint.git import git
from dry_lint.models import Versioned
from dry_lint.report import Report, plural

TRAILERS = {"not-reported": "Dry-Lint-Not-Reported", "dismissed": "Dry-Lint-Dismissed"}
VALUE = re.compile(
    r"(?P<key>[0-9a-f]{8,64}) (?P<new>\S+) ≈ (?P<existing>\S+)(?: \((?P<lines>\d+) lines?\))?(?P<model> \[model review\])?"
)


def reported_state(state: str) -> str:
    """Old disappearance-only claims carry no proof of removal."""
    return "not-reported" if state == "kept-out" else state


class Outcome(BaseModel):
    """A pair the hook blocked, and how it was settled before the commit."""

    key: str
    kind: Literal["function", "model"] = "function"
    new: str
    existing: str
    path: str = Field(default="", description="The new function's file: only a check that stages it settles it.")
    lines: int = 0
    state: Literal["blocked", "not-reported", "dismissed"] = "blocked"

    _read_legacy_state = field_validator("state", mode="before")(reported_state)

    def trailer(self) -> str:
        size = f" ({plural(self.lines, 'line')})" if self.lines else ""
        lane = " [model review]" if self.kind == "model" else ""
        return f"{TRAILERS[self.state]}: {self.key} {self.new} ≈ {self.existing}{size}{lane}"


class Journal(Versioned):
    """The hook's memory in the git directory: pairs it blocked, and outcomes the next commit will carry."""

    blocked: dict[str, Outcome] = Field(default_factory=dict)
    pending: dict[str, Outcome] = Field(default_factory=dict)

    @staticmethod
    def path(root: Path) -> Path:
        return root / git(root, "rev-parse", "--git-path", "dry-lint/commits.json")

    @classmethod
    def load(cls, root: Path) -> "Journal":
        path = cls.path(root)
        return cls.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else cls()

    def save(self, root: Path) -> None:
        path = self.path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2) + "\n", encoding="utf-8")

    def observe(self, report: Report, staged: set[str]) -> "Journal":
        """This journal after one staged check: what it reports is blocked; what it no longer reports is settled."""
        journal = self.model_copy(deep=True)
        reported = {f.candidate.key: f for f in report.findings if f.tracked}
        unjudged = {f.candidate.key for f in report.findings if f.deferred or f.verdict is None}
        by_rule = {c.key for c in report.filtered}
        for key, finding in reported.items():
            new, existing = finding.candidate.new, finding.candidate.existing
            path, _, name = new.qualname.partition("::")
            journal.blocked[key] = Outcome(
                key=key,
                kind=finding.kind,
                new=name,
                existing=existing.qualname.split("::", 1)[-1],
                path=path,
                lines=new.lines,
            )
            journal.pending.pop(
                key, None
            )  # back again: the commit that carries it must not say it was no longer reported
        for key, pair in list(journal.blocked.items()):
            if key in reported or key in unjudged or pair.path not in staged:
                continue
            if pair.kind == "model" and report.model_judging is None:
                continue
            state = "dismissed" if key in by_rule else "not-reported"
            journal.pending[key] = pair.model_copy(update={"state": state})
            del journal.blocked[key]
        return journal


def staged_files(root: Path) -> set[str]:
    """Every staged path, deletions included: deleting the copy is a fix too."""
    return set(git(root, "diff", "--cached", "--name-only", "--no-renames").splitlines())


def outcomes(messages: list[str]) -> list[Outcome]:
    """The outcomes commit messages carry, oldest message first; the latest word on a pair wins."""
    names = {name.lower(): state for state, name in TRAILERS.items()}
    names["dry-lint-kept-out"] = "not-reported"  # legacy trailers were based on absence alone
    found: dict[str, Outcome] = {}
    for line in (line for message in messages for line in message.splitlines()):
        name, _, value = line.partition(":")
        match = VALUE.fullmatch(value.strip())
        if name.strip().lower() in names and match:
            found[match["key"]] = Outcome(
                key=match["key"],
                kind="model" if match["model"] else "function",
                new=match["new"],
                existing=match["existing"],
                lines=int(match["lines"] or 0),
                state=names[name.strip().lower()],
            )
    return list(found.values())


def trailed(root: Path, base: str, head: str = "HEAD") -> list[Outcome]:
    """The outcomes the commits in base..head carry."""
    log = git(root, "log", "--reverse", "--format=%B%x00", f"{base}..{head}", check=False)
    return outcomes(log.split("\0"))


def append_trailers(root: Path, message: Path) -> int:
    """Write the pending outcomes into a commit message, once; how many were written."""
    journal = Journal.load(root)
    if not journal.pending:
        return 0
    trailers = [arg for pair in journal.pending.values() for arg in ("--trailer", pair.trailer())]
    git(root, "interpret-trailers", "--in-place", "--if-exists", "addIfDifferent", *trailers, str(message))
    count = len(journal.pending)
    journal.pending = {}
    journal.save(root)
    return count


def summary(root: Path, base: str) -> str:
    """The hook's header: what it has no longer reported and dismissed on this branch, committed and still to commit."""
    outcomes = {o.key: o for o in [*trailed(root, base), *Journal.load(root).pending.values()]}
    kept = sum(o.state == "not-reported" and o.kind == "function" for o in outcomes.values())
    dismissed = sum(o.state == "dismissed" and o.kind == "function" for o in outcomes.values())
    model_resolved = sum(o.state == "not-reported" and o.kind == "model" for o in outcomes.values())
    model_dismissed = sum(o.state == "dismissed" and o.kind == "model" for o in outcomes.values())
    if not outcomes:
        return ""
    return (
        f"dry-lint before commit on this branch: {plural(kept, 'finding')} no longer reported, "
        f"{plural(dismissed, 'look-alike')} dismissed; the pull request's comment counts them"
        + (
            f"; model reviews: {model_resolved} resolved, {model_dismissed} dismissed (not confirmed consolidations)"
            if model_resolved or model_dismissed
            else ""
        )
    )
