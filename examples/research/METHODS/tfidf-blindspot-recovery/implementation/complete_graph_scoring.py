# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: F403, F405
"""Consume all-source operation edges; no grouping, seeds, labels, or inference."""

import recover as R
from recover import *


def gemmas():
    out = collections.defaultdict(list)
    base = ROOT / "jobs/gemma-cpu-evaluation/.lab-results/ranking/ranks/gemma2-bf16-t4-symmetric-4096"
    for fp in sorted(base.glob("*.receipt.json")):
        if any(s in fp.name for s in ["bf60fb3615061d02", "faef200af37c7cb5"]):
            continue
        r = json.loads(fp.read_text()).get("matrix_receipt", {})
        if r.get("status") == "complete" and r.get("document_matrix_path"):
            out[r["cohort_id"]].append((fp, r))
    return out


def main():
    start = time.monotonic()
    indexpath = H / "LOCAL-GRAPH-CACHE-INDEX.json"
    index = json.loads(indexpath.read_text())
    mats = R.matrix_receipts()
    gm = gemmas()
    for cid, rs in gm.items():
        mats[cid] += rs
    allrows = []
    metrics = []
    write(
        H / "GRAPH-RECIPE-COMPLETE.json",
        {
            "schema": 1,
            "version": "all-source-operation-dense-v1",
            "rule": "same .35 sparse exclusion, .65 max cached dense gate and .6 structural + .4 dense score as normalized route; consume existing all-source operation-block edges rather than reimplementing graph grouping",
            "graph_index_sha256": sha(indexpath),
            "cache_selection": "source-exact CodeRank4096 and Gemma4096 receipts; absent remains unavailable",
            "operation_gate": "existing nonempty operation_evidence; mechanical source spans and operations retained; semantic independent ownership remains review question",
            "label_access": False,
            "native_budget": 0.04,
            "physical_cap": 1.25,
        },
    )
    for panel in index["cohorts"]:
        cid = panel["cohort_id"]
        p = panel["receipt_source"]
        out = H / "graph-generation" / cid
        if p["repository"] == "anomalyco/opencode":
            continue
        if (out / "METRICS.json").exists():
            metrics.append(json.loads((out / "METRICS.json").read_text()))
            allrows += jl(out / "candidates.jsonl")
            continue
        tick = time.monotonic()
        adj = pathlib.Path(panel["adjacency"])
        counts = collections.Counter()
        if not adj.exists():
            write(
                out / "METRICS.json",
                {
                    "cohort_id": cid,
                    "status": "unavailable",
                    "reason": "all-source graph adjacency absent",
                    "counts": {},
                },
            )
            write(out / "candidates.jsonl", [])
            metrics.append(json.loads((out / "METRICS.json").read_text()))
            continue
        assert sha(adj) == panel["adjacency_sha256"]
        assert sha(p["functions_path"]) == p["functions_sha256"] and sha(p["background_path"]) == p["background_sha256"]
        fs = jl(p["functions_path"])
        bg = BenchBackground.decode(pathlib.Path(p["background_path"]).read_bytes())
        idx = bg.index()
        vectors = {}
        sparse = {}
        bankqueries = {r["query_position"] for r in jl(BANK / "deterministic-v2/bank" / cid / "queries.jsonl")}
        dense = {}
        avail = {}
        source_matrices = [
            (
                "minilm",
                {"document_matrix_path": p["minilm_matrix_path"], "document_matrix_sha256": p["minilm_matrix_sha256"]},
            )
        ]
        for fp, m in mats.get(cid, []):
            if (
                m.get("functions_sha256") != p["functions_sha256"]
                or m.get("background_sha256") != p["background_sha256"]
            ):
                continue
            name = "coderank" if "coderank" in str(fp) else "gemma"
            source_matrices.append((name, m))
            avail[name] = {"receipt": str(fp), "sha256": sha(fp)}
        for name, m in source_matrices:
            assert sha(m["document_matrix_path"]) == m["document_matrix_sha256"]
            dense[name] = np.load(m["document_matrix_path"], mmap_mode="r")
            avail.setdefault(name, {})["matrix_sha256"] = m["document_matrix_sha256"]
        assert sha(p["minilm_tail_matrix_path"]) == p["minilm_tail_matrix_sha256"]
        z = np.load(p["minilm_tail_matrix_path"])
        tv = z["vectors"]
        tailby = collections.defaultdict(list)
        for i, q in enumerate(z["owners"]):
            tailby[int(q)].append(i)
        emitted = []
        for line in adj.open():
            counts["graph_edges"] += 1
            if '"operation_evidence": []' in line:
                continue
            e = json.loads(line)
            if not e["operation_evidence"]:
                continue
            counts["operation_edges"] += 1
            q = e["query_position"]
            t = e["target_position"]
            f, g = fs[q], fs[t]
            for i in (q, t):
                if i not in vectors:
                    vectors[i] = idx.vector(bg.documents[i].tokens())
            score = sum(vectors[q][k] * vectors[t].get(k, 0) for k in sorted(vectors[q]))
            if score >= 0.35:
                continue
            counts["below035"] += 1
            if min(f.get("line") or 0, g.get("line") or 0) < 1:
                counts["unknown_spans"] += 1
                continue
            ds = {name: float(v[q] @ v[t]) for name, v in dense.items()}
            v = dense["minilm"]
            qa = np.vstack([v[q : q + 1], tv[tailby[q]]])
            ta = np.vstack([v[t : t + 1], tv[tailby[t]]])
            ds["tail"] = float((qa @ ta.T).max()) if tailby[q] or tailby[t] else -1
            if max(ds.values()) < 0.65:
                counts["dense_rejected"] += 1
                continue
            op = max(e["operation_evidence"], key=lambda x: x["score"])
            strength = min(1, op["score"])
            match = []
            for fn, span in [(f, op["query_span"]), (g, op["target_span"])]:
                match.append(
                    {
                        "line": span[0],
                        "end_line": span[1],
                        "coordinates": "native_absolute",
                        "source": "\n".join(fn["code"].splitlines()[span[0] - fn["line"] : span[1] - fn["line"] + 1]),
                    }
                )
            if q not in sparse:
                sparse[q] = dict(idx.similar(bg.documents[q].tokens()))
            order = [i for i in sorted(sparse[q], key=lambda i: (-sparse[q][i], i)) if i != q]
            shared = sorted(set(vectors[q]) & set(vectors[t]))
            rank = order.index(t) + 1 if t in order else None
            emitted.append(
                {
                    "id": "BG-" + digest(cid + ":" + str(q) + ":" + str(t))[:20],
                    "cohort_id": cid,
                    "repository": p["repository"],
                    "revision": p["revision"],
                    "scope": p["scope"],
                    "query_position": q,
                    "target_position": t,
                    "source": {
                        "functions_path": p["functions_path"],
                        "functions_sha256": p["functions_sha256"],
                        "background_sha256": p["background_sha256"],
                        "query": {"source_id": bg.documents[q].id, "source_sha256": digest(f["code"])},
                        "target": {"source_id": bg.documents[t].id, "source_sha256": digest(g["code"])},
                    },
                    "mechanism": {
                        "route": "all-source-native-block",
                        "strength": strength,
                        "region_match": match,
                        "shared_operations": op["shared_operations"],
                        "representation": op["representation"],
                    },
                    "dense": ds,
                    "score": 0.6 * strength + 0.4 * max(ds.values()),
                    "trace": {
                        "tfidf_score": score,
                        "retained_shared_postings": shared,
                        "zero_shared_postings": not shared,
                        "raw_rank_positive_scores_corpus_ties": rank,
                        "default_floor": 0.3 if f["end_line"] - f["line"] + 1 < 6 else 0.5,
                        "balanced_exploration_floor": 0.35,
                        "same_file": f["path"] == g["path"],
                        "first_sparse_loss": "zero_postings" if not shared else "below_score_floor",
                        "funding": "not_yet_evaluated",
                    },
                    "query_in_bank": q in bankqueries,
                    "in_original_bank": None,
                    "ownership": "source region is executable; semantic contract and independent ownership remain source review questions",
                    "provider_outcome": "unknown",
                }
            )
        counts["generated"] = len(emitted)
        counts["queries_outside_bank"] = sum(not r["query_in_bank"] for r in emitted)
        counts["zero_postings"] = sum(r["trace"]["zero_shared_postings"] for r in emitted)
        metric = {
            "cohort_id": cid,
            "status": "complete",
            "repository": p["repository"],
            "counts": dict(counts),
            "source": p,
            "availability": avail,
            "seconds": time.monotonic() - tick,
            "adjacency_sha256": sha(adj),
        }
        write(out / "METRICS.json", metric)
        write(out / "candidates.jsonl", emitted)
        metrics.append(metric)
        allrows += emitted
        print(cid, dict(counts), round(metric["seconds"], 2), flush=True)
    allrows.sort(key=lambda r: (-r["score"], r["id"]))
    write(H / "graph-generated.jsonl", allrows)
    write(
        H / "GRAPH-GENERATION.json",
        {
            "backgrounds": len(metrics),
            "available": sum(m["status"] == "complete" for m in metrics),
            "counts": dict(sum((collections.Counter(m["counts"]) for m in metrics), collections.Counter())),
            "seconds": time.monotonic() - start,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "provider_calls": 0,
            "inference_calls": 0,
        },
    )
    write(H / "graph-coverage.jsonl", metrics)


if __name__ == "__main__":
    main()
