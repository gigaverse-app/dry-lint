# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, F401, I001
"""Final frozen hybrid arm; exact replay plumbing, no provider execution."""

from replay_frontier import R, H, ROOT, TARGETS
from dry_lint.report import Finding
from dry_lint.discovery import CampaignStore
import json, pathlib, argparse, time, resource


def source_key(c):
    return R.canonical({"new": c.new.model_dump(mode="json"), "existing": c.existing.model_dump(mode="json")})


_original_ordered = R.ordered
_original_store = R.AllocationStore


def frozen_ordered(candidates, arm, signals, settings, state):
    return list(candidates) if arm == "hybrid" else _original_ordered(candidates, arm, signals, settings, state)


class HybridSequenceStore(_original_store):
    def order(self, candidates):
        return list(candidates) if self.arm == "hybrid" else super().order(candidates)


R.ordered = frozen_ordered
R.AllocationStore = HybridSequenceStore


def eligible(cs):
    return [c for c in cs if not c.filtered and c.lane != "relative" and min(c.new.line, c.existing.line) > 0]


def report(cs, recordings, s, run, path):
    seen = {}
    findings = []
    for c in cs:
        if c.key in seen:
            continue
        seen[c.key] = True
        row = recordings.get(c.key)
        v = R.Verdict.model_validate(row["verdict"]) if row and row.get("verdict") and not row.get("error") else None
        findings.append(Finding(candidate=c, verdict=v))
    result = R.Report.build(findings, s, run=run, changed=1, judge=R.JUDGE.name)
    R.write(path, result.model_dump(mode="json"))
    return [f.candidate.key for f in result.findings if f.reported]


