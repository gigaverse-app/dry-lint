"""
The judge step, which is core whatever judge is plugged in: for every candidate, the stored verdict when it still
holds, otherwise the judge's answer; for first scores in the escalation band, a second judge's answer instead.
Every new answer goes to the store. Filtered pairs never reach a judge.
"""

import subprocess
from pathlib import Path

import httpx

from dry_lint.costs import Ledger
from dry_lint.git import git
from dry_lint.judges import make_escalation, make_judge
from dry_lint.models import Candidate, Run, Verdict
from dry_lint.plugins import Judge, identity, load
from dry_lint.report import Finding, JudgingSummary
from dry_lint.settings import Settings
from dry_lint.store import DirectoryStore, VerdictStore

# What a judge raises when it cannot answer: a CLI that fails or times out, an API error, an answer without a verdict.
JUDGE_ERRORS = (subprocess.SubprocessError, httpx.HTTPError, ValueError, OSError)


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
    alikes for the first judge; for the second, the first scores nearest the middle of the band, where the first
    judge is least sure. A pair the first judge could not afford stays unjudged (None); one the second could not
    afford keeps the first judge's answer. So does every pair the second judge was asked about when it fails (an
    expired login, an outage), as long as there is a ledger to record that on.
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
    middle = (low + high) / 2
    unsure = sorted((i for i, v in enumerate(answers) if v is not None and low <= v.score < high),
                    key=lambda i: abs(answers[i].score - middle))
    allowed = ledger.affordable(escalation, [candidates[i] for i in unsure]) if ledger else len(unsure)
    escalated = [candidates[i] for i in unsure[:allowed]]
    try:
        second = escalation.judge(escalated, settings) if allowed else []
    except JUDGE_ERRORS as error:
        if ledger is None:
            raise
        ledger.fail(escalation, escalated, error)
        return answers
    if ledger:
        ledger.charge(escalation, escalated, skipped=len(unsure) - allowed)
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
        self.pull_request = False

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
            spend=list(self.ledger.spend.values()), spent_before=self.ledger.spent, pull_request=self.pull_request)

    def unsure(self, verdict: Verdict) -> bool:
        """A first answer in the escalation band, which the second judge did not replace."""
        band = self.settings.escalate.between if self.escalation and self.settings.escalate else None
        return band is not None and verdict.second_opinion is None and band[0] <= verdict.score < band[1]

    def findings(self, candidates: list[Candidate], source: Run | None = None, refresh: bool = False) -> list[Finding]:
        """A finding per proposed candidate: unjudged when there is no judge, else from the store or the judge."""
        proposed = [c for c in candidates if c.filtered is None]
        if self.judge is None:
            return [Finding(candidate=c) for c in proposed]
        # The budget is for the whole pull request, not this run; known even when nothing is left to judge.
        self.ledger.spent = self.store.spent(source)
        self.pull_request = source is not None and source.pull_request is not None
        strict = getattr(self.judge, "context", False) or getattr(self.judge, "strict_version", False)
        version = self.judge.version if refresh or strict else None
        second = identity(self.escalation) if self.escalation and self.settings.escalate else None
        band = self.settings.escalate.between if second and self.settings.escalate else (0.0, 0.0)
        known = [self.store.lookup(c, self.judge.name, self.settings.reopen_margin, version, second, band).verdict
                 for c in proposed]
        # A cached first answer the second judge has not seen yet: it stands whenever this run cannot ask again.
        first = {i: self.store.lookup(c, self.judge.name, self.settings.reopen_margin, version).verdict
                 for i, c in enumerate(proposed) if second and known[i] is None}
        cached = {i for i, verdict in enumerate(known) if verdict is not None}
        pending = [i for i, verdict in enumerate(known) if verdict is None]
        deferred = set(pending[self.settings.max_judgements:]) if self.settings.max_judgements is not None else set()
        pending = [i for i in pending if i not in deferred]
        if pending:
            asked = [proposed[i] for i in pending]
            for i, verdict in zip(pending, decide(asked, self.judge, self.escalation, self.settings, self.ledger)):
                if verdict is None:
                    deferred.add(i)  # the budget ran out before this pair: not cleared, asked again next run
                elif not (self.ledger.failed and self.unsure(verdict)):  # else asked again once the judge is back
                    self.store.remember(proposed[i], verdict, source)
                known[i] = verdict
            self.store.add_spent(source, self.ledger.usd)
        for i in [i for i in deferred if first.get(i) is not None]:
            known[i], cached = first[i], cached | {i}
            deferred.discard(i)
        return [Finding(candidate=c, verdict=known[i], cached=i in cached, deferred=i in deferred)
                for i, c in enumerate(proposed)]
