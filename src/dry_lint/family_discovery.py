"""Nominate and judge operation families using the existing campaign's remaining allowance."""

from itertools import combinations

from dry_lint.costs import Spend, price
from dry_lint.family_judging import (
    FamilyFinding,
    FamilyJudging,
    FamilyVerdictStore,
    family_key,
    family_reservation_cost,
)
from dry_lint.family_models import request_from_nomination
from dry_lint.operation_families import FamilyLimits, PythonOperationFamilies
from dry_lint.plugins import identity, load


class FamilyBackend:
    """Separate physical keys, also excluded from the pair store's record enumeration."""

    def __init__(self, store):
        scoped = store.scoped("operation-families:v1")
        self.backend, self.prefix = scoped.backend, scoped.prefix

    def get(self, key):
        return self.backend.get(self.prefix + key)

    def put(self, key, value):
        self.backend.put(self.prefix + key, value)

    def keys(self):
        return (key.removeprefix(self.prefix) for key in self.backend.keys() if key.startswith(self.prefix))


class FamilyAdmission:
    """No separate dollar allowance: reservations and failures share the native pair ledger."""

    def __init__(self, judging):
        self.judging = judging
        self.reservations = {}

    def reserve(self, request, judge, usd):
        campaign = self.judging.campaign
        if campaign is None:
            raise ValueError("Family judging requires native campaign admission")
        reserved = campaign.reserve_family(
            family_key(request, judge),
            request.key,
            request.members[0].owner_id,
            self.judging.settings,
            usd,
            subscription=getattr(judge, "subscription", False),
        )
        spend = self.judging.ledger.spend.setdefault(
            identity(judge), Spend(judge=identity(judge), subscription=getattr(judge, "subscription", False))
        )
        if isinstance(reserved, int):
            self.reservations[reserved] = spend
        else:
            spend.skipped += 1
        return reserved

    def settle(self, reservation, usd, success):
        charged = self.judging.campaign.settle(reservation, usd, success)
        spend = self.reservations.pop(reservation)
        spend.calls += 1
        spend.usd += charged
        if not success:
            spend.failed += 1
            spend.error = "Family judgment failed; its reservation remains accounted"
        return charged


class FamilyDiscovery:
    """Retain complete source and rank distinct operations by removable work per reserved dollar."""

    def __init__(self, functions, changed, run, configuration, *, settled=None):
        self.configuration = configuration
        self.batch = PythonOperationFamilies(FamilyLimits(max_owners=configuration.max_members)).nominate(
            functions, run=run, changed={function.qualname for function in changed}
        )
        self.requests = []
        self.rejected = []
        for nomination in self.batch.nominations:
            # Use the same core/adopter decisions as pair detection. Do not clip a ruled-out family into
            # a different membership question: omit it whole and retain the visible policy reason.
            reason = next(
                (
                    reason
                    for a, b in combinations(nomination.owners, 2)
                    if settled is not None and (reason := settled(a.function, b.function))
                ),
                None,
            )
            if reason:
                self.rejected.append(
                    {"nomination_id": nomination.nomination_id, "kind": "rule", "reason": f"Settled by rule: {reason}"}
                )
                continue
            try:
                request = request_from_nomination(nomination)
            except ValueError as error:
                # Oversized or invalid source is visible as an exclusion, never a clipped paid question.
                self.rejected.append({"nomination_id": nomination.nomination_id, "reason": str(error)})
                continue
            self.requests.append((nomination.benefit.removable_statements, request))
        self.findings = [FamilyFinding(request=request, status="unjudged") for _, request in self.requests]

    def __call__(self, judging, protected_findings, source):
        if not self.requests or judging.judge is None:
            return
        if any(finding.deferred and finding.candidate.lane == "baseline" for finding in protected_findings):
            return
        campaign = judging.campaign
        state = campaign.snapshot()
        current = [attempt for attempt in state.attempts if attempt.revision == campaign.revision]
        sources = {"family:" + request.key for _, request in self.requests}
        cached_work = any(
            attempt.status == "answered" and attempt.source_evidence in sources for attempt in state.attempts
        )
        if not cached_work and (
            any(attempt.status != "answered" for attempt in current)
            or state.usd >= judging.settings.budget.usd
            or not campaign.call_room(state, current, judging.settings, exploration=True)
        ):
            status = "budget" if state.usd >= judging.settings.budget.usd else "deferred"
            self.findings = [FamilyFinding(request=request, status=status) for _, request in self.requests]
            return
        try:
            judge = load("judges", self.configuration.judge)
        except (ValueError, ImportError) as error:
            self.findings = [
                FamilyFinding(request=request, status="failed", error=type(error).__name__)
                for _, request in self.requests
            ]
            return
        try:
            self._execute(judging, judge)
        finally:
            close = getattr(judge, "close", None)
            if close is not None:
                close()

    def _execute(self, judging, judge):
        if not hasattr(judge, "judge_family"):
            raise ValueError("discovery.families.judge must implement family judging")
        rates = price(judge, judging.settings)
        if rates is None:
            raise ValueError("Family discovery requires configured model prices")
        # Cache-only/no-key runs still name the actual policy, with zero calls and charge.
        judging.ledger.spend.setdefault(
            identity(judge), Spend(judge=identity(judge), subscription=getattr(judge, "subscription", False))
        )
        store = FamilyVerdictStore(FamilyBackend(judging.store))
        execution = FamilyJudging(judge, store, FamilyAdmission(judging), rates)
        priced = []
        self.findings = []
        for benefit, request in self.requests:
            try:
                reservation = family_reservation_cost(request, judge, rates)
            except ValueError:
                self.findings.append(
                    FamilyFinding(
                        request=request,
                        status="deferred",
                        error="Family prompt exceeds the configured complete-source bound",
                    )
                )
                continue
            priced.append((-benefit / max(reservation, 1e-12), -benefit, request.key, request))
        ranked = sorted(priced, key=lambda entry: entry[:3])
        for *_, request in ranked[: self.configuration.max_questions]:
            self.findings.append(execution.finding(request))
        for *_, request in ranked[self.configuration.max_questions :]:
            self.findings.append(FamilyFinding(request=request, status="deferred"))