def enriched_events(native, s, phase):
    rows = []
    prior_count = len(native["state"]["attempts"]) - sum(e["admitted"] for e in native["events"])
    for e in native["events"]:
        before = native["state"]["attempts"][:prior_count]
        constraints = {
            "total_dollars_remaining": s.budget.usd - e["before_usd"],
            "exploration_credit_remaining": e["credit_before"],
            "original_exploration_per_revision": s.discovery.exploration_per_revision,
            "exploration_fraction_cap": s.budget.usd * (1 - s.discovery.baseline_fraction),
            "requested_conservative_hold": e["requested_usd"],
            "calls_per_revision": s.discovery.calls_per_revision,
            "exploration_calls_per_revision": s.discovery.exploration_calls_per_revision,
            "campaign_calls": s.discovery.calls,
            "attempts_before": len(before),
            "exploration_attempts_before": sum(x["lane"] == "exploration" for x in before),
            "exploration_fraction_remaining": s.budget.usd * (1 - s.discovery.baseline_fraction)
            - sum(x["usd"] for x in before if x["lane"] == "exploration"),
        }
        reason = e["reason"]
        if reason == "exploration_credit_or_fraction":
            reason = "exploration_credit" if e["requested_usd"] > e["credit_before"] + 1e-12 else "exploration_fraction"
        rows.append(e | {"phase": phase, "specific_stop": reason, "constraints": constraints})
        prior_count += int(e["admitted"])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--cap", type=float, choices=[0.005, 0.01, 0.02, 0.04], required=True)
    ap.add_argument("--all-nominations", action="store_true")
    ap.add_argument("--observations", type=pathlib.Path, action="append", default=[])
    ap.add_argument("--recordings-snapshot", type=pathlib.Path, required=True)
    a = ap.parse_args()
    out = H / a.out
    out.mkdir(exist_ok=False)
    plans = R.jl(H / "hybrid-frozen-v1/plans.jsonl")
    plan_by = {p["id"]: p for p in plans}
    targets = [p["id"] for p in plans]
    start = time.monotonic()
    cpu = time.process_time()
    frozen = json.loads(a.recordings_snapshot.read_text())["observations"]
    assert all(R.sha(x["path"]) == x["sha256"] for x in frozen)
    cache = R.recordings([pathlib.Path(x["path"]) for x in frozen], include_default=False)
    snap = []
    for rs in cache.values():
        for p, r in rs:
            snap.append(
                {
                    "path": str(p),
                    "sha256": R.sha(p),
                    "request_key": r["request_key"],
                    "question_equivalence": r.get("question_equivalence"),
                    "source_physical_request_key": r.get("question_equivalence", {}).get(
                        "source_physical_request_key", r["request_key"]
                    ),
                }
            )
    R.write(out / "OBSERVATIONS.json", {"observations": snap})
    R.write(out / "CONTRACT.json", json.loads((H / "hybrid-frozen-v1/CONTRACT.json").read_text()))
    results = []
    front = []
    review = []
    for target in targets:
        original = H / "batch-v1/native" / target / "campaigns.jsonl"
        camp = R.jl(original)[0]
        cid = camp["cohort_id"]
        q = camp["query_positions"][0]
        p = json.loads(
            (ROOT / "jobs/complementary-signal-learning/.lab-results/bank" / cid / "RECEIPT.json").read_text()
        )["source"]
        raw = [R.Candidate.model_validate(c) for c in camp["arms"]["raw_tfidf"]]
        base_s = R.Settings.model_validate(camp["native"]["raw_tfidf"]["settings"])
        base_s = base_s.model_copy(update={"budget": base_s.budget.model_copy(update={"usd": a.cap})})
        for arm in ["hybrid"]:
            folder = out / target / arm
            run = R.Run.model_validate(camp["native"]["raw_tfidf"]["run"])
            assert R.sha(original) == plan_by[target]["source_campaign_sha256"]
            assert camp["arms"]["raw_tfidf"] == plan_by[target]["raw_prefix"]
            cs = [R.Candidate.model_validate(c) for c in plan_by[target]["hybrid_suffix"]]
            normal1 = R.normal(raw, R.features(raw), base_s, run, folder / "prefix", "fixed", p, cache)
            native1 = R.native_replay(raw, R.features(raw), base_s, run, folder / "native", "fixed", p, cache)
            selected = {e["key"] for e in normal1["events"] if e["admitted"]}
            selected_sources = {source_key(c) for c in raw if c.key in selected}
            ncs = [c for c in eligible(cs) if source_key(c) not in selected_sources]
            remaining = max(0.0, a.cap - normal1["estimated_usd"])
            ns = base_s.model_copy(update={"budget": base_s.budget.model_copy(update={"usd": remaining})})
            normal2 = R.normal(ncs, R.features(ncs), ns, run, folder / "normal-residual", "hybrid", p, cache)
            normal_events = [e | {"phase": "protected_raw"} for e in normal1["events"] if e["admitted"]] + [
                e | {"phase": "residual", "cumulative_usd": e["cumulative_usd"] + normal1["estimated_usd"]}
                for e in normal2["events"]
            ]
            normal_cost = normal1["estimated_usd"] + normal2["estimated_usd"]
            assert normal_cost <= a.cap + 1e-12
            normal_obs = {e["key"]: e["recording"] for e in normal_events if e["admitted"]}
            allcs = raw + [c for c in cs if c.key not in {x.key for x in raw}]
            normal_candidates = {c.key: c for c in allcs}
            normal_candidates.update(
                {c.key: c for c in ncs if c.key in {e["key"] for e in normal2["events"] if e["admitted"]}}
            )
            normal_reports = report(
                list(normal_candidates.values()), normal_obs, base_s, run, folder / "normal-report.json"
            )
            normal_unknown = sum(
                e["admitted"]
                and (not e["recording"] or bool(e["recording"].get("error")) or not e["recording"].get("verdict"))
                for e in normal_events
            )
            if native1["censored"] is not None:
                # Unknown protected prefix blocks the residual phase; never fabricate suffix admission.
                record = {
                    "id": target,
                    "cohort_id": cid,
                    "query": q,
                    "arm": arm,
                    "repository": p["repository"],
                    "revision": p["revision"],
                    "original_campaign": str(original),
                    "original_campaign_sha256": R.sha(original),
                    "candidates_unchanged": True,
                    "matched_cap_usd": a.cap,
                    "analysis_scope": "final hybrid .04 arm; original recipes retained"
                    if a.cap == 0.04
                    else "explicit posthoc cost efficiency; not original acceptance or provider funding",
                    "normal": {
                        "complete": normal_unknown == 0,
                        "unknown_funded": normal_unknown,
                        "estimated_usd": normal_cost,
                        "events": normal_events,
                        "reported_keys": normal_reports,
                        "report": str(folder / "normal-report.json"),
                        "protected_prefix": normal1,
                        "residual": normal2,
                    },
                    "native": {
                        "complete": False,
                        "censored": native1["censored"],
                        "state": native1["state"],
                        "reported_keys": native1["reports"],
                        "report": str(folder / "native/report.json"),
                        "protected_prefix": native1,
                        "residual": None,
                        "transition": {"status": "blocked_by_actual_prefix_unknown", "credit_not_released": True},
                    },
                }
                results.append(record)
                key = native1["censored"]
                c = next((c for c in raw if c.key == key), None)
                if c is not None:
                    event = next(e for e in native1["events"] if e["key"] == key and e["admitted"])
                    front.append(
                        {
                            "id": target,
                            "arm": arm,
                            "repository": p["repository"],
                            "revision": p["revision"],
                            "candidate": c.model_dump(mode="json"),
                            "settings": base_s.model_dump(mode="json"),
                            "run": run.model_dump(mode="json"),
                            "event": event,
                            "original_native_scope": "actual protected raw prefix; residual phase unopened",
                            "normal_funded": any(e["key"] == key and e["admitted"] for e in normal_events),
                            "source": p,
                        }
                    )
                R.write(
                    folder / "first-stop-trace.json",
                    {
                        "events": enriched_events(native1, base_s, "protected_raw"),
                        "residual_status": "unopened: exact prefix observation missing",
                    },
                )
                R.write(out / "results.jsonl", results)
                R.write(
                    out / ("unanswered-hybrid-native.jsonl" if a.cap == 0.04 else "unanswered-curve-questions.jsonl"),
                    front,
                )
                print(target, arm, "normal", len(normal_reports), "native prefix missing", key, flush=True)
                continue
            attempted = {e["key"] for e in native1["events"] if e["admitted"]}
            attempted_sources = {source_key(c) for c in raw if c.key in attempted}
            suffix = [c for c in eligible(cs) if source_key(c) not in attempted_sources]
            residual_s = base_s.model_copy(
                update={
                    "discovery": base_s.discovery.model_copy(
                        update={"baseline_fraction": 0.0, "exploration_per_revision": a.cap}
                    )
                }
            )
            campaign = CampaignStore(folder / "native/campaign.sqlite", run)
            before = campaign.snapshot()
            with campaign.transaction() as state:
                state.credit = max(0.0, a.cap - state.usd)
            transition = {
                "protected_prefix_usd": before.usd,
                "prefix_credit": before.credit,
                "residual_credit": campaign.snapshot().credit,
                "same_database": str(campaign.path),
                "prefix_attempts": len(before.attempts),
                "cap_usd": a.cap,
                "remaining_calls_per_revision": base_s.discovery.calls_per_revision - len(before.attempts),
                "remaining_exploration_calls": base_s.discovery.exploration_calls_per_revision
                - sum(x.lane == "exploration" for x in before.attempts),
                "no_prior_charge_reset": True,
            }
            R.write(folder / "protected-native.json", native1)
            R.write(folder / "protected-native-report.json", json.loads((folder / "native/report.json").read_text()))
            # Second call continues existing SQLite and exact-source VerdictStore. Only new candidates supplied.
            native2 = R.native_replay(
                suffix, R.features(suffix), residual_s, run, folder / "native", "hybrid", p, cache
            )
            native_obs = {e["key"]: e["recording"] for n in [native1, native2] for e in n["recordings"]}
            native_candidates = {c.key: c for c in allcs}
            native_candidates.update({c.key: c for c in suffix if c.key in {e["key"] for e in native2["recordings"]}})
            native_reports = report(
                list(native_candidates.values()), native_obs, base_s, run, folder / "native-report.json"
            )
            assert native2["state"]["prior_usd"] + sum(x["usd"] for x in native2["state"]["attempts"]) <= a.cap + 1e-12
            assert set(native1["reports"]) <= set(native_reports)
            traces = enriched_events(native1, base_s, "protected_raw") + enriched_events(
                native2, residual_s, "residual"
            )
            R.write(
                folder / "first-stop-trace.json",
                {
                    "events": traces,
                    "first_denied_each_phase": {
                        phase: next((e for e in traces if e["phase"] == phase and not e["admitted"]), None)
                        for phase in ["protected_raw", "residual"]
                    },
                    "baseline_preallocation": {
                        "prefix_deferred_without_reserve_keys": [
                            c.key for c in eligible(raw) if c.key not in {e["key"] for e in native1["events"]}
                        ],
                        "suffix_deferred_without_reserve_keys": [
                            c.key for c in suffix if c.key not in {e["key"] for e in native2["events"]}
                        ],
                    },
                },
            )
            record = {
                "id": target,
                "cohort_id": cid,
                "query": q,
                "arm": arm,
                "repository": p["repository"],
                "revision": p["revision"],
                "original_campaign": str(original),
                "original_campaign_sha256": R.sha(original),
                "candidates_unchanged": True,
                "matched_cap_usd": a.cap,
                "analysis_scope": "final hybrid .04 arm; original recipes retained"
                if a.cap == 0.04
                else "explicit posthoc cost efficiency; not original acceptance or provider funding",
                "normal": {
                    "complete": normal_unknown == 0,
                    "unknown_funded": normal_unknown,
                    "estimated_usd": normal_cost,
                    "events": normal_events,
                    "reported_keys": normal_reports,
                    "report": str(folder / "normal-report.json"),
                    "protected_prefix": normal1,
                    "residual": normal2,
                },
                "native": {
                    "complete": native2["censored"] is None,
                    "censored": native2["censored"],
                    "state": native2["state"],
                    "reported_keys": native_reports,
                    "report": str(folder / "native-report.json"),
                    "protected_prefix": native1,
                    "residual": native2,
                    "transition": transition,
                    "first_stop_trace": str(folder / "first-stop-trace.json"),
                },
            }
            results.append(record)
            if native2["censored"]:
                key = native2["censored"]
                c = next((c for c in suffix if c.key == key), None)
                if c is not None:
                    event = next(e for e in native2["events"] if e["key"] == key and e["admitted"])
                    front.append(
                        {
                            "id": target,
                            "arm": arm,
                            "repository": p["repository"],
                            "revision": p["revision"],
                            "candidate": c.model_dump(mode="json"),
                            "settings": residual_s.model_dump(mode="json"),
                            "run": run.model_dump(mode="json"),
                            "event": event,
                            "original_native_scope": "revised residual policy, not original failed recipe",
                            "normal_funded": any(e["key"] == key and e["admitted"] for e in normal_events),
                            "source": p,
                        }
                    )
            for regime, keys in [("normal", normal_reports), ("native", native_reports)]:
                for key in keys:
                    c = (normal_candidates if regime == "normal" else native_candidates)[key]
                    review.append(
                        {
                            "id": target,
                            "arm": arm,
                            "regime": regime,
                            "candidate": c.model_dump(mode="json"),
                            "key": key,
                            "repository": p["repository"],
                            "revision": p["revision"],
                            "report": record[regime]["report"],
                            "family_id": None,
                            "confirmed_independent_owner_ids": None,
                            "source_review_authority": "root",
                            "claim": "emitted pair only; new family and useful owner expansion require independent reconciliation",
                        }
                    )
            R.write(out / "results.jsonl", results)
            R.write(
                out / ("unanswered-hybrid-native.jsonl" if a.cap == 0.04 else "unanswered-curve-questions.jsonl"), front
            )
            R.write(out / "emitted-family-owner-review.jsonl", review)
            print(
                target,
                arm,
                "normal",
                len(normal_reports),
                "native",
                len(native_reports),
                "missing",
                native2["censored"],
                flush=True,
            )
    R.write(
        out / "SUMMARY.json",
        {
            "analysis_scope": "final hybrid .04 arm" if a.cap == 0.04 else "explicit posthoc cost efficiency",
            "cap_usd": a.cap,
            "cache_snapshot": {"path": str(a.recordings_snapshot), "sha256": R.sha(a.recordings_snapshot)},
            "curve_questions_must_not_trigger_provider_calls": True,
            "campaigns": len(targets),
            "selection": str(H / "diagnostic-single-question/FROZEN-SELECTION.json"),
            "selection_sha256": R.sha(H / "diagnostic-single-question/FROZEN-SELECTION.json"),
            "arms": len(results),
            "normal_complete": sum(r["normal"]["complete"] for r in results),
            "native_complete": sum(r["native"]["complete"] for r in results),
            "frontier_rows": len(front),
            "baseline_report_pairs_preserved": all(
                set(r["native"]["protected_prefix"]["reports"]) <= set(r["native"]["reported_keys"]) for r in results
            ),
            "provider_calls": 0,
            "implementation_sha256": R.sha(pathlib.Path(__file__)),
            "contract_sha256": R.sha(H / "hybrid-frozen-v1/CONTRACT.json"),
            "cpu_seconds": time.process_time() - cpu,
            "wall_seconds": time.monotonic() - start,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "family_gain": "pending root",
            "confirmed_member_gain": "pending root",
        },
    )


if __name__ == "__main__":
    main()
