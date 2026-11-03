"""
The judge step, which is core whatever judge is plugged in: for every candidate, the stored verdict when it still
holds, otherwise the judge's answer; for first scores in the escalation band, a second judge's answer instead.
Every new answer goes to the store. Filtered pairs never reach a judge.
"""

from pathlib import Path

from dry_lint.costs import Ledger
from dry_lint.git import git
from dry_lint.judges import make_escalation, make_judge
from dry_lint.models import Candidate, Run, Verdict
from dry_lint.plugins import Judge, identity, load
from dry_lint.report import Finding, JudgingSummary
from dry_lint.settings import Settings
from dry_lint.store import DirectoryStore, VerdictStore


def default_store(root: Path) -> Path:
    """Inside the git directory: kept between runs, never committed."""
    return (root / git(root, "rev-parse", "--git-common-dir")).resolve() / "dry-lint" / "verdicts"


def open_store(settings: Settings, root: Path, path: Path | None = None) -> VerdictStore:
    """The configured store; `path` (from --store) means a folder, whatever the settings say."""
    if path is not None:
        return VerdictStore(DirectoryStore(path))
    if settings.store.use == "dir":
        folder = settings.store.options().get("path")
        return VerdictStore(DirectoryStore(root / folder if folder else default_store(root)))
    return VerdictStore(load("stores", settings.store))


def decide(candidates: list[Candidate], judge: Judge, escalation: Judge | None, settings: Settings,
           ledger: Ledger | None = None) -> list[Verdict | None]:
    """
    The first judge's answers, with those in the escalation band replaced by the second judge's answers, kept under
    the first judge's name with `second_opinion` set, so they are stored and reused like any other.

    With a `ledger`, each judge is asked only about the pairs the budget covers, riskiest first: the closest look-
    alikes for the first judge, the highest first scores for the second. A pair the first judge could not afford
    stays unjudged (None); one the second could not afford keeps the first judge's answer.
    """
    order = sorted(range(len(candidates)), key=lambda i: -candidates[i].similarity)
    allowed = ledger.affordable(judge, [candidates[i] for i in order]) if ledger else len(order)
    asked = order[:allowed]
    answers: list[Verdict | None] = [None] * len(candidates)
    for i, verdict in zip(asked, judge.judge([candidates[i] for i in asked], settings) if asked else []):
        answers[i] = verdict
    if ledger:
        ledger.charge(judge, [candidates[i] for i in asked], skipped=len(order) - allowed)
    if escalation is None or settings.escalate is None:
        return answers
    low, high = settings.escalate.between
    unsure = sorted((i for i, v in enumerate(answers) if v is not None and low <= v.score < high),
                    key=lambda i: -answers[i].score)
    allowed = ledger.affordable(escalation, [candidates[i] for i in unsure]) if ledger else len(unsure)
    second = escalation.judge([candidates[i] for i in unsure[:allowed]], settings) if allowed else []
    if ledger:
        ledger.charge(escalation, [candidates[i] for i in unsure[:allowed]], skipped=len(unsure) - allowed)
    for i, verdict in zip(unsure, second):
        answers[i] = verdict.model_copy(update={"judge": judge.name, "judge_version": judge.version,
                                                "second_opinion": identity(escalation)})
    return answers


def judges_name(judge: Judge, escalation: Judge | None) -> str:
    return identity(judge) + (f" > {identity(escalation)}" if escalation else "")


class Judging:
    def __init__(self, settings: Settings, judge: Judge | None, escalation: Judge | None, store: VerdictStore) -> None:
        self.settings, self.judge, self.escalation, self.store = settings, judge, escalation, store
        self.ledger = Ledger(settings)

    @classmethod
    def configured(cls, settings: Settings, store: VerdictStore) -> "Judging":
        judge = make_judge(settings.judge)
        escalation = make_escalation(settings) if judge is not None else None
        return cls(settings, judge, escalation, store)

    @property
    def name(self) -> str | None:
        if self.judge is None:
            return None
        return judges_name(self.judge, self.escalation)

    def summary(self) -> JudgingSummary:
        """What judged this run, on which thresholds, and what it cost: shown on every report."""
        band = self.settings.escalate.between if self.escalation and self.settings.escalate else None
        return JudgingSummary(
            preset=self.settings.preset, judge=identity(self.judge) if self.judge else None,
            escalation=identity(self.escalation) if self.escalation else None, band=band,
            report_at=self.settings.report_at, fail_at=max(self.settings.report_at, self.settings.fail_at),
            budget_usd=self.settings.budget.usd, subscription_calls=self.settings.budget.subscription_calls,
            spend=list(self.ledger.spend.values()))

    def findings(self, candidates: list[Candidate], source: Run | None = None, refresh: bool = False) -> list[Finding]:
        """A finding per proposed candidate: unjudged when there is no judge, else from the store or the judge."""
        proposed = [c for c in candidates if c.filtered is None]
        if self.judge is None:
            return [Finding(candidate=c) for c in proposed]
        version = self.judge.version if refresh or getattr(self.judge, "context", False) else None
        known = [self.store.lookup(c, self.judge.name, self.settings.reopen_margin, version).verdict for c in proposed]
        pending = [i for i, verdict in enumerate(known) if verdict is None]
        deferred = set(pending[self.settings.max_judgements:]) if self.settings.max_judgements is not None else set()
        pending = [i for i in pending if i not in deferred]
        if pending:
            asked = [proposed[i] for i in pending]
            for i, verdict in zip(pending, decide(asked, self.judge, self.escalation, self.settings, self.ledger)):
                if verdict is None:
                    deferred.add(i)  # the budget ran out before this pair: not cleared, asked again next run
                else:
                    self.store.remember(proposed[i], verdict, source)
                known[i] = verdict
        return [Finding(candidate=c, verdict=known[i], cached=known[i] is not None and i not in pending,
                        deferred=i in deferred) for i, c in enumerate(proposed)]
