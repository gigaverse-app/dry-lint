"""Drives the real CampaignStore on a temporary SQLite ledger. No ledger logic lives here.

Each mutant breaks exactly one rule of the ledger; the contract must notice every one.
"""

import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from campaign_driver import Attempt, CampaignDriver, Outcome, View
from pytest_quint_connect import HistoryContext

from dry_lint import discovery
from dry_lint.discovery import Campaign, CampaignStore
from dry_lint.models import Candidate, Function, Run
from dry_lint.settings import ExplorationComparer, FamilyDiscovery, Settings

EIGHTH = 0.125  # the model's money unit; every amount is exact in binary floating point


def units(usd: float) -> int:
    value = usd / EIGHTH
    assert value == int(value), f"{usd} is not a whole number of eighths"
    return int(value)


def settings() -> Settings:
    configured = Settings()
    configured.budget.usd = 8 * EIGHTH
    policy = configured.discovery
    policy.enabled, policy.baseline_fraction, policy.exploration_per_revision = True, 0.5, 2 * EIGHTH
    policy.calls_per_revision, policy.exploration_calls_per_revision, policy.calls = 3, 2, 5
    policy.residual_comparers = [ExplorationComparer(use="tfidf")]
    policy.families = FamilyDiscovery(judge="family-judge")
    return configured


class Judge:
    name, version, model, max_tokens = "judge", "v1", "model", 100


def candidate(cand: str, kind: str) -> Candidate:
    new = Function(path=f"{cand}.py", name=cand, line=1, end_line=2, code=f"def {cand}():\n    return 1", tokens=[cand])
    old = Function(path=f"{cand}_old.py", name="old", line=1, end_line=2, code="def old():\n    return 2", tokens=["o"])
    lane = "baseline" if kind == "baseline" else "exploration"
    return Candidate(new=new, existing=old, similarity=0.9, lane=lane, residual=kind == "residual")


class DoubleSettle(CampaignStore):
    def settle(self, reservation: int, usd: float | None, success: bool) -> float:
        # A planted bug: reopens the reservation so the real settle() accepts it again.
        # dry-lint: distinct-from src/dry_lint/discovery.py::CampaignStore.settle
        with self.transaction() as state:
            state.attempts[reservation].status = "reserved"
        return super().settle(reservation, usd, success)


class CreditPerCall(CampaignStore):
    def _enter(self, state: Campaign, settings: Settings) -> float:
        # A planted bug: mints credit again when the revision was already entered.
        # dry-lint: distinct-from src/dry_lint/discovery.py::CampaignStore._enter
        seen = self.revision in state.revisions
        cap = super()._enter(state, settings)
        if seen:
            state.credit = min(cap, state.credit + settings.discovery.exploration_per_revision)
        return cap


class ResidualSkipsPass(CampaignStore):
    hide = False

    def reserve(self, candidate: Candidate, judge, settings: Settings, usd: float, *, residual: bool = False):
        self.hide = residual
        try:
            return super().reserve(candidate, judge, settings, usd, residual=residual)
        finally:
            self.hide = False

    @contextmanager
    def transaction(self) -> Iterator[Campaign]:
        with super().transaction() as state:
            if not self.hide:
                yield state
                return
            statuses = [attempt.status for attempt in state.attempts]
            for attempt in state.attempts:
                attempt.status = "answered"
            yield state
            for attempt, status in zip(state.attempts, statuses, strict=False):
                attempt.status = status


class NoDedupe(CampaignStore):
    def reserve(self, candidate: Candidate, judge, settings: Settings, usd: float, *, residual: bool = False):
        calls = iter(range(10**9))
        with patch.object(discovery, "evidence", lambda *args: f"unique-{next(calls)}-{id(args)}"):
            return super().reserve(candidate, judge, settings, usd, residual=residual)


MUTANTS: dict[str, type[CampaignStore]] = {
    "double-settle": DoubleSettle,
    "credit-per-call": CreditPerCall,
    "residual-skips-pass": ResidualSkipsPass,
    "no-dedupe": NoDedupe,
}


class LedgerDriver(CampaignDriver):
    def __init__(self, store_type: type[CampaignStore]) -> None:
        self.store_type = store_type
        self.folder = tempfile.TemporaryDirectory()
        self.settings = settings()
        self.rev, self.outcome = 0, {"tag": "NoOutcome"}
        self.store = self.open()

    def open(self) -> CampaignStore:
        run = Run(repository="owner/repo", session="contract", revision=f"r{self.rev}")
        return self.store_type(Path(self.folder.name) / "campaign.sqlite3", run)

    def init(self) -> None:
        self.outcome = {"tag": "NoOutcome"}

    def push(self) -> None:
        self.rev += 1
        self.store, self.outcome = self.open(), {"tag": "NoOutcome"}

    def advance(self) -> None:
        self.store.advance(self.settings)
        self.outcome = {"tag": "NoOutcome"}

    def admitted(self, result: int | str | None) -> Outcome:
        if result is None or result == "limit":
            return {"tag": "Refused"}
        if result == "budget":
            return {"tag": "OverBudget"}
        return {"tag": "Reserved", "value": result}

    def reserve(self, kind: str, cand: str, cost: int) -> None:
        result = self.store.reserve(
            candidate(cand, kind), Judge(), self.settings, cost * EIGHTH, residual=kind == "residual"
        )
        self.outcome = self.admitted(result)

    def reserve_family(self, cost: int) -> None:
        try:
            result = self.store.reserve_family("family-key", "family-source", "family", self.settings, cost * EIGHTH)
        except ValueError as error:
            assert "protected campaign phase" in str(error), error
            self.outcome = {"tag": "NotEntered"}
            return
        self.outcome = self.admitted(result)

    def settle(self, idx: int, actual: int, success: bool) -> None:
        try:
            charged = self.store.settle(idx, None if actual < 0 else actual * EIGHTH, success)
        except ValueError as error:
            assert "already settled" in str(error), error
            self.outcome = {"tag": "AlreadySettled"}
            return
        self.outcome = {"tag": "Settled", "value": units(charged)}

    def inspect(self) -> None:
        pass

    def observe(self) -> View:
        state = self.store.snapshot()

        def attempt(a) -> Attempt:
            if a.source_evidence.startswith("family:"):
                kind, cand = "family", "family"
            else:
                kind = "baseline" if a.lane == "baseline" else "residual" if a.residual else "exploration"
                cand = a.query.split("::")[-1]
            return {"rev": int(a.revision[1:]), "kind": kind, "cand": cand, "cost": units(a.usd), "status": a.status}

        return {
            "rev": self.rev,
            "revisions": len(state.revisions),
            "credit": units(state.credit),
            "attempts": [attempt(a) for a in state.attempts],
            "outcome": self.outcome,
        }

    def close(self) -> None:
        self.folder.cleanup()


@pytest.fixture
def campaign_driver() -> Callable[[HistoryContext], LedgerDriver]:
    return lambda context: LedgerDriver(MUTANTS.get(context.mutant, CampaignStore))
