# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B905, E401, E402, E731, E741, F841, I001
"""Read-only independent evaluation of graph worker's frozen native-relative replay."""

from _recovery_paths import recovery_path
import os

for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[k] = "2"
import sys

sys.dont_write_bytecode = True
import json, pathlib, collections, hashlib, math
from prepare import H, jl, write, sha
from analyze import bootstrap

G = pathlib.Path(recovery_path("jobs/confirmed-cluster-expansion/.lab-results"))


def main():
    c = json.loads((H / "EXPERIMENT-CONTRACT.json").read_text())
    allowed = {p["cohort_id"]: p for p in c["inputs"]}
    frozen = H / "graph-snapshot"
    frozen.mkdir(exist_ok=True)
    inputs = {}
    for name in ["CLUSTER-CONTRACT.json", "seed-exposures.jsonl", "proposals.jsonl", "outcomes.jsonl", "metrics.jsonl"]:
        data = (frozen / name).read_bytes() if (frozen / name).exists() else (G / name).read_bytes()
        (frozen / name).write_bytes(data)
        inputs[name] = hashlib.sha256(data).hexdigest()
    seeds = {s["seed_id"]: s for s in jl(frozen / "seed-exposures.jsonl") if s["cohort_id"] in allowed}
    proposals = collections.defaultdict(list)
    for p in jl(frozen / "proposals.jsonl"):
        if p["seed_id"] in seeds:
            assert p["repository"] == allowed[p["cohort_id"]]["repository"]
            proposals[p["seed_id"], p["method"]].append(p)
    raw_proposal_count = sum(map(len, proposals.values()))
    for key, items in list(proposals.items()):
        unique = {}
        for item in sorted(items, key=lambda p: (-p["ranking_score"], p["proposal_id"])):
            unique.setdefault(tuple(sorted((item["query_position"], item["target_position"]))), item)
        proposals[key] = list(unique.values())
    labels = {}
    sizes = {}
    known_rows = []
    for cid in {s["cohort_id"] for s in seeds.values()}:
        p = allowed[cid]
        assert sha(p["targets_path"]) == p["targets_sha256"]
        ls = collections.defaultdict(list)
        for t in jl(p["targets_path"]):
            if t["canonical_evaluation"]:
                ls[tuple(sorted(t["query_positions"]))].append(t)
        labels[cid] = ls
        assert sha(p["source"]["functions_path"]) == p["source"]["functions_sha256"]
        sizes[cid] = [len(f["code"]) for f in jl(p["source"]["functions_path"])]

    def outcome(cid, p):
        ls = labels[cid].get(tuple(sorted((p["query_position"], p["target_position"]))), [])
        ys = {
            l["label"]
            for l in ls
            if l["accepted_gold"] and l.get("calibration_eligible", True) and l["label"] in ["duplicate", "separate"]
        }
        return int(next(iter(ys)) == "duplicate") if len(ys) == 1 else -1

    records = []
    for sid, s in seeds.items():
        cid = s["cohort_id"]
        native = sorted(
            proposals[sid, "current_relatives_native"], key=lambda p: (-p["ranking_score"], p["proposal_id"])
        )
        key = lambda p: tuple(sorted((p["query_position"], p["target_position"])))
        nkeys = {key(p) for p in native}
        mode = s["seed_mode"]
        if mode == "real_prior_judge_confirmed":
            mode = "recorded_provider_positive_native_emission_unverified"
        for arm in [
            "current_relatives_native",
            "unseeded_changed_endpoint",
            "reciprocal_anchored",
            "bounded_seed_diffusion",
        ]:
            ranked = sorted(proposals[sid, arm], key=lambda p: (-p["ranking_score"], p["proposal_id"]))
            queue = native + [p for p in ranked if key(p) not in nkeys] if arm != "current_relatives_native" else native
            for b in [1, 3, 5, 10, 20, 100]:
                chosen = queue[:b]
                baseline = native[:b]
                extra = [p for p in chosen if key(p) not in nkeys]
                seednodes = set(s["positions"])
                basenodes = seednodes | {pos for p in baseline for pos in key(p)}
                newnodes = {pos for p in extra for pos in key(p)} - basenodes
                ys = [outcome(cid, p) for p in extra]
                baseys = [outcome(cid, p) for p in baseline]
                chars = sum(sizes[cid][pos] for pos in newnodes)
                records.append(
                    {
                        "seed_id": sid,
                        "source_component": s["source_component"],
                        "repository": s["repository"],
                        "cohort_id": cid,
                        "seed_mode": mode,
                        "seed_lane": s["lane"],
                        "arm": arm,
                        "budget": b,
                        "baseline_reviewed": len(baseline),
                        "baseline_positive": baseys.count(1),
                        "baseline_negative": baseys.count(0),
                        "baseline_unknown": baseys.count(-1),
                        "additional_reviewed": len(extra),
                        "additional_positive": ys.count(1),
                        "additional_negative": ys.count(0),
                        "additional_unknown": ys.count(-1),
                        "additional_unique_source_characters": chars,
                        "additional_source_tokens_proxy": math.ceil(chars / 4),
                        "lost_native_proposals": len({key(p) for p in baseline} - {key(p) for p in chosen}),
                        "additional_pair_keys": [list(key(p)) for p in extra],
                        "known_positive_additions": [
                            {
                                "positions": list(key(p)),
                                "proposal_id": p["proposal_id"],
                                "labels": labels[cid].get(key(p), []),
                            }
                            for p in extra
                            if outcome(cid, p) == 1
                        ],
                    }
                )
    with (H / "graph-budget-results.jsonl").open("w") as f:
        for r in records:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    summary = []
    for k in sorted({(r["seed_mode"], r["arm"], r["budget"]) for r in records}):
        rs = [r for r in records if (r["seed_mode"], r["arm"], r["budget"]) == k]
        keys = [
            "baseline_reviewed",
            "baseline_positive",
            "baseline_negative",
            "baseline_unknown",
            "additional_reviewed",
            "additional_positive",
            "additional_negative",
            "additional_unknown",
            "additional_unique_source_characters",
            "lost_native_proposals",
        ]
        totals = {key: sum(r[key] for r in rs) for key in keys}
        summary.append(
            dict(zip(["seed_mode", "arm", "budget"], k))
            | {
                "scenarios": len(rs),
                "totals_occurrences": totals,
                "unique_positive_additions": len(
                    {(r["cohort_id"], tuple(x["positions"])) for r in rs for x in r["known_positive_additions"]}
                ),
                "source_component_bootstrap_mean_additional_positive": bootstrap(
                    [r["additional_positive"] for r in rs], [r["source_component"] for r in rs]
                ),
                "repository_bootstrap_mean_additional_positive": bootstrap(
                    [r["additional_positive"] for r in rs], [r["repository"] for r in rs]
                ),
            }
        )
    write(
        "GRAPH-REFERENCE.json",
        {
            "schema": 1,
            "inputs": inputs,
            "cohorts": len(sizes),
            "seeds": len(seeds),
            "raw_seed_rows": sum(1 for _ in jl(frozen / "seed-exposures.jsonl")),
            "raw_proposal_rows": raw_proposal_count,
            "unique_seed_method_pairs": sum(map(len, proposals.values())),
            "results": summary,
            "comparison": "Native pinned Detector.relatives outputs protected first; wider lead queue assessed within same review count. No native Judging/settled dollar replay performed here. Native source-gold seeds are oracle. Recorded provider seed is exact request-bound but historical report emission remains unverified.",
            "source_grouping": "Audit source components, not graph connectivity",
            "truth": "Source-positive registry operation label only; no new independent source review or report acceptance. Unknown speculative leads are permissible review cost, never presumed false.",
        },
    )
    print("graph done", len(seeds), len(records))


if __name__ == "__main__":
    main()
