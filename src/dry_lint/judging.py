"""
The judge step, which is core whatever judge is plugged in: for every candidate, the stored verdict when it still
holds, otherwise the judge's answer; for first scores in the escalation band, a second judge's answer instead.
Every new answer goes to the store. Filtered pairs never reach a judge.
"""

import subprocess
from pathlib import Path

from dry_lint.judges import make_judge
from dry_lint.models import Candidate, Run, Verdict
from dry_lint.plugins import Judge, identity, load
from dry_lint.report import Finding
from dry_lint.settings import Settings
from dry_lint.store import DirectoryStore, VerdictStore


def default_store(root: Path) -> Path:
    """Inside the git directory: kept between runs, never committed."""
    out = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=root, capture_output=True, text=True, check=True)
    return (root / out.stdout.strip()).resolve() / "dry-lint" / "verdicts"


def open_store(settings: Settings, root: Path, path: Path | None = None) -> VerdictStore:
    """The configured store; `path` (from --store) means a folder, whatever the settings say."""
    if path is not None:
        return VerdictStore(DirectoryStore(path))
    if settings.store.use == "dir":
        folder = settings.store.options().get("path")
        return VerdictStore(DirectoryStore(root / folder if folder else default_store(root)))
    return VerdictStore(load("stores", settings.store))


class Judging:
    def __init__(self, settings: Settings, judge: Judge | None, escalation: Judge | None, store: VerdictStore) -> None:
        self.settings, self.judge, self.escalation, self.store = settings, judge, escalation, store

    @classmethod
    def configured(cls, settings: Settings, store: VerdictStore) -> "Judging":
        judge = make_judge(settings.judge)
        escalation = make_judge(settings.escalate) if judge is not None and settings.escalate else None
        return cls(settings, judge, escalation, store)

    @property
    def name(self) -> str | None:
        if self.judge is None:
            return None
        return identity(self.judge) + (f" > {identity(self.escalation)}" if self.escalation else "")

    def escalated(self, candidates: list[Candidate], first: list[Verdict]) -> list[Verdict]:
        """First answers, with those in the escalation band replaced by the second judge's, under the first's name."""
        assert self.judge is not None
        if self.escalation is None or self.settings.escalate is None:
            return first
        low, high = self.settings.escalate.between
        unsure = [i for i, verdict in enumerate(first) if low <= verdict.score < high]
        second = self.escalation.judge([candidates[i] for i in unsure], self.settings) if unsure else []
        answers = list(first)
        for i, verdict in zip(unsure, second):
            answers[i] = verdict.model_copy(update={"judge": self.judge.name, "judge_version": self.judge.version,
                                                    "second_opinion": identity(self.escalation)})
        return answers

    def findings(self, candidates: list[Candidate], source: Run | None = None, refresh: bool = False) -> list[Finding]:
        """A finding per proposed candidate: unjudged when there is no judge, else from the store or the judge."""
        proposed = [c for c in candidates if c.filtered is None]
        if self.judge is None:
            return [Finding(candidate=c) for c in proposed]
        version = self.judge.version if refresh else None
        known = [self.store.lookup(c, self.judge.name, self.settings.reopen_margin, version).verdict for c in proposed]
        pending = [i for i, verdict in enumerate(known) if verdict is None]
        if pending:
            asked = [proposed[i] for i in pending]
            for i, verdict in zip(pending, self.escalated(asked, self.judge.judge(asked, self.settings))):
                self.store.remember(proposed[i], verdict, source)
                known[i] = verdict
        return [Finding(candidate=c, verdict=known[i], cached=i not in pending) for i, c in enumerate(proposed)]
