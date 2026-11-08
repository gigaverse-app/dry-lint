# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B905, E401, E402, E741, F401, F841, I001
"""One label revealed per scenario; outcomes consulted only after immutable queues."""

import os

for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[k] = "2"
import sys

sys.dont_write_bytecode = True
import json, collections, hashlib, pathlib, time, math
import numpy as np
from prepare import H, jl, sha, write
from analyze import bootstrap


def main():
    tick = time.monotonic()
    contract = json.loads((H / "EXPERIMENT-CONTRACT.json").read_text())
    X = np.load(H / "features.npy")
    rows = list(jl(H / "rows.jsonl"))
    bycohort = collections.defaultdict(list)
    groups = collections.defaultdict(list)
    for i, r in enumerate(rows):
        bycohort[r["cohort_id"]].append(i)
        if r["label"] >= 0:
            comp = sorted({l["inventory"]["component"] for l in r["labels"]})[0]
            groups[comp].append(i)
    # All selection before seed labels are accessed; labels above only determine availability.
    seeds = [min(ids, key=lambda i: rows[i]["pair_id"]) for ids in groups.values()]
    params = {(m["test_repository"], m["arm"]): m for m in json.loads((H / "MODELS.json").read_text())["parameters"]}
    sizes = {}
    sources = {}
    for p in contract["inputs"]:
        cid = p["cohort_id"]
        fp = p["source"]["functions_path"]
        assert sha(fp) == p["source"]["functions_sha256"]
        sizes[cid] = [len(f["code"]) for f in jl(fp)]
    records = []
    queues = []
    with (H / "one-seed-queues.jsonl").open("w") as queueout:
        for seed in seeds:
            sr = rows[seed]
            cid = sr["cohort_id"]
            endpoints = set(sr["positions"])
            components = set(sr["graph_components"])
            component = sorted({l["inventory"]["component"] for l in sr["labels"]})[0]
            seed_positive = True
            actual_seed_positive = sr["label"] == 1
            pool = [
                i
                for i in bycohort[cid]
                if i != seed
                and (endpoints & set(rows[i]["positions"]) or components & set(rows[i]["graph_components"]))
            ]
            pool = sorted(pool, key=lambda i: (-rows[i]["fixed_fusion"], rows[i]["pair_id"]))[:100]
            if not pool:
                continue
            m = params.get((sr["repository"], "svm"))
            xx = X[pool].copy()
            xx[:, 17] = [int(seed_positive and bool(endpoints & set(rows[i]["positions"]))) for i in pool]
            xx[:, 18] = [int(seed_positive and bool(components & set(rows[i]["graph_components"]))) for i in pool]
            xx[:, 19] = [int(bool(endpoints & set(rows[i]["positions"]))) for i in pool]
            if m:
                z = (xx - np.array(m["scaler_mean"])) / np.array(m["scaler_scale"])
                margin = z @ np.array(m["svm_coef"][0]) + m["svm_intercept"][0]
                score = margin * m["sigmoid_coef"][0][0] + m["sigmoid_intercept"][0]
            else:
                score = np.array([rows[i]["fixed_fusion"] for i in pool])
            arms = {
                "fixed_fusion": pool,
                "seed_anchor_first": sorted(
                    pool,
                    key=lambda i: (
                        -int(seed_positive and bool(endpoints & set(rows[i]["positions"]))),
                        -rows[i]["fixed_fusion"],
                        rows[i]["pair_id"],
                    ),
                ),
                "svm_one_seed_transport": sorted(pool, key=lambda i: (-score[pool.index(i)], rows[i]["pair_id"])),
            }
            mode = "source_positive_single_seed" if actual_seed_positive else "source_negative_false_seed_control"
            for arm, order in arms.items():
                # Freeze queue: no sibling labels copied or consulted until this write.
                queueout.write(
                    json.dumps(
                        {
                            "seed_pair_id": sr["pair_id"],
                            "source_component": component,
                            "cohort_id": cid,
                            "arm": arm,
                            "seed_presented_positive": seed_positive,
                            "seed_source_positive": actual_seed_positive,
                            "queue": [rows[i]["pair_id"] for i in order],
                            "hidden_sibling_labels": True,
                        }
                    )
                    + "\n"
                )
                for b in [1, 3, 5, 10, 20]:
                    for policy in ["continue", "branch_local_stop", "cluster_stop"]:
                        selected = []
                        closed = set()
                        read = set(endpoints)
                        newchars = 0
                        fullchars = 0
                        unknown_before_stop = 0
                        for i in order:
                            if len(selected) >= b:
                                break
                            r = rows[i]
                            shared = endpoints & set(r["positions"])
                            branch = ("endpoint", min(shared)) if shared else ("component", min(r["graph_components"]))
                            if branch in closed:
                                continue
                            selected.append(i)
                            for pos in r["positions"]:
                                fullchars += sizes[cid][pos]
                                if pos not in read:
                                    newchars += sizes[cid][pos]
                                    read.add(pos)
                            if r["label"] == -1:
                                unknown_before_stop += 1
                            if r["label"] == 0:
                                if policy == "cluster_stop":
                                    break
                                if policy == "branch_local_stop":
                                    closed.add(branch)
                        ys = [rows[i]["label"] for i in selected]
                        records.append(
                            {
                                "seed_pair_id": sr["pair_id"],
                                "source_component": component,
                                "repository": sr["repository"],
                                "cohort_id": cid,
                                "seed_mode": mode,
                                "arm": arm,
                                "budget": b,
                                "policy": policy,
                                "reviewed": len(selected),
                                "positive": ys.count(1),
                                "negative": ys.count(0),
                                "unknown": ys.count(-1),
                                "positive_components": sorted(
                                    {
                                        l["inventory"]["component"]
                                        for i in selected
                                        if rows[i]["label"] == 1
                                        for l in rows[i]["labels"]
                                    }
                                ),
                                "full_source_characters_without_reuse": fullchars,
                                "additional_unique_source_characters": newchars,
                                "additional_source_tokens_proxy": math.ceil(newchars / 4),
                                "unknown_response_may_change_stopping": policy != "continue"
                                and bool(unknown_before_stop),
                                "selected_pair_ids": [rows[i]["pair_id"] for i in selected],
                            }
                        )
    with (H / "one-seed-results.jsonl").open("w") as f:
        for r in records:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    label_by_id = {r["pair_id"]: r["label"] for r in rows}
    summary = []
    for key in sorted({(r["seed_mode"], r["arm"], r["budget"], r["policy"]) for r in records}):
        ss = [r for r in records if (r["seed_mode"], r["arm"], r["budget"], r["policy"]) == key]
        total = {
            k: sum(r[k] for r in ss)
            for k in [
                "reviewed",
                "positive",
                "negative",
                "unknown",
                "full_source_characters_without_reuse",
                "additional_unique_source_characters",
            ]
        }
        chars = total["additional_unique_source_characters"]
        summary.append(
            dict(zip(["seed_mode", "arm", "budget", "policy"], key))
            | {
                "scenarios": len(ss),
                "totals_occurrences": total,
                "unique_positive_pairs": len({p for r in ss for p in r["selected_pair_ids"] if label_by_id[p] == 1}),
                "positive_components": len({c for r in ss for c in r["positive_components"]}),
                "known_positive_per_100k_additional_characters": total["positive"] * 100000 / chars if chars else None,
                "positive_per_scenario_component_bootstrap": bootstrap(
                    [r["positive"] for r in ss], [r["source_component"] for r in ss]
                ),
                "positive_per_scenario_repo_bootstrap": bootstrap(
                    [r["positive"] for r in ss], [r["repository"] for r in ss]
                ),
            }
        )
    write(
        "ONE-SEED-RESULTS.json",
        {
            "schema": 1,
            "seed_scenarios_selected": len(seeds),
            "source_components_selected": len(groups),
            "rows": summary,
            "seconds": time.monotonic() - tick,
            "contract_sha256": sha(H / "ONE-SEED-CONTRACT.json"),
            "script_sha256": sha(__file__),
            "all_other_positive_seed_features_used": False,
            "stopping_warning": "Partial observed-outcome replay; unknown decisions are not rejections and can change stopping. Graph-component branch is coarse, not operation identity. Scores trained on all-other oracle are transport stress-test only, not calibrated one-seed probabilities.",
        },
    )
    print("one seed done", len(seeds), len(records), flush=True)


if __name__ == "__main__":
    main()
