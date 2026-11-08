"""Exact family cache and execution; the caller supplies admission from the SAME native campaign cap."""

import hashlib
import json
import math
from typing import Literal, Protocol

from pydantic import Field, model_validator

from dry_lint.costs import usage_cost
from dry_lint.family_models import (
    FamilyAnswer,
    FamilyFile,
    FamilyRecord,
    FamilyRequest,
    FamilyResponse,
    validate_answer,
)
from dry_lint.plugins import StoreBackend, identity


class FamilyJudge(Protocol):
    name: str
    version: str
    model: str
    max_tokens: int
    available: bool

    def input_text(self, request: FamilyRequest) -> str: ...

    def judge_family(self, request: FamilyRequest) -> FamilyResponse: ...


class FamilyAdmission(Protocol):
    """Root's adapter must reserve/settle the existing CampaignStore after the protected pair pass.

    reserve must commit before returning, preserve attempt identity on failure, and enforce SAME residual
    USD/call limits. This protocol intentionally cannot initialize, advance, or replenish an allowance.
    """

    def reserve(self, request: FamilyRequest, judge: FamilyJudge, usd: float) -> int | Literal["budget"] | None: ...

    def settle(self, reservation: int, usd: float | None, success: bool) -> float: ...


def family_key(request: FamilyRequest, judge: FamilyJudge) -> str:
    payload = [
        request.model_dump(mode="json"),
        identity(judge),
        judge.model,
        judge.max_tokens,
        judge.input_text(request),
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def checked_rates(rates: tuple[float, float]) -> tuple[float, float]:
    if len(rates) != 2 or any(not math.isfinite(rate) or rate < 0 for rate in rates):
        raise ValueError("Family admission requires finite nonnegative input/output prices")
    return rates


def family_reservation_cost(request: FamilyRequest, judge: FamilyJudge, rates: tuple[float, float]) -> float:
    if not isinstance(judge.max_tokens, int) or not 1 <= judge.max_tokens <= 16000:
        raise ValueError("Family admission requires a finite output ceiling")
    text = judge.input_text(request)
    # Same conservative reservation rule as native discovery: UTF8 bytes plus framing, bounded output.
    return usage_cost({"input": len(text.encode()) + 1024, "output": judge.max_tokens}, checked_rates(rates))


def record_family_response(
    request: FamilyRequest,
    judge: FamilyJudge,
    response: FamilyResponse,
    rates: tuple[float, float] | None = None,
) -> FamilyRecord:
    """Provider-free recording seam: strict JSON + exact grounding, no calls, retries or pair/gold promotion."""
    if response.stop_reason != "end_turn":
        raise ValueError(f"Incomplete family response: {response.stop_reason}")
    answer = validate_answer(request, FamilyAnswer.model_validate_json(response.text))
    return FamilyRecord(
        key=family_key(request, judge),
        request_key=request.key,
        judge=judge.name,
        judge_version=judge.version,
        answer=answer,
        response=response,
        actual_usd=usage_cost(response.usage.model_dump(), checked_rates(rates)) if response.usage and rates else None,
    )


class FamilyVerdictStore:
    """Use a dedicated backend namespace (e.g. DirectoryStore(root / 'families')), separate from pair records."""

    def __init__(self, backend: StoreBackend) -> None:
        self.backend = backend

    def lookup(self, request: FamilyRequest, judge: FamilyJudge) -> FamilyRecord | None:
        key = family_key(request, judge)
        data = self.backend.get(key)
        if data is None:
            return None
        try:
            record = FamilyRecord.model_validate_json(data)
            replay = record_family_response(request, judge, record.response)
            if (
                record.key != key
                or record.request_key != request.key
                or record.judge != judge.name
                or record.judge_version != judge.version
                or record.answer != replay.answer
            ):
                return None
            return record
        except ValueError:
            return None

    def remember(self, request: FamilyRequest, judge: FamilyJudge, record: FamilyRecord) -> None:
        replay = record_family_response(request, judge, record.response)
        if (
            record.key != replay.key
            or record.request_key != replay.request_key
            or record.judge != replay.judge
            or record.judge_version != replay.judge_version
            or record.answer != replay.answer
        ):
            raise ValueError("Family record is not bound to this request and response")
        self.backend.put(record.key, record.model_dump_json().encode())


class FamilyFinding(FamilyFile):
    request: FamilyRequest
    record: FamilyRecord | None = None
    status: Literal["answered", "cached", "no_key", "unjudged", "budget", "deferred", "failed"]
    charged_usd: float = Field(default=0, ge=0)
    error: str = ""
    response: FamilyResponse | None = None

    @model_validator(mode="after")
    def bound(self):
        if self.status in {"answered", "cached"}:
            if self.record is None or self.record.request_key != self.request.key:
                raise ValueError("Answered family findings require a source-bound record")
            validate_answer(self.request, self.record.answer)
        elif self.record is not None:
            raise ValueError("Unanswered family findings cannot carry a verdict")
        return self

    @property
    def unresolved(self) -> bool:
        return (
            self.record is None
            or self.record.answer.decision == "unknown"
            or any(member.status == "unknown" for member in self.record.answer.members)
        )

    @property
    def reported(self) -> bool:
        return self.record is not None and self.record.answer.decision == "consolidate"


class FamilyJudging:
    def __init__(
        self,
        judge: FamilyJudge,
        store: FamilyVerdictStore,
        admission: FamilyAdmission,
        rates: tuple[float, float],
    ) -> None:
        self.judge, self.store, self.admission, self.rates = judge, store, admission, checked_rates(rates)

    def finding(self, request: FamilyRequest) -> FamilyFinding:
        if not self.judge.available:
            return FamilyFinding(request=request, status="no_key")
        try:
            cached = self.store.lookup(request, self.judge)
        except Exception as error:
            # A cache outage cannot authorize a paid duplicate question or erase the protected report.
            return FamilyFinding(request=request, status="failed", error=type(error).__name__)
        if cached is not None:
            return FamilyFinding(request=request, status="cached", record=cached)
        reserved = family_reservation_cost(request, self.judge, self.rates)
        reservation = self.admission.reserve(request, self.judge, reserved)
        if reservation is None or reservation == "budget":
            return FamilyFinding(request=request, status="budget" if reservation == "budget" else "deferred")
        response = None
        actual = None
        try:
            response = self.judge.judge_family(request)
            if response.usage is not None:
                actual = usage_cost(response.usage.model_dump(), self.rates)
            record = record_family_response(request, self.judge, response, self.rates)
            self.store.remember(request, self.judge, record)
        except Exception as error:
            charged = self.admission.settle(reservation, actual, False)
            # Exceptions can contain credentials/request headers. Persist only the type, plus safe raw response.
            return FamilyFinding(
                request=request, status="failed", charged_usd=charged, error=type(error).__name__, response=response
            )
        charged = self.admission.settle(reservation, actual, True)
        return FamilyFinding(request=request, status="answered", record=record, charged_usd=charged)
