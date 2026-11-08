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
    """No separate dollar allowance: family questions share the pair judging's allowance and its spend record.

    Subclasses decide whether a question fits (`admit`) and what it finally costs (`charge`); the spend record
    the summary reports is kept here, once.
    """

    def __init__(self, judging):
        self.judging = judging
        self.reservations = {}

    def reserve(self, request, judge, usd):
        reserved = self.admit(request, judge, usd)
        spend = self.judging.ledger.spend.setdefault(
            identity(judge), Spend(judge=identity(judge), subscription=getattr(judge, "subscription", False))
        )
        if isinstance(reserved, int):
            self.reservations[reserved] = spend
        else:
            spend.skipped += 1
        return reserved

    def settle(self, reservation, usd, success):
        charged = self.charge(reservation, usd, success)
        spend = self.reservations.pop(reservation)
        spend.calls += 1
        spend.usd += charged
        if not success:
            spend.failed += 1
            spend.error = "Family judgment failed; its reservation remains accounted"
        return charged


class CampaignFamilyAdmission(FamilyAdmission):
    """`check`: reservations and failures share the native pair campaign's ledger."""

    def admit(self, request, judge, usd):
        return self.judging.campaign.reserve_family(
            family_key(request, judge),
            request.key,
            request.members[0].owner_id,
            self.judging.settings,
            usd,
            subscription=getattr(judge, "subscription", False),
        )

    def charge(self, reservation, usd, success):
        return self.judging.campaign.settle(reservation, usd, success)


class BudgetFamilyAdmission(FamilyAdmission):
    """`scan`: no campaign, so a question fits what the run's pair budget has left, like any pair question.

    The conservative reservation is held until the answer settles; unknown usage keeps it charged.
    """

    def __init__(self, judging):
        super().__init__(judging)
        self.held = {}

    def admit(self, request, judge, usd):
        ledger, budget = self.judging.ledger, self.judging.settings.budget
        if getattr(judge, "subscription", False):
            used = sum(spend.calls for spend in ledger.spend.values() if spend.subscription)
            if used + len(self.held) >= budget.subscription_calls:
                return None
        if usd > budget.usd - ledger.spent - ledger.usd - sum(self.held.values()) + 1e-12:
            return "budget"
        reservation = len(self.reservations) + len(self.held) + 1
        while reservation in self.held:
            reservation += 1
        self.held[reservation] = usd
        return reservation

    def charge(self, reservation, usd, success):
        held = self.held.pop(reservation)
        return held if usd is None else usd


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
        if judging.campaign is None:
            # `scan`: the complete pair pass comes first; a pair the budget deferred leaves nothing for families.
            if any(finding.budget_deferred for finding in protected_findings):
                self.findings = [FamilyFinding(request=request, status="budget") for _, request in self.requests]
                return
        elif not self._campaign_ready(judging, protected_findings):
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

    def _campaign_ready(self, judging, protected_findings):
        """`check`: the protected pair pass is complete and the campaign still has room, or the answer is cached."""
        if any(finding.deferred and finding.candidate.lane == "baseline" for finding in protected_findings):
            return False
        campaign, settings = judging.campaign, judging.settings
        if campaign.recovery_ready(settings, {"family:" + request.key for _, request in self.requests}):
            return True
        status = "budget" if campaign.snapshot().usd >= settings.budget.usd else "deferred"
        self.findings = [FamilyFinding(request=request, status=status) for _, request in self.requests]
        return False

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
        admission = BudgetFamilyAdmission if judging.campaign is None else CampaignFamilyAdmission
        execution = FamilyJudging(judge, store, admission(judging), rates)
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
