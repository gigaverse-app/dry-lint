# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B007, E401, E402, F401, F403, F405, F841, I001
"""Reuse adaptive recorded lookup/normal ledger/native replay on frozen policy orders."""

from policy_common import *
import argparse, collections, importlib.util

ADAPT = ROOT / "jobs/adaptive-judge-budget/.lab-results"
sys.path[:0] = [str(ADAPT), str(R), str(B)]
import replay_captures as rc
import policy as old_policy
from transport_controls_v3 import canonical
from dry_lint.models import Candidate, Run
from dry_lint.settings import Settings
from dry_lint.report import Report, Finding

INTAKE = ROOT / ".lab-results/encoder-judging/intakes/encoder-corpus-evaluation/r1-1e4e1e7230ab7987"


def preserve_order(candidates, arm, signals, settings, state):
    return list(candidates)


def recording_state(recording):
    if recording is None:
        return "unpaid_missing"
    if not recording.get("verdict") or recording.get("error"):
        return "paid_unknown"
    return "observed"


# Reuse the recorder, funding snapshots and production report path; only replace inherited ranking.
rc.ordered = preserve_order
old_policy.ordered = preserve_order


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="completion-v1")
    ap.add_argument("--intake", action="append")
    ap.add_argument("--observations", action="append", default=[])
    a = ap.parse_args()
    out = H / a.out
    assert not out.exists()
    out.mkdir()
    paths = []
    receipts = []
    for intake in a.intake or [str(INTAKE)]:
        p = pathlib.Path(intake)
        for f in jl(p / "method-feedback.jsonl"):
            for ob in f["observations"]:
                if ob["kind"] == "claude" and ob.get("provenance"):
                    pr = ob["provenance"]
                    assert sha(pr["path"]) == pr["sha256"]
                    paths.append(pathlib.Path(pr["path"]))
        receipts.append({"path": str(p), "sha256": sha(p / "method-feedback.jsonl")})
    for extra in a.observations:
        ep = pathlib.Path(extra)
        paths.extend(ep.glob("*.json") if ep.is_dir() else [ep])
    cache = rc.recordings(paths, include_default=False)
    equivalences = []
    for entries in cache.values():
        for path, raw in entries:
            if raw.get("question_equivalence"):
                eq = raw["question_equivalence"]
                assert eq["fresh_provider_observation"] is False and eq["new_physical_usd"] == 0
                assert sha(eq["original_observation"]) == eq["original_observation_sha256"]
                equivalences.append({"path": str(path), "sha256": sha(path), "question_equivalence": eq})
    write(
        out / "QUESTION-EQUIVALENCE.json",
        {
            "contract": str(ROOT / "reports/utility-recovery/QUESTION-EQUIVALENCE-CONTRACT.md"),
            "derived_recordings": equivalences,
            "fresh_provider_observations": 0,
        },
    )
    nominations = jl(H / "funded-questions.jsonl")
    ranks = [27, 101, 607, 40]
    selected = [next(r for r in nominations if r["shortlist_rank"] == rank) for rank in ranks]
    subset = {
        "schema": 1,
        "campaigns": [
            {
                "cohort_id": r["cohort_id"],
                "query": r["query"],
                "repository": r["repository"],
                "revision": r["revision"],
                "operation_question": r["reason"],
                "source_endpoints": [r["query_source"], r["target_source"]],
                "nominated_id": r["canonical_queue_id"],
            }
            for r in selected
        ],
        "selection": "Four source-supported distinct operation questions: timeout normalization, SCIM deactivation, project/draft cleanup, and atom-command failure reporting. Paid report existence determines completion priority only; no source-review labels read. Not chosen by easiest number of missing answers.",
        "core_arms": ["raw_dollar", "raw_native", "guarded", "guarded_native"],
        "cheap_control": "raw_dollar already has no score floor and variable depth up to .04; duplicating lower-floor/deeper arm would be identical.",
        "scope": "Completion subset of original single-query counterfactuals. V1 broad screen preserved. Guarded recipe is unchanged; these are development regressions, not fresh source-group tests. New structural-generator groups remain separate.",
        "family_acceptance": "Pending independent reviewer mapping across ALL emitted raw/guard reports, including third-function coverage and revision aliases. Unknown families cannot count as incremental.",
    }
    write(H / "COMPLETION-SUBSET.json", subset)
    allplans = jl(H / "replay-v1/plans.jsonl")
    results = []
    frontier = []
    missing = {}
    bindings = []
    planrows = []
    mismatches = []
    paid_unknowns = []
    physical = {}
    for row in subset["campaigns"]:
        cid, q = row["cohort_id"], row["query"]
        panel = json.loads((B / "bank" / cid / "RECEIPT.json").read_text())["source"]
        for arm in subset["core_arms"]:
            plan = next(p for p in allplans if p["cohort_id"] == cid and p["query"] == q and p["arm"] == arm)
            cs = [Candidate.model_validate(c) for c in plan["candidates"]]
            s = Settings.model_validate(plan["settings"])
            run = Run(
                repository=panel["repository"],
                revision=panel["revision"],
                session=f"learned-policy-completion:{cid}:{q}:{arm}",
            )
            folder = out / cid / str(q) / arm
            folder.mkdir(parents=True)
            signals = {}
            judge = rc.RecordedJudge(panel, cache, s)
            normal = rc.normal(cs, signals, s, run, folder, arm, panel, cache)
            if "_native" in arm:
                native = rc.native_replay(cs, signals, s, run, folder, arm, panel, cache)
                if native["censored"] and not native["censored"].startswith("known_paid_failure:"):
                    event = next(
                        e for e in reversed(native["events"]) if e["admitted"] and e["settled_actual_usd"] is None
                    )
                    c = next(c for c in cs if c.key == event["key"])
                    frontier.append(
                        {
                            "id": "ENC-" + canonical(c)[:20],
                            "cohort_id": cid,
                            "query": q,
                            "arm": arm,
                            "candidate": c.model_dump(mode="json"),
                            "event": event,
                            "run": native["run"],
                            "settings": native["settings"],
                            "database": event["preexecution_database"],
                            "native": native,
                        }
                    )
                complete = native["censored"] is None
                reported = native["reports"]
            else:
                fs = [
                    Finding(
                        candidate=c,
                        verdict=rc.Verdict.model_validate(e["recording"]["verdict"])
                        if e["recording"] and e["recording"]["verdict"] and not e["recording"]["error"]
                        else None,
                        deferred=not bool(e["recording"] and e["recording"]["verdict"]),
                    )
                    for c, e in zip(cs, normal["events"], strict=True)
                    if e["admitted"]
                ]
                report = Report.build(fs, s, run=run, changed=1, judge=judge.name)
                write(folder / "report.json", report.model_dump(mode="json"))
                native = None
                complete = normal["unknown_funded"] == 0
                reported = [f.candidate.key for f in report.findings if f.reported]
            results.append(
                {
                    "cohort_id": cid,
                    "query": q,
                    "arm": arm,
                    "repository": panel["repository"],
                    "normal": normal,
                    "native": native,
                    "complete": complete,
                    "reports": reported,
                    "normal_logical_charge_usd": normal["estimated_usd"],
                }
            )
            planrows.append(plan)
            total = 0.0
            for ordinal, (c, event) in enumerate(zip(cs, normal["events"], strict=True), 1):
                rec = judge.lookup(c)
                ck = canonical(c)
                qid = "ENC-" + ck[:20]
                if rec:
                    eq = json.loads(pathlib.Path(rec["path"]).read_text()).get("question_equivalence")
                    request_key = rc.canonical(rec["identity"])
                    physical_key = eq["source_physical_request_key"] if eq else request_key
                    bindings.append(
                        {
                            "id": qid,
                            "arm": arm,
                            "cohort_id": cid,
                            "query": q,
                            "request_key": request_key,
                            "source_physical_request_key": physical_key,
                            "recording": {"path": rec["path"], "sha256": rec["sha256"]},
                            "match": "exact inherited RecordedJudge.lookup, including source/prompt/options/profile/settings",
                            "mismatch_reason": None,
                            "question_equivalence": eq,
                        }
                    )
                    if physical_key in physical:
                        assert physical[physical_key]["usd"] == rec["usd"]
                    physical[physical_key] = {
                        "source_physical_request_key": physical_key,
                        "usd": rec["usd"],
                        "outcome": recording_state(rec),
                    }
                elif cache.get(ck):
                    for path, raw in cache[ck]:
                        mismatches.append(
                            {
                                "id": qid,
                                "arm": arm,
                                "request_key": raw.get("request_key"),
                                "reason": "same Candidate digest but inherited exact lookup rejects source/prompt/options/profile/settings or usage; no fuzzy reuse",
                                "identity": raw["identity"],
                            }
                        )
                state = recording_state(rec)
                if state == "observed":
                    continue
                if not event["admitted"]:
                    continue
                if state == "paid_unknown":
                    paid_unknowns.append(
                        {
                            "id": qid,
                            "cohort_id": cid,
                            "query": q,
                            "arm": arm,
                            "ordinal": ordinal,
                            "candidate_key": c.key,
                            "request_key": request_key,
                            "source_physical_request_key": physical_key,
                            "recording": {"path": rec["path"], "sha256": rec["sha256"]},
                            "error": rec["error"],
                            "physical_usd": rec["usd"],
                            "normal_event": {k: v for k, v in event.items() if k != "recording"},
                            "retry_eligible": False,
                            "truth_label": None,
                        }
                    )
                    continue
                entry = missing.setdefault(
                    (cid, ck),
                    {
                        "id": qid,
                        "cohort_id": cid,
                        "repository": panel["repository"],
                        "revision": panel["revision"],
                        "candidate": c.model_dump(mode="json"),
                        "settings": s.model_dump(mode="json"),
                        "occurrences": [],
                    },
                )
                entry["occurrences"].append(
                    {
                        "query": q,
                        "arm": arm,
                        "ordinal": ordinal,
                        "normal_event": event,
                        "normal_funded": True,
                        "original_native_first_frontier": any(f["id"] == qid and f["arm"] == arm for f in frontier),
                    }
                )
    write(out / "results.jsonl", results)
    write(out / "plans.jsonl", planrows)
    write(out / "native-frontier.jsonl", frontier)
    write(out / "normal-funded-missing.jsonl", list(missing.values()))
    write(out / "exact-bindings.jsonl", bindings)
    write(out / "identity-mismatches.jsonl", mismatches)
    write(out / "paid-unknowns.jsonl", paid_unknowns)
    write(
        out / "PHYSICAL-REUSE.json",
        {
            "observations": list(physical.values()),
            "unique_source_physical_request_keys": len(physical),
            "known_previously_paid_usd": sum(x["usd"] or 0 for x in physical.values()),
            "usage_unknown": sum(x["usd"] is None for x in physical.values()),
            "fresh_provider_calls": 0,
            "meaning": "Only exact observations used by these arms; aliases collapse by source_physical_request_key. Historical physical usage, not fresh spend or normal logical charges.",
        },
    )
    summary = {
        "schema": 1,
        "subset": str(H / "COMPLETION-SUBSET.json"),
        "campaigns": 4,
        "arms": 16,
        "complete_arms": sum(r["complete"] for r in results),
        "native_frontier_occurrences": len(frontier),
        "normal_funded_missing_unique": len(missing),
        "exact_observation_matches": len(bindings),
        "identity_mismatches": len(mismatches),
        "recording_inputs": receipts,
        "reused_machinery": {"path": str(ADAPT / "replay_captures.py"), "sha256": sha(ADAPT / "replay_captures.py")},
        "provider_calls": 0,
        "derived_recordings_available": len(equivalences),
        "derived_recordings_used": sum(bool(x.get("question_equivalence")) for x in bindings),
        "independent_family_gains": None,
        "family_review": "pending; no reviewer labels read",
    }
    summary.update(
        {
            "paid_unknown_occurrences": len(paid_unknowns),
            "paid_unknown_unique": len({x["source_physical_request_key"] for x in paid_unknowns}),
            "unknown_policy": "Paid failures remain unknown; no retry frontier is emitted. Other campaigns continue.",
        }
    )
    write(out / "RESULTS.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
