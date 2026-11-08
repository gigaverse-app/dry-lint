# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, F403, F405, I001
"""Frozen-model, settlement-aware residual scheduler using the inherited replay engine."""

from policy_common import *
import argparse, collections, time, resource
import numpy as np
from complete_subset import rc, old_policy, recording_state
from bank_loader import BankLoader
from dry_lint.models import Candidate, Run
from dry_lint.settings import Settings
from transport_controls_v3 import canonical


class KnownFailureJudge(rc.RecordedJudge):
    def judge(self, candidates, settings):
        try:
            return super().judge(candidates, settings)
        except rc.MissingAnswer as exc:
            if str(exc).startswith("known_paid_failure:"):
                # The inherited lookup has already accounted exact recorded usage.
                # Let pinned Judging handle a failed response and continue exploration.
                raise ValueError(str(exc)) from exc
            raise


class ResidualStore(old_policy.AllocationStore):
    def order(self, candidates):
        bykey = {c.key: c for c in candidates}
        meta = self.signals
        pending = dict(bykey)
        covered = collections.Counter()
        seen = set()
        self.selection_trace = []
        self.stop_reason = None

        def expose(c, phase):
            info = meta["rows"][c.key]
            self.selection_trace.append(
                dict(
                    key=c.key,
                    phase=phase,
                    settled_or_held_before_usd=self.snapshot().usd,
                    conservative_hold=info["hold"],
                    utility=info["utility"],
                )
            )
            return c

        def remember(c):
            if any(e["key"] == c.key and e["admitted"] for e in self.events):
                covered.update(meta["rows"][c.key]["shared_calls"])
                seen.add(meta["rows"][c.key]["target_sha"])

        prefix = [] if self.arm == "raw_20call_config_control" else meta["prefix"]
        for key in prefix:
            c = pending.pop(key)
            yield expose(c, "preserved_raw_prefix")
            remember(c)
        while pending:
            state = self.snapshot()
            call_limit = min(
                self.settings.discovery.calls,
                self.settings.discovery.calls_per_revision,
                self.settings.discovery.exploration_calls_per_revision,
                self.settings.max_judgements or len(bykey),
            )
            if len(state.attempts) >= call_limit:
                self.stop_reason = (
                    "explicit_20call_control"
                    if self.arm == "raw_20call_config_control"
                    else "eligible_pool_safety_bound"
                )
                return
            room = min(0.04 - state.usd, state.credit)
            fit = [c for c in pending.values() if meta["rows"][c.key]["hold"] <= room + 1e-12]
            if not fit:
                self.stop_reason = "no_conservative_hold_fits_residual_native_dollars"
                return
            if self.arm == "raw_prefix_then_learned":
                scored = []
                for c in fit:
                    f = meta["rows"][c.key]
                    if f["utility"] < 0.15:
                        continue
                    novelty = 1 / (1 + sum(covered[s] for s in f["shared_calls"]) / max(1, len(f["shared_calls"])))
                    if f["target_sha"] in seen:
                        novelty *= 0.1
                    value = f["utility"] * novelty / (f["hold"] + 0.0005 * f["source_lines"] / 60)
                    scored.append((value, -f["tfidf_rank"], f["target_source"], c.key))
                if not scored:
                    self.stop_reason = "frozen_utility_cutoff"
                    return
                c = pending[max(scored)[-1]]
            else:
                c = min(fit, key=lambda c: (meta["rows"][c.key]["tfidf_rank"], meta["rows"][c.key]["target_source"]))
            pending.pop(c.key)
            yield expose(c, "residual")
            remember(c)
        self.stop_reason = "full_eligible_pool_exhausted"

    def snapshot(self):
        result = super().snapshot()
        # Expose diagnostics to the wrapper without replacing native reserve/settle.
        ACTIVE_STORES[self.arm] = self
        return result


