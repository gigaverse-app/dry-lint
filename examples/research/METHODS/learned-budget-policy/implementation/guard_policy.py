# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, F403, F405, I001
from policy_common import *
from allocate_policy import allocate
import numpy as np, time, collections, resource


def guarded(ids, rows, data, pred, native=False):
    if not ids:
        return []
    maximum = max(data["tfidf"][i] for i in ids)
    strong = [i for i in ids if data["tfidf"][i] > 0 and data["tfidf"][i] >= 0.5 * maximum]
    seeds = allocate(strong, rows, data, pred, mode="raw", cap=0.01, native=native)
    cost = data["hold"] if native else data["cost"]
    remaining = 0.04 - sum(float(cost[i]) for i in seeds)
    seedset = set(seeds)
    return seeds + allocate([i for i in ids if i not in seedset], rows, data, pred, cap=remaining, native=native)


def main():
    start = time.monotonic()
    cpu = time.process_time()
    inputs = json.loads((H / "INPUTS.json").read_text())
    selections = []
    metrics = collections.defaultdict(collections.Counter)
    depth = collections.defaultdict(collections.Counter)
    hit = collections.defaultdict(set)
    for a in inputs["arrays"]:
        cid = a["cohort_id"]
        rows = jl(a["metadata"])
        data = dict(np.load(a["path"]))
        pred = np.load(pathlib.Path(a["path"]).with_name("scores.npy")).mean(axis=1)
        for q in np.unique(data["query"]):
            ids = np.flatnonzero((data["query"] == q) & data["eligible"]).tolist()
            plans = {"guarded": guarded(ids, rows, data, pred), "guarded_native": guarded(ids, rows, data, pred, True)}
            plans["guard_raw_count"] = allocate(ids, rows, data, pred, mode="raw", ncap=len(plans["guarded"]))
            plans["guard_raw_source"] = allocate(
                ids, rows, data, pred, mode="raw", linecap=sum(rows[i]["source_lines"] for i in plans["guarded"])
            )
            selections.append(
                {
                    "cohort_id": cid,
                    "repository": a["repository"],
                    "query": int(q),
                    "indices": plans,
                    "plans": {arm: [rows[i]["candidate_id"] for i in ii] for arm, ii in plans.items()},
                }
            )
            for arm, ii in plans.items():
                hit[cid, arm].update(tuple(sorted((int(q), rows[i]["target"]))) for i in ii)
                m = metrics[arm]
                m["queries"] += 1
                m["candidates"] += len(ii)
                m["normal_estimated_usd"] += sum(float(data["cost"][i]) for i in ii)
                m["native_hold_usd"] += sum(float(data["hold"][i]) for i in ii)
                m["source_lines"] += sum(rows[i]["source_lines"] for i in ii)
                depth[arm][len(ii)] += 1
        print(cid, flush=True)
    cases = jl(H / "case-results.jsonl")
    for c in cases:
        c["hits"].update({arm: tuple(sorted(c["query_positions"])) in hit[c["cohort_id"], arm] for arm in metrics})
    results = []
    for arm in metrics:
        for label, accepted in sorted({(str(c["label"]), c["accepted_gold"]) for c in cases}):
            rs = [c for c in cases if str(c["label"]) == label and c["accepted_gold"] == accepted]
            hs = [c for c in rs if c["hits"][arm]]
            base = "raw_native" if arm == "guarded_native" else "raw_dollar"
            results.append(
                {
                    "arm": arm,
                    "label": label,
                    "accepted": accepted,
                    "denominator": len(rs),
                    "hit_pairs": len(hs),
                    "components": len({c["source_component"] for c in hs}),
                    "added_vs_raw": sum(c["hits"][arm] and not c["hits"][base] for c in rs),
                    "lost_vs_raw": sum(not c["hits"][arm] and c["hits"][base] for c in rs),
                }
            )
    write(H / "guard-selections.jsonl", selections)
    write(H / "guard-case-results.jsonl", cases)
    write(
        H / "GUARD-RESULTS.json",
        {
            "metrics": results,
            "costs": dict(metrics),
            "depth": {a: dict(v) for a, v in depth.items()},
            "backgrounds": len(inputs["arrays"]),
            "queries": len(selections),
            "seconds": time.monotonic() - start,
            "cpu_seconds": time.process_time() - cpu,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "contract_sha256": sha(H / "REVISION-CONTRACT.json"),
            "actual_new_emitted_reports": 0,
            "provider_calls": 0,
        },
    )


if __name__ == "__main__":
    main()
