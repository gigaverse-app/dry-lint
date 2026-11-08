# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E402, F401, F841, I001
"""Offline bounded allocation. No provider construction or credential access."""

from _recovery_paths import recovery_path
import os
import sys
from pathlib import Path

for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "2"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True
ROOT = Path(recovery_path(""))
BASE = ROOT / "jobs/encoder-corpus-evaluation/.lab-results"
sys.path.insert(0, str(BASE))
from native_harness import (
    Candidate,
    CampaignStore,
    JUDGE,
    REF,
    Run,
    Settings,
    estimate,
    reservation_cost,
    digest,
    sha,
    jl,
    write,
)
from collections import Counter
import json

HERE = Path(__file__).resolve().parent


def canonical(value):
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=True))


def features(candidates, extra=None):
    """Rank/margin utility, never a calibrated probability or judge answer."""
    extra = extra or {}
    groups = {}
    for c in candidates:
        if c.lane != "relative":
            groups.setdefault(c.new.qualname, []).append(c)
    result = {}
    for cs in groups.values():
        cs = sorted(cs, key=lambda c: (-c.similarity, c.key))
        for rank, c in enumerate(cs, 1):
            following = cs[rank].similarity if rank < len(cs) else c.similarity
            # Historical captures have only their original lexical rank channel.
            r = extra.get(c.key, {})
            sparse_rank = r.get("tfidf_rank", rank)
            dense_rank = r.get("minilm_rank")
            utility = 61 / (60 + sparse_rank)
            if dense_rank is not None:
                utility = (utility + 61 / (60 + dense_rank)) / 2
            agreement = dense_rank is not None and sparse_rank <= 50 and dense_rank <= 10
            # Never subtract a block/RRF score from a cosine from another channel.
            margin = max(0.0, r.get("margin", 0.0))
            result[c.key] = dict(
                r,
                utility=utility * (1 + int(agreement) + margin),
                margin=margin,
                agreement=agreement,
                nonblank_lines=min(sum(bool(x.strip()) for x in f.code.splitlines()) for f in (c.new, c.existing)),
                family_proxy=c.existing.hash or digest(c.existing.code),
            )
    return result


def ordered(candidates, arm, signal, settings, state):
    """Keep production baseline order, then query-fair cost/diversity allocation.

    Static proposed order uses the same attempted-query round-robin as production.
    Family proxy is exact extractor structure hash, not accepted label families.
    """
    pending = list(candidates)
    counts = Counter((a.lane, a.query) for a in state.attempts)
    families = Counter()
    result = []
    costs = {c.key: estimate(JUDGE, [c], settings) for c in pending}
    while pending:

        def score(c):
            if c.lane == "baseline" or arm == "fixed":
                return (c.lane != "baseline", -c.priority, counts[c.lane, c.new.qualname], -c.similarity, c.key)
            f = signal[c.key]
            value = f["utility"] / costs[c.key] / (1 + families[f["family_proxy"]])
            return (True, -c.priority, counts[c.lane, c.new.qualname], -value if arm == "adaptive" else 0, c.key)

        c = min(pending, key=score)
        pending.remove(c)
        result.append(c)
        counts[c.lane, c.new.qualname] += 1
        families[signal[c.key]["family_proxy"]] += 1
    return result


class AllocationStore(CampaignStore):
    def __init__(self, path, run, arm, signals, settings, accounting):
        super().__init__(path, run)
        self.arm, self.signals, self.settings, self.accounting = arm, signals, settings, accounting
        self.events, self.estimates = [], {}

    def order(self, candidates):
        return ordered(candidates, self.arm, self.signals, self.settings, self.snapshot())

    def reserve(self, candidate, judge, settings, usd):
        before = self.snapshot()
        normal = estimate(judge, [candidate], settings)
        requested = normal if self.accounting == "normal_estimated" else usd
        token = super().reserve(candidate, judge, settings, requested)
        reason = None
        current = [a for a in before.attempts if a.revision == self.revision]
        if type(token) is not int:
            if token == "budget":
                reason = (
                    "exploration_credit_or_fraction"
                    if candidate.lane == "exploration" and requested <= settings.budget.usd - before.usd + 1e-12
                    else "total_dollars"
                )
            elif len(current) >= min(
                settings.discovery.calls_per_revision, settings.max_judgements or settings.discovery.calls_per_revision
            ):
                reason = "per_revision_call_limit"
            elif len(before.attempts) >= settings.discovery.calls:
                reason = "campaign_call_limit"
            elif (
                candidate.lane == "exploration"
                and sum(a.lane == "exploration" for a in current) >= settings.discovery.exploration_calls_per_revision
            ):
                reason = "exploration_per_revision_call_limit"
            else:
                reason = "duplicate_evidence_or_campaign_exploration_calls"
        event = dict(
            key=candidate.key,
            admitted=type(token) is int,
            attempt_index=token if type(token) is int else None,
            reason=reason,
            lane=candidate.lane,
            query=candidate.new.qualname,
            conservative_reservation_usd=usd,
            normal_estimate_usd=normal,
            requested_usd=requested,
            before_usd=before.usd,
            credit_before=before.credit,
            candidate_sha256=canonical(candidate.model_dump(mode="json")),
            settled_actual_usd=None,
            accounting=self.accounting,
        )
        self.events.append(event)
        if type(token) is int:
            self.estimates[token] = normal
            if self.accounting == "native_settled":
                # Preserve the committed pre-call hold for the coordinator intake.
                # MissingAnswer later marks the live replay attempt failed in finally.
                import sqlite3

                held = self.path.with_name(f"held-{token}.sqlite")
                with (
                    sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True) as src,
                    sqlite3.connect(held) as dst,
                ):
                    src.backup(dst)
                event["preexecution_database"] = str(held)
                event["preexecution_database_sha256"] = sha(held)
        return token

    def settle(self, reservation, usd, success):
        event = next(e for e in reversed(self.events) if e["attempt_index"] == reservation)
        event.update(settled_actual_usd=usd, success=success)
        # Normal estimated logical charges do not become cheaper on an exact recording hit.
        return super().settle(
            reservation, self.estimates[reservation] if self.accounting == "normal_estimated" else usd, success
        )


def allocation(candidates, signals, settings, run, out, arm, accounting):
    """Answer-independent allocation diagnostic, explicitly not a completed campaign."""
    store = AllocationStore(out / "campaign.sqlite", run, arm, signals, settings, accounting)
    store.advance(settings)
    eligible = [
        c for c in candidates if not c.filtered and c.lane != "relative" and min(c.new.line, c.existing.line) > 0
    ]
    baseline_pending = False
    for c in store.order(eligible):
        if baseline_pending and c.lane == "exploration":
            store.events.append(
                dict(key=c.key, admitted=False, reason="baseline_pending", lane=c.lane, query=c.new.qualname)
            )
            continue
        token = store.reserve(c, JUDGE, settings, reservation_cost(JUDGE, c, settings))
        if c.lane == "baseline" and type(token) is not int:
            baseline_pending = True
    assert store.snapshot().usd <= 0.04 + 1e-12
    result = dict(
        events=store.events,
        state=store.snapshot().model_dump(mode="json"),
        database=str(store.path),
        run=run.model_dump(mode="json"),
        settings=settings.model_dump(mode="json"),
        accounting=accounting,
        answers="unknown; allocation diagnostic only",
    )
    write(out / "allocation.json", result)
    return result
