"""
The judge step, which is core whatever judge is plugged in: for every candidate, the stored verdict when it still
holds, otherwise the judge's answer; for first scores in the escalation band, a second judge's answer instead.
Every new answer goes to the store. Filtered pairs never reach a judge.
"""

import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from dry_lint.costs import Ledger, Spend, price, usage_cost
from dry_lint.discovery import CampaignStore, reservation_cost
from dry_lint.git import git
from dry_lint.judges import make_escalation, make_judge
from dry_lint.models import Candidate, Run, Verdict, evidence
from dry_lint.plugins import Judge, accepted_identities, accepted_versions, identity, load
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


def decide(
    candidates: list[Candidate],
    judge: Judge,
    escalation: Judge | None,
    settings: Settings,
    ledger: Ledger | None = None,
) -> list[Verdict | None]:
    """
    The first judge's answers, with those in the escalation band replaced by the second judge's answers, kept under
    the first judge's name with `second_opinion` set, so they are stored and reused like any other.

    With a `ledger`, each judge is asked only about the pairs the budget covers, riskiest first: the closest look-
    alikes for the first judge; for the second, the first scores nearest the middle of the band, where the first
    judge is least sure. Single-judge and second-opinion queues skip unaffordable entries and try later ones;
    a cascade's first pass retains its prefix so extra first judgments cannot crowd out its second opinions.
    A pair the first judge could not afford stays unjudged (None); one the second could not
    afford keeps the first judge's answer. So does every pair the second judge was asked about when it fails (an
    expired login, an outage), as long as there is a ledger to record that on.
    """
    order = sorted(range(len(candidates)), key=lambda i: (-candidates[i].priority, -candidates[i].similarity))
    # Preserve the cascade's first-pass prefix: refilling it could consume the allowance its second judge needs.
    cascade = escalation is not None and settings.escalate is not None
    selected = (
        ledger.select(judge, [candidates[i] for i in order], prefix_only=cascade) if ledger else range(len(order))
    )
    asked = [order[i] for i in selected]
    answers: list[Verdict | None] = [None] * len(candidates)
    for i, verdict in zip(asked, judge.judge([candidates[i] for i in asked], settings) if asked else [], strict=True):
        answers[i] = verdict
    if ledger:
        ledger.charge(judge, [candidates[i] for i in asked], skipped=len(order) - len(asked))
    if escalation is None or settings.escalate is None:
        return answers
    low, high = settings.escalate.between
    middle = (low + high) / 2
    unsure = sorted(
        (i for i, v in enumerate(answers) if v is not None and low <= v.score < high),
        key=lambda i: abs(answers[i].score - middle),
    )
    selected = ledger.select(escalation, [candidates[i] for i in unsure]) if ledger else range(len(unsure))
    asked = [unsure[i] for i in selected]
    escalated = [candidates[i] for i in asked]
    try:
        second = escalation.judge(escalated, settings) if escalated else []
    except JUDGE_ERRORS as error:
        if ledger is None:
            raise
        ledger.fail(escalation, escalated, error)
        return answers
    if ledger:
        ledger.charge(escalation, escalated, skipped=len(unsure) - len(asked))
    for i, verdict in zip(asked, second, strict=True):
        answers[i] = verdict.model_copy(
            update={"judge": judge.name, "judge_version": judge.version, "second_opinion": identity(escalation)}
        )
    return answers


def judges_name(judge: Judge, escalation: Judge | None) -> str:
    return identity(judge) + (f" > {identity(escalation)}" if escalation else "")


