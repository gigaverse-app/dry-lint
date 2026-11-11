# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, E731, F403, F405, F841, I001
from policy_common import *
import numpy as np, collections, time, resource


def allocate(ids, rows, data, pred, mode="combined", cap=0.04, ncap=None, linecap=None, native=False):
    cost = data["hold"] if native else data["cost"]
    selected = []
    total = 0.0
    lines = 0
    covered = collections.Counter()
    seen = set()
    pending = list(ids)
    if mode == "raw":
        pending.sort(key=lambda i: (rows[i]["tfidf_rank"], rows[i]["target_source"]))
    while pending:
        fit = [
            i
            for i in pending
            if total + cost[i] <= cap + 1e-12 and (linecap is None or lines + rows[i]["source_lines"] <= linecap)
        ]
        if not fit or (ncap is not None and len(selected) >= ncap):
            break
        if mode == "raw":
            i = fit[0]
        else:
            scored = []
            for j in fit:
                utility = float(pred[j])
                if utility < 0.15:
                    continue
                signals = rows[j]["shared_calls"]
                novelty = 1 / (1 + sum(covered[s] for s in signals) / max(1, len(signals)))
                if rows[j]["target_sha"] in seen:
                    novelty *= 0.1
                review = rows[j]["source_lines"] / 60
                value = utility * novelty / (cost[j] + 0.0005 * review)
                scored.append((value, -rows[j]["tfidf_rank"], rows[j]["target_source"], j))
            if not scored:
                break
            i = max(scored)[-1]
        selected.append(i)
        total += float(cost[i])
        lines += rows[i]["source_lines"]
        covered.update(rows[i]["shared_calls"])
        seen.add(rows[i]["target_sha"])
        pending.remove(i)
    return selected


