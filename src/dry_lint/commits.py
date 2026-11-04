"""
What the pre-commit hook kept out before a commit, carried to the pull request's sticky in commit trailers.

A duplicate the hook blocks and the coding agent then fixes never reaches a push, so CI never sees it. The hook
keeps the pairs it blocked in the git directory. When a later staged check no longer reports one, it is kept out,
or dismissed when a rule settled it (`distinct-from`, a reviewed dismissal): the rule the pull request's ledger
uses across pushes. Only a check that staged the pair's file can settle it, so unstaging a file settles nothing.

The `dry-lint-trailers` hook writes those outcomes into the next commit's message:

    Dry-Lint-Kept-Out: ab7719f1ec3f9b70 repository_counter_name ≈ counter_key (4 lines)
    Dry-Lint-Dismissed: 5c0e2f6a91d3b7e4 parse_date ≈ parse_timestamp (9 lines)

and the action reads the trailers of the pull request's commits into its ledger. The commits carry them across
machines and worktrees with no service in between. A trailer is what the committer's hook said: it is counted,
not verified, as a dismissal in a pull request is.
"""

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from dry_lint.git import git
from dry_lint.report import Report, plural

TRAILERS = {"kept-out": "Dry-Lint-Kept-Out", "dismissed": "Dry-Lint-Dismissed"}
VALUE = re.compile(r"(?P<key>[0-9a-f]{8,64}) (?P<new>\S+) ≈ (?P<existing>\S+)(?: \((?P<lines>\d+) lines?\))?")


class Outcome(BaseModel):
    """A pair the hook blocked, and how it was settled before the commit."""

    key: str
    new: str
    existing: str
    path: str = Field(default="", description="The new function's file: only a check that stages it settles it.")
    lines: int = 0
    state: Literal["blocked", "kept-out", "dismissed"] = "blocked"

    def trailer(self) -> str:
        size = f" ({plural(self.lines, 'line')})" if self.lines else ""
        return f"{TRAILERS[self.state]}: {self.key} {self.new} ≈ {self.existing}{size}"


class Journal(BaseModel):
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
        reported = {f.candidate.key: f for f in report.findings if f.reported}
        unjudged = {f.candidate.key for f in report.findings if f.deferred or f.verdict is None}
        by_rule = {c.key for c in report.filtered}
        for key, finding in reported.items():
            new, existing = finding.candidate.new, finding.candidate.existing
            path, _, name = new.qualname.partition("::")
            journal.blocked[key] = Outcome(key=key, new=name, existing=existing.qualname.split("::", 1)[-1],
                                           path=path, lines=new.lines)
            journal.pending.pop(key, None)  # back again: the commit that carries it must not say it was kept out
        for key, pair in list(journal.blocked.items()):
            if key in reported or key in unjudged or pair.path not in staged:
                continue
            state = "dismissed" if key in by_rule else "kept-out"
            journal.pending[key] = pair.model_copy(update={"state": state})
            del journal.blocked[key]
        return journal


def staged_files(root: Path) -> set[str]:
    """Every staged path, deletions included: deleting the copy is a fix too."""
    return set(git(root, "diff", "--cached", "--name-only", "--no-renames").splitlines())


def outcomes(messages: list[str]) -> list[Outcome]:
    """The outcomes commit messages carry, oldest message first; the latest word on a pair wins."""
    names = {name.lower(): state for state, name in TRAILERS.items()}
    found: dict[str, Outcome] = {}
    for line in (line for message in messages for line in message.splitlines()):
        name, _, value = line.partition(":")
        match = VALUE.fullmatch(value.strip())
        if name.strip().lower() in names and match:
            found[match["key"]] = Outcome(key=match["key"], new=match["new"], existing=match["existing"],
                                          lines=int(match["lines"] or 0), state=names[name.strip().lower()])
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
    """The hook's header: what it has kept out and dismissed on this branch, committed and still to commit."""
    outcomes = {o.key: o for o in [*trailed(root, base), *Journal.load(root).pending.values()]}
    kept = sum(o.state == "kept-out" for o in outcomes.values())
    dismissed = sum(o.state == "dismissed" for o in outcomes.values())
    if not kept and not dismissed:
        return ""
    return (f"dry-lint before commit on this branch: {plural(kept, 'duplicate')} kept out, "
            f"{plural(dismissed, 'look-alike')} dismissed; the pull request's comment counts them")
