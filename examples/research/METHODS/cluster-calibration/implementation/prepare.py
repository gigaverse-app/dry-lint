# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B023, E401, E402, E731, E741, I001
"""Frozen provider-free bank graph reference; no model or judge calls."""

from _recovery_paths import recovery_path
import os

for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[k] = "2"
import sys

sys.dont_write_bytecode = True
import pathlib, json, hashlib, collections, math, time
import numpy as np

H = pathlib.Path(__file__).resolve().parent
R = pathlib.Path(recovery_path(""))


def sha(p):
    with open(p, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def jl(p):
    with open(p) as f:
        for l in f:
            if l.strip():
                yield json.loads(l)


def write(p, v):
    (H / p).write_text(json.dumps(v, indent=2, sort_keys=True, allow_nan=False) + "\n")


def excluded(repo):
    return any(x in repo.lower() for x in ["opencode", "firecrawl", "curator"])


class DSU:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        if self.p[x] != x:
            self.p[x] = self.find(self.p[x])
        return self.p[x]

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.p[max(a, b)] = min(a, b)


def main():
    tick = time.monotonic()
    c = json.loads((H / "EXPERIMENT-CONTRACT.json").read_text())
    s = json.loads(pathlib.Path(c["split_path"]).read_text())
    assert sha(c["split_path"]) == c["split_sha256"]
    held = set(s["holdout"]["exclude_connected_components"])
    hs = json.loads(pathlib.Path(s["holdout"]["identity_file"]).read_text())
    hb = set(hs["body_sha256"])
    inv = {
        r["row_id"]: r
        for r in jl(s["inventory_rows_path"])
        if not excluded(r["repository"]) and r["component"] not in held
    }
    source_group = {}
    for r in inv.values():
        for ident in r["endpoint_identities"]:
            source_group[ident] = r["component"]
    allx = []
    stats = []
    labelsout = []
    names = c["features"]
    with (H / "rows.jsonl").open("w") as out:
        for p in c["inputs"]:
            cid = p["cohort_id"]
            assert not excluded(p["repository"])
            assert sha(p["bank_path"]) == p["bank_sha256"]
            assert sha(p["targets_path"]) == p["targets_sha256"]
            labels = collections.defaultdict(list)
            for t in jl(p["targets_path"]):
                if not t["canonical_evaluation"] or t["row_id"] not in inv:
                    continue
                if any(e["source_sha256"] in hb for e in t["endpoint_identities"]):
                    continue
                labels[tuple(sorted(t["query_positions"]))].append(t | {"inventory": inv[t["row_id"]]})
            pairs = {}
            adj = collections.defaultdict(set)
            outgoing = collections.defaultdict(set)
            ds = DSU()
            blocked = 0
            directions = 0
            for r in jl(p["bank_path"]):
                if not r["native_eligible"]:
                    continue
                if any(r["source"][e]["source_sha256"] in hb for e in ("query", "target")):
                    blocked += 1
                    continue
                q, t = r["query_position"], r["target_position"]
                key = tuple(sorted((q, t)))
                directions += 1
                if r["features"]["fixed_fusion_rank"] <= 10:
                    outgoing[q].add(t)
                    adj[q].add(t)
                    adj[t].add(q)
                    ds.union(q, t)
                if key not in pairs:
                    pairs[key] = {"row": r, "directions": []}
                old = pairs[key]["row"]
                if (r["scores"]["fixed_fusion"], r["candidate_id"]) > (
                    old["scores"]["fixed_fusion"],
                    old["candidate_id"],
                ):
                    pairs[key]["row"] = r
                pairs[key]["directions"].append(
                    {
                        "query": q,
                        "target": t,
                        "candidate_id": r["candidate_id"],
                        "tfidf_cross_rank": r["features"]["tfidf_cross_rank"],
                        "fixed_fusion_rank": r["features"]["fixed_fusion_rank"],
                    }
                )
            states = {}
            pos = collections.defaultdict(set)
            neg = collections.defaultdict(set)
            reviewed = collections.defaultdict(set)
            pc = collections.defaultdict(set)
            for key, ls in labels.items():
                elig = [
                    x
                    for x in ls
                    if x["accepted_gold"]
                    and x.get("calibration_eligible", True)
                    and x["label"] in ["duplicate", "separate"]
                ]
                ys = {x["label"] for x in elig}
                y = int(next(iter(ys)) == "duplicate") if len(ys) == 1 else -1
                states[key] = y
                if y < 0:
                    continue
                for node in key:
                    reviewed[node].add(key)
                    (pos if y else neg)[node].add(key)
                    if y:
                        pc[ds.find(node)].add(key)
            cohort_counts = collections.Counter()
            for key, entry in sorted(pairs.items()):
                r = entry["row"]
                f = r["features"]
                q, t = key
                ls = labels.get(key, [])
                y = states.get(key, -1)
                ps = (pos[q] | pos[t]) - {key}
                ns = (neg[q] | neg[t]) - {key}
                rs = (reviewed[q] | reviewed[t]) - {key}
                cs = (pc[ds.find(q)] | pc[ds.find(t)]) - {key}
                nq, nt = adj[q], adj[t]
                union = nq | nt
                common = nq & nt
                density = lambda node: (
                    sum(len(adj[a] & adj[node]) for a in adj[node]) / (len(adj[node]) * (len(adj[node]) - 1))
                    if len(adj[node]) > 1
                    else 0.0
                )
                votes = (
                    int(r["routes"]["tfidf"])
                    + int(r["routes"]["minilm"] or r["routes"]["tail"])
                    + int(r["routes"]["block"])
                    + int(r["routes"]["containment"])
                )
                x = [
                    f["tfidf_score"],
                    f.get("minilm_score", 0),
                    max(0, f.get("tail_score", 0)),
                    f.get("block_score", 0),
                    f.get("containment_score", 0),
                    math.log1p(min(f["query_lines"], f["target_lines"])),
                    math.log1p(max(f["query_lines"], f["target_lines"])),
                    f["length_ratio"],
                    int(f["same_file"]),
                    votes,
                    math.log1p(f["shared_api_tokens"]),
                    f["contract_jaccard"],
                    (density(q) + density(t)) / 2,
                    int(t in outgoing[q] and q in outgoing[t]),
                    len(common) / max(1, len(union)),
                    math.log1p(max(len(nq), len(nt))),
                    float(f.get("block_score", 0) > 0),
                    int(bool(ps)),
                    int(bool(cs)),
                    int(bool(rs)),
                ]
                components = sorted(
                    {l["inventory"]["component"] for l in ls}
                    | {
                        source_group[z]
                        for e in ("query", "target")
                        if (z := p["repository"] + "::" + r["source"][e]["source_id"]) in source_group
                    }
                )
                pid = hashlib.sha256((cid + ":" + str(key)).encode()).hexdigest()[:20]
                row = {
                    "index": len(allx),
                    "pair_id": pid,
                    "cohort_id": cid,
                    "repository": p["repository"],
                    "revision": p["revision"],
                    "positions": list(key),
                    "source": r["source"],
                    "directions": entry["directions"],
                    "label": y,
                    "labels": ls,
                    "components": components,
                    "graph_components": sorted({ds.find(q), ds.find(t)}),
                    "oracle_endpoint_seed_pairs": [list(k) for k in sorted(ps)],
                    "false_endpoint_seed_pairs": [list(k) for k in sorted(ns)],
                    "other_reviewed_seed_pairs": [list(k) for k in sorted(rs)],
                    "oracle_component_seed_count": len(cs),
                    "fixed_fusion": r["scores"]["fixed_fusion"],
                    "tfidf": f["tfidf_score"],
                }
                allx.append(x)
                out.write(json.dumps(row, sort_keys=True) + "\n")
                cohort_counts["pairs"] += 1
                cohort_counts[{1: "positive", 0: "negative", -1: "unknown"}[y]] += 1
                if ls:
                    labelsout.append({"pair_id": pid, "cohort_id": cid, "labels": ls})
            stats.append(
                {
                    "cohort_id": cid,
                    "repository": p["repository"],
                    "directions": directions,
                    "held_body_rows_excluded": blocked,
                    "reference_graph_edges": sum(map(len, adj.values())) // 2,
                    "reference_graph_components": len({ds.find(n) for n in adj}),
                    "targets_missing_from_bank": sum(k not in pairs for k in labels),
                    "counts": dict(cohort_counts),
                }
            )
            print(cid, dict(cohort_counts), flush=True)
    np.save(H / "features.npy", np.asarray(allx, dtype=np.float32))
    write(
        "PREPARED.json",
        {
            "schema": 1,
            "features": names,
            "cohorts": stats,
            "rows": len(allx),
            "seconds": time.monotonic() - tick,
            "contract_sha256": sha(H / "EXPERIMENT-CONTRACT.json"),
            "script_sha256": sha(__file__),
            "inventory_sha256": sha(s["inventory_rows_path"]),
            "held_identity_sha256": sha(s["holdout"]["identity_file"]),
            "graph_worker_available_at_start": False,
            "direction_aggregation": "Undirected exact pair representative is largest fixed fusion, tie candidate id, selected without labels. All original query memberships retained. Labels and source metadata preserved.",
        },
    )
    write(
        "STATUS.json",
        {
            "state": "bank-prepared",
            "worker": "cluster-calibration",
            "rows": len(allx),
            "next": "Run matched lift, leave-repository-out model and budget diagnostics",
            "no_provider_calls": True,
        },
    )


if __name__ == "__main__":
    main()
