"""Durable admission for paid discovery. Reservations commit before a provider is contacted."""

import hashlib
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterator

from pydantic import BaseModel, Field

from dry_lint.costs import price
from dry_lint.judges.command import prompt
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


class Campaign(BaseModel):
    schema_version: int = 1
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

    def reserve(self, candidate: Candidate, judge: Judge, settings: Settings, usd: float) -> int | None:
        policy = settings.discovery
        version = evidence(candidate, identity(judge))
        with self.transaction() as state:
            exploration_cap = settings.budget.usd * (1 - policy.baseline_fraction)
            if self.revision not in state.revisions:
                state.revisions.append(self.revision)
                state.credit = min(exploration_cap, state.credit + policy.exploration_per_revision)
            current = [a for a in state.attempts if a.revision == self.revision]
            # Repeated attempts on one tree do not mint calls or credit, including failed/abandoned requests.
            if any(a.evidence == version for a in current):
                return None
            limit = min(policy.calls_per_revision, settings.max_judgements or policy.calls_per_revision)
            if len(current) >= limit or len(state.attempts) >= policy.calls:
                return None
            room = settings.budget.usd - state.usd
            if candidate.lane == "exploration":
                explored = [a for a in state.attempts if a.lane == "exploration"]
                if sum(a.lane == "exploration" for a in current) >= policy.exploration_calls_per_revision:
                    return None
                if len(explored) >= int(policy.calls * (1 - policy.baseline_fraction)):
                    return None
                # Exploration cannot borrow the capacity reserved for future baseline evidence.
                room = min(room, exploration_cap - sum(a.usd for a in explored), state.credit)
            if usd > room + 1e-12:
                return None
            state.attempts.append(Attempt(revision=self.revision, evidence=version, lane=candidate.lane,
                                          query=candidate.new.qualname, usd=usd))
            if candidate.lane == "exploration":
                state.credit -= usd
            return len(state.attempts) - 1

    def settle(self, reservation: int, usd: float | None, success: bool) -> float:
        with self.transaction() as state:
            attempt = state.attempts[reservation]
            if usd is not None:
                if attempt.lane == "exploration":
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
            candidate = min(pending, key=lambda c: (c.lane != "baseline", counts.get((c.lane, c.new.qualname), 0),
                                                    -c.similarity, c.key))
            pending.remove(candidate)
            ordered.append(candidate)
            key = (candidate.lane, candidate.new.qualname)
            counts[key] = counts.get(key, 0) + 1
        return ordered


def reservation_cost(judge: Judge, candidate: Candidate, settings: Settings) -> float:
    rates = price(judge, settings)
    maximum = getattr(judge, "max_tokens", None)
    if rates is None or maximum is None:
        raise ValueError("Discovery needs a priced judge with a maximum output token limit")
    # Conservative input estimate plus the actual configured output ceiling; actual usage settles the charge.
    text = prompt(candidate, policy=getattr(judge, "prompt_policy", "concept"))
    return ((len(text.encode("utf-8")) + 1024) * rates[0] + maximum * rates[1]) / 1_000_000
