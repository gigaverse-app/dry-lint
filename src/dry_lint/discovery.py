"""Durable admission for paid discovery. Reservations commit before a provider is contacted."""

import hashlib
import math
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from dry_lint.costs import judging_input, price, usage_cost
from dry_lint.models import Candidate, Run, evidence
from dry_lint.plugins import Judge, identity
from dry_lint.settings import Settings


class Attempt(BaseModel):
    revision: str
    evidence: str
    lane: str
    query: str
    usd: float
    status: str = "reserved"
    residual: bool = False
    source_evidence: str = ""
    subscription: bool = False


class Campaign(BaseModel):
    schema_version: int = 3
    revisions: list[str] = Field(default_factory=list)
    attempts: list[Attempt] = Field(default_factory=list)
    credit: float = 0.0
    prior_usd: float = 0.0

    @property
    def usd(self) -> float:
        return self.prior_usd + sum(a.usd for a in self.attempts)


class CampaignStore:
    """SQLite serializes admission across local processes; no lock is held during network calls.

    Keep this file on persistent local storage. CI must serialize a PR's restore/run/save lifecycle.
    A lost cache cannot guarantee a cumulative cap; it must not be advertised as a durable ledger.
    """

    def __init__(self, path: Path, run: Run) -> None:
        if not run.session and run.pull_request is None:
            raise ValueError("Discovery requires a session or pull request identity")
        self.path = path
        scope = f"pr:{run.pull_request}" if run.pull_request is not None else f"session:{run.session}"
        self.key = hashlib.sha256(f"{run.repository}|{scope}".encode()).hexdigest()
        self.revision = run.revision or run.head
        if not self.revision:
            raise ValueError("Discovery requires an immutable source revision")
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS campaigns (key TEXT PRIMARY KEY, state TEXT NOT NULL)")

    @contextmanager
    def transaction(self) -> Iterator[Campaign]:
        with closing(sqlite3.connect(self.path, timeout=30)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM campaigns WHERE key = ?", (self.key,)).fetchone()
            state = Campaign.model_validate_json(row[0]) if row else Campaign()
            yield state
            state.schema_version = 3
            db.execute("INSERT OR REPLACE INTO campaigns VALUES (?, ?)", (self.key, state.model_dump_json()))

    def snapshot(self) -> Campaign:
        with self.transaction() as state:
            return state.model_copy(deep=True)

    def advance(self, settings: Settings, prior_usd: float = 0.0) -> None:
        with self.transaction() as state:
            state.prior_usd = max(state.prior_usd, prior_usd)
            cap = settings.budget.usd * (1 - settings.discovery.baseline_fraction)
            if self.revision not in state.revisions:
                state.revisions.append(self.revision)
                state.credit = min(cap, state.credit + settings.discovery.exploration_per_revision)

    def recovery_ready(self, settings: Settings, candidates: list[Candidate]) -> bool:
        """Avoid constructing a recovery plugin when neither admission nor recovery cache work can run.

        This is only a lazy-loading gate; reserve repeats the authoritative checks atomically.
        """
        state = self.snapshot()
        current = [a for a in state.attempts if a.revision == self.revision]
        sources = {evidence(c) for c in candidates}
        # Cached successful recovery remains readable after a later failure or exhaustion. Loading the
        # current plugin still verifies its exact version; an earlier policy cannot answer this one.
        if any(a.residual and a.status == "answered" and a.source_evidence in sources for a in state.attempts):
            return True
        return (
            all(a.status == "answered" for a in current)
            and state.usd < settings.budget.usd
            and self.call_room(state, current, settings, exploration=True)
        )

    @staticmethod
    def call_room(state: Campaign, current: list[Attempt], settings: Settings, *, exploration: bool) -> bool:
        policy = settings.discovery
        limit = min(policy.calls_per_revision, settings.max_judgements or policy.calls_per_revision)
        return (
            len(current) < limit
            and len(state.attempts) < policy.calls
            and (
                not exploration or sum(a.lane == "exploration" for a in current) < policy.exploration_calls_per_revision
            )
        )

    def reserve(
        self, candidate: Candidate, judge: Judge, settings: Settings, usd: float, *, residual: bool = False
    ) -> int | Literal["budget"] | None:
        policy = settings.discovery
        if residual and not policy.residual_comparers or candidate.residual and not residual:
            raise ValueError("Residual admission requires an explicitly configured residual phase")
        version = evidence(candidate, identity(judge))
        with self.transaction() as state:
            exploration_cap = settings.budget.usd * (1 - policy.baseline_fraction)
            if self.revision not in state.revisions:
                state.revisions.append(self.revision)
                state.credit = min(exploration_cap, state.credit + policy.exploration_per_revision)
            current = [a for a in state.attempts if a.revision == self.revision]
            # A concurrent/abandoned or failed attempt is not a completed protected pass.
            if residual and any(a.status != "answered" for a in current):
                return None
            # Repeated attempts on one tree do not mint calls or credit, including failed/abandoned requests.
            if any(
                a.evidence == version or ((residual or a.residual) and a.source_evidence == evidence(candidate))
                for a in current
            ):
                return None
            if not self.call_room(state, current, settings, exploration=candidate.lane == "exploration"):
                return None
            if (
                getattr(judge, "subscription", False)
                and sum(a.subscription for a in current) >= settings.budget.subscription_calls
            ):
                return None
            room = settings.budget.usd - state.usd
            if candidate.lane == "exploration":
                explored = [a for a in state.attempts if a.lane == "exploration"]
                if not residual:
                    if len(explored) >= int(policy.calls * (1 - policy.baseline_fraction)):
                        return None
                    # Only an explicit residual phase may borrow future baseline capacity.
                    room = min(room, exploration_cap - sum(a.usd for a in explored), state.credit)
            if usd > room + 1e-12:
                return "budget"
            state.attempts.append(
                Attempt(
                    revision=self.revision,
                    evidence=version,
                    lane=candidate.lane,
                    query=candidate.new.qualname,
                    usd=usd,
                    residual=residual,
                    source_evidence=evidence(candidate),
                    subscription=getattr(judge, "subscription", False),
                )
            )
            if candidate.lane == "exploration" and not residual:
                state.credit -= usd
            return len(state.attempts) - 1

    def reserve_family(
        self,
        key: str,
        source_key: str,
        query: str,
        settings: Settings,
        usd: float,
        *,
        subscription: bool = False,
    ) -> int | Literal["budget"] | None:
        """A whole family consumes one residual question, with the same total caps and failure holds."""
        if settings.discovery.families is None or not settings.discovery.enabled:
            raise ValueError("Operation-family admission requires explicit native discovery opt-in")
        if not math.isfinite(usd) or usd < 0:
            raise ValueError("Family reservation must be a finite nonnegative cost")
        with self.transaction() as state:
            if self.revision not in state.revisions:
                raise ValueError("The protected campaign phase must run before family recovery")
            current = [attempt for attempt in state.attempts if attempt.revision == self.revision]
            if any(attempt.status != "answered" for attempt in current):
                return None
            # A changed policy cannot trigger a second paid assessment of the same complete family this revision.
            if any(attempt.evidence == key or attempt.source_evidence == "family:" + source_key for attempt in current):
                return None
            if not self.call_room(state, current, settings, exploration=True):
                return None
            if subscription and sum(attempt.subscription for attempt in current) >= settings.budget.subscription_calls:
                return None
            if usd > settings.budget.usd - state.usd + 1e-12:
                return "budget"
            state.attempts.append(
                Attempt(
                    revision=self.revision,
                    evidence=key,
                    lane="exploration",
                    query=query,
                    usd=usd,
                    residual=True,
                    source_evidence="family:" + source_key,
                    subscription=subscription,
                )
            )
            # Family recovery never mints protected exploration credit.
            return len(state.attempts) - 1

    def settle(self, reservation: int, usd: float | None, success: bool) -> float:
        with self.transaction() as state:
            attempt = state.attempts[reservation]
            if usd is not None:
                if attempt.lane == "exploration" and not attempt.residual:
                    state.credit += attempt.usd - usd
                attempt.usd = usd
            # Unknown usage stays charged at the reservation, even when a provider or process failed.
            attempt.status = "answered" if success else "failed"
            return attempt.usd

    def order(self, candidates: list[Candidate]) -> list[Candidate]:
        state = self.snapshot()
        counts: dict[tuple[str, str], int] = {}
        for attempt in state.attempts:
            key = (attempt.lane, attempt.query)
            counts[key] = counts.get(key, 0) + 1
        ordered, pending = [], list(candidates)
        while pending:
            candidate = min(
                pending,
                key=lambda c: (
                    c.lane != "baseline",
                    -c.priority,
                    counts.get((c.lane, c.new.qualname), 0),
                    -c.similarity,
                    c.key,
                ),
            )
            pending.remove(candidate)
            ordered.append(candidate)
            key = (candidate.lane, candidate.new.qualname)
            counts[key] = counts.get(key, 0) + 1
        return ordered


def reservation_cost(judge: Judge, candidate: Candidate, settings: Settings) -> float:
    rates = price(judge, settings)
    maximum = getattr(judge, "max_tokens", None)
    if rates is None or maximum is None and rates[1] != 0:
        raise ValueError("Discovery needs a priced judge with a maximum output token limit")
    return conservative_cost(judging_input(judge, candidate), maximum or 0, rates)


def conservative_cost(text: str, output_tokens: int, rates: tuple[float, float]) -> float:
    """An admission bound: UTF-8 bytes plus framing as input, and the full output ceiling; actual usage settles."""
    return usage_cost({"input": len(text.encode("utf-8")) + 1024, "output": output_tokens}, rates)