class Judging:
    def __init__(self, settings: Settings, judge: Judge | None, escalation: Judge | None, store: VerdictStore) -> None:
        self.settings, self.judge, self.escalation, self.store = settings, judge, escalation, store
        self.ledger = Ledger(settings)
        self.pull_request = False
        self.campaign: CampaignStore | None = None
        self.residual_judge: Judge | None = None
        self.family_recovery = None

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
            preset=self.settings.preset,
            judge=identity(self.judge) if self.judge else None,
            escalation=identity(self.escalation) if self.escalation else None,
            band=band,
            report_at=self.settings.report_at,
            fail_at=max(self.settings.report_at, self.settings.fail_at),
            budget_usd=self.settings.budget.usd,
            subscription_calls=self.settings.budget.subscription_calls,
            spend=list(self.ledger.spend.values()),
            spent_before=self.ledger.spent,
            pull_request=self.pull_request,
            campaign=self.campaign.key if self.campaign else "",
            exploration_credit=self.campaign.snapshot().credit if self.campaign else 0,
        )

    def unsure(self, verdict: Verdict) -> bool:
        """A first answer in the escalation band, which the second judge did not replace."""
        band = self.settings.escalate.between if self.escalation and self.settings.escalate else None
        return band is not None and verdict.second_opinion is None and band[0] <= verdict.score < band[1]

    def findings(self, candidates: list[Candidate], source: Run | None = None, refresh: bool = False) -> list[Finding]:
        """
        A finding per proposed candidate: unjudged when there is no judge, else from the store or the judge. A
        relative is asked about only once its parent pair is reported, and only within what the budget has left.
        """
        proposed = [c for c in candidates if c.filtered is None and c.lane != "relative"]
        if self.judge is None:
            return [Finding(candidate=c) for c in proposed]
        if any(c.residual for c in proposed) and not self.settings.discovery.residual_comparers:
            raise ValueError("Residual candidates require explicit discovery.residual_comparers opt-in")
        if self.campaign is not None:
            return self.discover(proposed, source)
        if self.settings.discovery.residual_comparers:
            raise ValueError("Residual discovery requires native campaign admission")
        # The budget is for the whole pull request, not this run; known even when nothing is left to judge.
        self.ledger.spent = self.store.spent(source)
        self.pull_request = source is not None and source.pull_request is not None
        found = self.assess(proposed, source, refresh)
        reported = {
            f.candidate.key
            for f in found
            if f.verdict
            and f.verdict.model_assessment is None
            and self.settings.duplicate_at(f.verdict, self.settings.report_at)
        }
        relatives = [c for c in candidates if c.filtered is None and c.lane == "relative" and c.parent in reported]
        found += [f for f in self.assess(relatives, source, refresh, advisory=True) if not f.deferred]
        if self.family_recovery is not None:
            # After the complete pair pass, within what its budget left; recorded in the same spend.
            self.family_recovery(self, found, source)
        self.store.add_spent(source, self.ledger.usd)
        return found

    def assess(
        self, proposed: list[Candidate], source: Run | None, refresh: bool, *, advisory: bool = False
    ) -> list[Finding]:
        """
        From the store when it still holds, else from the judges. `advisory` pairs (relatives) never block, so one
        judge answers them, closest first, and those the budget does not cover are deferred rather than skipped.
        """
        assert self.judge is not None
        escalation = None if advisory else self.escalation
        strict = getattr(self.judge, "context", False) or getattr(self.judge, "strict_version", False)
        # --refresh asks again for every answer not of this exact version, older ones the judge accepts included.
        versions = frozenset({self.judge.version}) if refresh else accepted_versions(self.judge) if strict else None
        second = identity(escalation) if escalation and self.settings.escalate else None
        seconds = accepted_identities(escalation) if second and escalation and not refresh else frozenset()
        band = self.settings.escalate.between if second and self.settings.escalate else (0.0, 0.0)
        known = [
            self.store.lookup(
                c, self.judge.name, self.settings.reopen_margin, versions, second, band, escalations=seconds
            ).verdict
            for c in proposed
        ]
        # A cached first answer the second judge has not seen yet: it stands whenever this run cannot ask again.
        first = {
            i: self.store.lookup(c, self.judge.name, self.settings.reopen_margin, versions).verdict
            for i, c in enumerate(proposed)
            if second and known[i] is None
        }
        cached = {i for i, verdict in enumerate(known) if verdict is not None}
        pending = sorted((i for i, verdict in enumerate(known) if verdict is None), key=lambda i: -proposed[i].priority)
        deferred = set(pending[self.settings.max_judgements :]) if self.settings.max_judgements is not None else set()
        pending = [i for i in pending if i not in deferred]
        count_limited = deferred.copy()
        if advisory and pending:
            pending.sort(key=lambda i: (-proposed[i].priority, -proposed[i].similarity))
            affordable = self.ledger.affordable(self.judge, [proposed[i] for i in pending])
            deferred |= set(pending[affordable:])
            pending = pending[:affordable]
        if pending:
            asked = [proposed[i] for i in pending]
            for i, verdict in zip(
                pending, decide(asked, self.judge, escalation, self.settings, self.ledger), strict=True
            ):
                if verdict is None:
                    deferred.add(i)  # the budget ran out before this pair: not cleared, asked again next run
                elif not (self.ledger.failed and self.unsure(verdict)):  # else asked again once the judge is back
                    self.store.remember(proposed[i], verdict, source)
                known[i] = verdict
        for i in [i for i in deferred if first.get(i) is not None]:
            known[i], cached = first[i], cached | {i}
            deferred.discard(i)
        deferred.update(i for i, v in enumerate(known) if not advisory and v is not None and self.unsure(v))
        return [
            Finding(
                candidate=c,
                verdict=known[i],
                cached=i in cached,
                deferred=i in deferred,
                budget_deferred=i in deferred and i not in count_limited and not self.ledger.failed,
            )
            for i, c in enumerate(proposed)
        ]

    def discover(self, candidates: list[Candidate], source: Run | None) -> list[Finding]:
        """Production scheduler: exact cached answers, baseline first, then reserved exploration."""
        assert self.campaign is not None and self.judge is not None
        if self.escalation is not None:
            raise ValueError("Scheduled discovery currently uses one judge; disable escalation")
        judge, campaign = self.judge, self.campaign
        campaign.advance(self.settings, self.store.spent(source))
        self.ledger.spent = campaign.snapshot().usd
        self.pull_request = source is not None and source.pull_request is not None
        protected = [c for c in candidates if not c.residual]
        found = self.discovery_phase(protected, source)
        if not self.settings.discovery.residual_comparers and self.family_recovery is None:
            return found
        suffix = [c for c in candidates if c.residual]
        # Preserve the complete configured pass, including every exploration comparer. An unresolved baseline
        # still bars exploration. Only unattempted deferred exploration can join the recovery queue.
        blocked = [f for f in found if f.deferred and f.candidate.lane == "baseline"]
        if blocked:
            self.ledger.spend[identity(judge)].skipped += len(suffix)
            return found + [
                Finding(candidate=c, deferred=True, budget_deferred=all(f.budget_deferred for f in blocked))
                for c in suffix
            ]
        if self.family_recovery is not None:
            self.family_recovery(self, found, source)
        if not self.settings.discovery.residual_comparers:
            return found
        choice = self.settings.discovery.residual_judge
        attempted = {
            a.evidence
            for a in campaign.snapshot().attempts
            if a.revision == campaign.revision and (choice is None or not a.residual or not a.source_evidence)
        }
        pending = [f.candidate for f in found if f.deferred and evidence(f.candidate, identity(judge)) not in attempted]
        already_attempted = []
        if choice is not None:
            # Schema-2 attempts lack source_evidence but were all made by the protected judge.
            # Changing policy cannot turn those into a second paid question on the same revision.
            already_attempted = [c for c in suffix if evidence(c, identity(judge)) in attempted]
            suffix = [c for c in suffix if evidence(c, identity(judge)) not in attempted]
            # Load only after the complete protected pass and its barriers. A missing main judge,
            # empty recovery queue, failed/inflight prefix or exhausted cold campaign needs no plugin/key.
            sources = {evidence(candidate) for candidate in pending + suffix}
            if not pending and not suffix or not campaign.recovery_ready(self.settings, sources):
                self.ledger.spend[identity(judge)].skipped += len(suffix) + len(already_attempted)
                state = campaign.snapshot()
                current = [a for a in state.attempts if a.revision == campaign.revision]
                budget_only = all(a.status == "answered" for a in current) and (
                    state.usd >= self.settings.budget.usd
                    or not campaign.call_room(state, current, self.settings, exploration=True)
                )
                return (
                    found
                    + [Finding(candidate=c, deferred=True, budget_deferred=budget_only) for c in suffix]
                    + [Finding(candidate=c, deferred=True) for c in already_attempted]
                )
            if self.residual_judge is None:
                self.residual_judge = load("judges", choice)
        self.ledger.spend[identity(judge)].skipped -= len(pending)
        recovered = self.discovery_phase(pending + suffix, source, residual=True)
        self.ledger.spend[identity(judge)].skipped += len(already_attempted)
        recovered += [Finding(candidate=c, deferred=True) for c in already_attempted]
        replacements = {f.candidate.key: f for f in recovered}
        return [replacements.get(f.candidate.key, f) for f in found] + [f for f in recovered if f.candidate.residual]

    def discovery_phase(
        self, candidates: list[Candidate], source: Run | None, *, residual: bool = False
    ) -> list[Finding]:
        """One ordered pass; both phases use the same reservations, settlements and exact verdict cache.

        Pairs are asked up to the judge's own ``workers`` at a time. Each batch holds one lane, so the baseline
        barrier still sees every baseline answer before exploration reserves. A residual pass stays one at a
        time: its admission requires every earlier attempt of the revision to be answered.
        """
        assert self.campaign is not None and self.judge is not None
        judge = self.residual_judge if residual and self.residual_judge is not None else self.judge
        campaign = self.campaign
        store = self.store.scoped(f"residual:{identity(judge)}") if residual and self.residual_judge else self.store
        spend = self.ledger.spend.setdefault(
            identity(judge), Spend(judge=identity(judge), subscription=getattr(judge, "subscription", False))
        )
        workers = 1 if residual else max(1, int(getattr(judge, "workers", 1) or 1))
        findings: list[Finding | None] = []
        batch: list[tuple[int, Candidate, int, float]] = []
        baseline_pending = False
        baseline_budget_only = True

        def flush() -> None:
            nonlocal baseline_pending, baseline_budget_only
            for (slot, candidate, _, _), verdict in zip(
                batch, self.judge_reserved(judge, campaign, spend, batch), strict=True
            ):
                if verdict is not None:
                    store.remember(candidate, verdict, source)
                elif candidate.lane == "baseline":
                    baseline_pending, baseline_budget_only = True, False
                findings[slot] = Finding(candidate=candidate, verdict=verdict, deferred=verdict is None)
            batch.clear()

        for candidate in campaign.order(candidates):
            if batch and (candidate.lane != batch[0][1].lane or len(batch) >= workers):
                flush()
            cached = store.lookup(
                candidate, judge.name, self.settings.reopen_margin, accepted_versions(judge), exact_source=True
            ).verdict
            if cached is not None:
                findings.append(Finding(candidate=candidate, verdict=cached, cached=True))
                continue
            reservation = "budget" if baseline_pending and baseline_budget_only else None
            cost = reservation_cost(judge, candidate, self.settings)
            if not (baseline_pending and candidate.lane == "exploration"):
                reservation = campaign.reserve(candidate, judge, self.settings, cost, residual=residual)
                if reservation == "budget" and batch:
                    # A batch in flight holds its conservative bounds, several times what the answers cost.
                    # Settle it and ask once more, so the money that is really left decides, not the batch size.
                    # The batch is this candidate's own lane, so settling it cannot raise the baseline barrier
                    # against an exploration pair.
                    flush()
                    reservation = campaign.reserve(candidate, judge, self.settings, cost, residual=residual)
            if not isinstance(reservation, int):
                # A spent dollar budget or call cap leaves the pair for a later run: a budget gap, not a failure.
                gap = reservation in ("budget", "limit")
                if candidate.lane == "baseline":
                    baseline_pending = True
                    baseline_budget_only &= gap
                spend.skipped += 1
                findings.append(Finding(candidate=candidate, deferred=True, budget_deferred=gap))
                continue
            # Reservation is committed before any call. Crashes cannot give its allowance back.
            findings.append(None)
            batch.append((len(findings) - 1, candidate, reservation, cost))
        flush()
        assert all(finding is not None for finding in findings)
        return [finding for finding in findings if finding is not None]

    def judge_reserved(
        self, judge: Judge, campaign: CampaignStore, spend: Spend, batch: list[tuple[int, Candidate, int, float]]
    ) -> list[Verdict | None]:
        """Ask every reserved pair at once, one call each so one failure cannot void the others; settle each once.

        A judge counts tokens for all its calls together, so the batch's measured cost is shared in proportion to
        what each pair reserved. Every settlement is made here, after all calls returned or failed.
        """
        if not batch:
            return []
        tokens = getattr(judge, "tokens", None)
        before = dict(tokens) if tokens is not None else None

        def ask(candidate: Candidate) -> Verdict | str:
            try:
                answers = judge.judge([candidate], self.settings)
                if len(answers) != 1:
                    raise ValueError("Judge returned no single verdict")
                return answers[0]
            except JUDGE_ERRORS as error:
                return " ".join(str(error).split())[:200] or type(error).__name__

        # An interrupt that is not a judge error still settles every reservation, as failed.
        outcomes: list[Verdict | str | None] = [None] * len(batch)
        try:
            if len(batch) == 1:
                outcomes = [ask(batch[0][1])]
            else:
                with ThreadPoolExecutor(len(batch)) as pool:
                    outcomes = list(pool.map(ask, [candidate for _, candidate, _, _ in batch]))
        finally:
            rates = price(judge, self.settings)
            actual = None
            if before is not None and rates is not None and tokens != before:
                actual = usage_cost({key: value - before.get(key, 0) for key, value in tokens.items()}, rates)
            reserved = sum(cost for *_, cost in batch)
            left = actual
            for position, (_, _, reservation, cost) in enumerate(batch):
                share = None
                if actual is not None and left is not None:
                    last = position == len(batch) - 1
                    share = left if last else actual * (cost / reserved if reserved else 1 / len(batch))
                    left -= share
                outcome = outcomes[position]
                success = isinstance(outcome, Verdict)
                charged = campaign.settle(reservation, share, success)
                spend.calls += 1
                spend.usd += charged
                if not success:
                    spend.failed += 1
                    spend.error = outcome if isinstance(outcome, str) else "Judging was interrupted"
        return [outcome if isinstance(outcome, Verdict) else None for outcome in outcomes]