def main():
    start = time.monotonic()
    cpu = time.process_time()
    inputs = json.loads((H / "INPUTS.json").read_text())
    selections = []
    case_results = []
    summary = collections.defaultdict(lambda: collections.Counter())
    depth = collections.defaultdict(collections.Counter)
    cases = jl(H / "cases.jsonl")
    caseby = collections.defaultdict(list)
    for c in cases:
        caseby[c["cohort_id"]].append(c)
    captured = {r["cohort_id"]: r for r in json.loads((B / "RESIDUAL-INPUTS.json").read_text())["captures"]}
    for a in inputs["arrays"]:
        cid = a["cohort_id"]
        rows = jl(a["metadata"])
        data = dict(np.load(a["path"]))
        scores = np.load(pathlib.Path(a["path"]).with_name("scores.npy"))
        pred = scores.mean(axis=1)
        capture = {}
        selected_by = {}
        knownkeys = set()
        canonical_pairs = {tuple(sorted(c["query_positions"])) for c in caseby[cid]}
        if cid in captured:
            assert sha(captured[cid]["path"]) == captured[cid]["sha256"]
            for c in jl(captured[cid]["path"]):
                if len(c["query_positions"]) == 1 and "minilm_stack" in c["arms"]:
                    capture[c["query_positions"][0]] = c
        for q in np.unique(data["query"]):
            ids = np.flatnonzero((data["query"] == q) & data["eligible"]).tolist()
            plans = {}
            plans["combined"] = allocate(ids, rows, data, pred)
            plans["linear"] = allocate(ids, rows, data, scores[:, 0])
            plans["interaction"] = allocate(ids, rows, data, scores[:, 1])
            plans["raw_dollar"] = allocate(ids, rows, data, pred, mode="raw")
            plans["raw_count"] = allocate(ids, rows, data, pred, mode="raw", ncap=len(plans["combined"]))
            plans["raw_source"] = allocate(
                ids, rows, data, pred, mode="raw", linecap=sum(rows[i]["source_lines"] for i in plans["combined"])
            )
            plans["combined_native"] = allocate(ids, rows, data, pred, native=True)
            plans["raw_native"] = allocate(ids, rows, data, pred, mode="raw", native=True)
            plans["combined_native_20control"] = allocate(ids, rows, data, pred, native=True, ncap=20)
            plans["raw_native_20control"] = allocate(ids, rows, data, pred, mode="raw", native=True, ncap=20)
            if int(q) in capture:
                cap = capture[int(q)]
                keys = {e["key"] for e in cap["native"]["minilm_stack"]["events"] if e["admitted"]}
                plans["deployed_captured"] = [i for i in ids if rows[i]["key"] in keys]
            record = {
                "cohort_id": cid,
                "repository": a["repository"],
                "query": int(q),
                "plans": {arm: [rows[i]["candidate_id"] for i in ii] for arm, ii in plans.items()},
                "indices": plans,
                "baseline_capture_available": int(q) in capture,
            }
            selections.append(record)
            for arm, ii in plans.items():
                selected_by.setdefault(arm, set()).update(tuple(sorted((int(q), rows[i]["target"]))) for i in ii)
                depth[arm][len(ii)] += 1
                s = summary[arm]
                s["queries"] += 1
                s["candidates"] += len(ii)
                s["normal_estimated_usd"] += sum(float(data["cost"][i]) for i in ii)
                s["native_hold_usd"] += sum(float(data["hold"][i]) for i in ii)
                s["source_lines"] += sum(rows[i]["source_lines"] for i in ii)
                s["outside_canonical_inventory"] += sum(
                    tuple(sorted((int(q), rows[i]["target"]))) not in canonical_pairs for i in ii
                )
        for c in caseby[cid]:
            c = {
                **c,
                "hits": {arm: tuple(sorted(c["query_positions"])) in pairs for arm, pairs in selected_by.items()},
                "captured_both_directions": all(q in capture for q in c["query_positions"]),
            }
            case_results.append(c)
        write(
            H / "ALLOCATION-PROGRESS.json",
            {
                "completed_backgrounds": len({r["cohort_id"] for r in selections}),
                "queries": len(selections),
                "seconds": time.monotonic() - start,
            },
        )
        print(cid, len(rows), len(selected_by), flush=True)
    # Deduplicate aliases using the same exact canonical pair, accepted flag and category as frozen reference.
    unique = {}
    for c in case_results:
        key = (c["cohort_id"], c["pair_identity"], c["label"], c["accepted_gold"])
        unique.setdefault(key, c)
    metrics = []
    for arm in summary:
        cs = [c for c in unique.values() if arm != "deployed_captured" or c["captured_both_directions"]]
        for label, accepted in sorted({(str(c["label"]), c["accepted_gold"]) for c in cs}):
            rs = [c for c in cs if str(c["label"]) == label and c["accepted_gold"] == accepted]
            hit = [c for c in rs if c["hits"].get(arm, False)]
            base = [c for c in rs if c["hits"].get("raw_native" if arm.endswith("native") else "raw_dollar", False)]
            keys = lambda vv: {(c["cohort_id"], c["pair_identity"]) for c in vv}
            metrics.append(
                {
                    "arm": arm,
                    "label": label,
                    "accepted": accepted,
                    "denominator": len(rs),
                    "hit_pairs": len(hit),
                    "components": len({c["source_component"] for c in hit}),
                    "added_vs_raw": len(keys(hit) - keys(base)),
                    "lost_vs_raw": len(keys(base) - keys(hit)),
                }
            )
    write(H / "selections.jsonl", selections)
    write(H / "case-results.jsonl", list(unique.values()))
    write(
        H / "RESULTS.json",
        {
            "metrics": metrics,
            "costs": dict(summary),
            "depth": {a: dict(v) for a, v in depth.items()},
            "backgrounds": len(inputs["arrays"]),
            "queries": len(selections),
            "seconds": time.monotonic() - start,
            "cpu_seconds": time.process_time() - cpu,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "actual_new_emitted_reports": 0,
            "status": "offline_selection_only_pending_root_answers",
            "native_scope": "One-pool dollar-only experimental allocator, exploration cap .04, eligible-pool call ceiling; separately named inherited 20-call configuration controls; no settlement without answers. Captured deployed arm retains original baseline/exploration settings. All caps .04.",
        },
    )


if __name__ == "__main__":
    main()