ACTIVE_STORES = {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dynamic-residual-v1")
    ap.add_argument("--intake", action="append", required=True)
    ap.add_argument("--observations", action="append", default=[])
    a = ap.parse_args()
    out = (H / a.out).resolve()
    assert out.is_relative_to(H.resolve()) and not out.exists()
    out.mkdir()
    start = time.perf_counter()
    cpu = time.process_time()
    paths = []
    intake_receipts = []
    for intake in a.intake:
        path = pathlib.Path(intake)
        for feed in jl(path / "method-feedback.jsonl"):
            for ob in feed["observations"]:
                if ob["kind"] == "claude" and ob.get("provenance"):
                    proof = ob["provenance"]
                    assert sha(proof["path"]) == proof["sha256"]
                    paths.append(pathlib.Path(proof["path"]))
        intake_receipts.append({"path": str(path), "feedback_sha256": sha(path / "method-feedback.jsonl")})
    for extra in a.observations:
        path = pathlib.Path(extra)
        paths.extend(path.glob("*.json") if path.is_dir() else [path])
    cache = rc.recordings(paths, include_default=False)
    rc.RecordedJudge = KnownFailureJudge
    rc.AllocationStore = ResidualStore
    old_results = {(r["cohort_id"], r["query"], r["arm"]): r for r in jl(H / "completion-v3/results.jsonl")}
    old_plans = {(r["cohort_id"], r["query"], r["arm"]): r for r in jl(H / "completion-v3/plans.jsonl")}
    subset = json.loads((H / "COMPLETION-SUBSET.json").read_text())["campaigns"]
    results = []
    plans = []
    frontier = []
    bindings = []
    paid_unknowns = []
    loaders = {}
    arrays = {}
    banks = {}
    for campaign in subset:
        cid, q = campaign["cohort_id"], campaign["query"]
        if cid not in loaders:
            loader = BankLoader(cid)
            original = loader.detector.hashed
            memo = {}

            def memo_hash(f, original=original, memo=memo):
                if id(f) not in memo:
                    memo[id(f)] = original(f)
                return memo[id(f)]

            loader.detector.hashed = memo_hash
            loaders[cid] = loader
            arrays[cid] = (
                dict(np.load(H / "arrays" / cid / "data.npz")),
                jl(H / "arrays" / cid / "rows.jsonl"),
                np.load(H / "arrays" / cid / "scores.npy").mean(axis=1),
            )
            banks[cid] = {r["candidate_id"]: r for r in jl(D / "bank" / cid / "candidates.jsonl")}
        loader = loaders[cid]
        panel = loader.panel
        data, rows, pred = arrays[cid]
        ids = np.flatnonzero((data["query"] == q) & data["eligible"])
        original_plan = old_plans[cid, q, "raw_native"]
        prefix = [Candidate.model_validate(c) for c in original_plan["candidates"]]
        bykey = {c.key: c for c in prefix}
        info = {}
        for i in ids:
            row = rows[i]
            c = loader.candidate(banks[cid][row["candidate_id"]])
            assert not c.filtered
            bykey.setdefault(c.key, c)
            info[c.key] = dict(
                hold=float(data["hold"][i]),
                normal_cost=float(data["cost"][i]),
                utility=float(pred[i]),
                shared_calls=row["shared_calls"],
                source_lines=row["source_lines"],
                target_sha=row["target_sha"],
                tfidf_rank=row["tfidf_rank"],
                target_source=row["target_source"],
            )
        cs = list(bykey.values())
        assert set(bykey) == set(info)
        for c in cs:
            s = Settings.model_validate(original_plan["settings"])
            assert abs(rc.reservation_cost(rc.JUDGE, c, s) - info[c.key]["hold"]) < 1e-12
        for arm in ["raw_prefix_then_learned", "raw_prefix_then_deeper_raw", "raw_20call_config_control"]:
            s = Settings.model_validate(original_plan["settings"])
            limit = 20 if arm == "raw_20call_config_control" else len(cs)
            s.discovery.calls = limit
            s.discovery.calls_per_revision = limit
            s.discovery.exploration_calls_per_revision = limit
            s.discovery.baseline_fraction = 0
            s.discovery.exploration_per_revision = 0.04
            s.max_judgements = None
            folder = out / cid / str(q) / arm
            folder.mkdir(parents=True)
            run = Run(
                repository=panel["repository"], revision=panel["revision"], session=f"learned-residual:{cid}:{q}:{arm}"
            )
            native = rc.native_replay(
                cs, {"prefix": [c.key for c in prefix], "rows": info}, s, run, folder, arm, panel, cache
            )
            store = ACTIVE_STORES[arm]
            attempted = [e for e in native["events"] if e["admitted"]]
            if arm != "raw_20call_config_control":
                assert [e["key"] for e in attempted[: len(prefix)]] == [c.key for c in prefix]
                assert set(old_results[cid, q, "raw_native"]["reports"]) <= set(native["reports"])
            unknown = []
            for entry in native["recordings"]:
                c = bykey[entry["key"]]
                rec = entry["recording"]
                qid = "ENC-" + canonical(c)[:20]
                if rec:
                    raw = json.loads(pathlib.Path(rec["path"]).read_text())
                    eq = raw.get("question_equivalence")
                    if eq:
                        assert not eq["fresh_provider_observation"] and eq["new_physical_usd"] == 0
                        assert sha(eq["original_observation"]) == eq["original_observation_sha256"]
                    binding = dict(
                        id=qid,
                        cohort_id=cid,
                        query=q,
                        arm=arm,
                        request_key=rc.canonical(rec["identity"]),
                        recording={"path": rec["path"], "sha256": rec["sha256"]},
                        source_physical_request_key=eq["source_physical_request_key"]
                        if eq
                        else rc.canonical(rec["identity"]),
                        question_equivalence=eq,
                        physical_usd=rec["usd"],
                        state=recording_state(rec),
                    )
                    bindings.append(binding)
                    if recording_state(rec) == "paid_unknown":
                        paid_unknowns.append(binding | {"retry_eligible": False, "truth_label": None})
                        unknown.append(qid)
            if native["censored"]:
                assert not native["censored"].startswith("known_paid_failure:")
                event = next(e for e in reversed(native["events"]) if e["admitted"] and e["settled_actual_usd"] is None)
                c = bykey[event["key"]]
                frontier.append(
                    dict(
                        id="ENC-" + canonical(c)[:20],
                        cohort_id=cid,
                        query=q,
                        arm=arm,
                        candidate=c.model_dump(mode="json"),
                        event=event,
                        database=event["preexecution_database"],
                        run=native["run"],
                        settings=native["settings"],
                        native=native,
                    )
                )
            trace = dict(
                stop_reason=store.stop_reason or "first_unpaid_missing_answer",
                selections=store.selection_trace,
                prefix_candidates=len(prefix),
                full_pool=len(cs),
            )
            write(folder / "scheduler.json", trace)
            result = dict(
                cohort_id=cid,
                query=q,
                arm=arm,
                repository=panel["repository"],
                revision=panel["revision"],
                native=native,
                complete=native["censored"] is None and not unknown,
                allocation_finished=native["censored"] is None,
                paid_unknown_ids=unknown,
                reports=native["reports"],
                normal_estimated_admitted_usd=sum(info[e["key"]]["normal_cost"] for e in attempted),
                source_lines=sum(info[e["key"]]["source_lines"] for e in attempted),
                scheduler=trace,
                original_raw_reports_retained=arm != "raw_20call_config_control",
            )
            results.append(result)
            plans.append(
                dict(
                    cohort_id=cid,
                    query=q,
                    arm=arm,
                    settings=s.model_dump(mode="json"),
                    candidates=[c.model_dump(mode="json") for c in cs],
                )
            )
            print(
                cid,
                q,
                arm,
                "admitted",
                len(attempted),
                "reports",
                len(native["reports"]),
                "settled",
                native["actual_settled_usd"],
                "stop",
                trace["stop_reason"],
                flush=True,
            )
    write(out / "results.jsonl", results)
    write(out / "plans.jsonl", plans)
    write(out / "native-frontier.jsonl", frontier)
    write(out / "exact-bindings.jsonl", bindings)
    write(out / "paid-unknowns.jsonl", paid_unknowns)
    write(
        out / "RESULTS.json",
        dict(
            schema=1,
            arms=len(results),
            complete_arms=sum(r["complete"] for r in results),
            allocation_finished_arms=sum(r["allocation_finished"] for r in results),
            native_frontier_occurrences=len(frontier),
            core_frontier_unique=len({r["id"] for r in frontier if r["arm"] != "raw_20call_config_control"}),
            paid_unknown_occurrences=len(paid_unknowns),
            provider_calls=0,
            encoder_calls=0,
            seconds=time.perf_counter() - start,
            cpu_seconds=time.process_time() - cpu,
            peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            intakes=intake_receipts,
            contract_sha256=sha(H / "DYNAMIC-RESIDUAL-CONTRACT.json"),
            family_review="root-owned; labels not read",
            normal_accounting="Original completion-v3 normal arms unchanged. New experiment is native settlement-aware; normal-estimated admitted cost is a separate metric.",
        ),
    )


if __name__ == "__main__":
    main()
