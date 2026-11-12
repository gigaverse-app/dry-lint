# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B023, E741, F403, F405
"""One frozen SVD cache and one regularized weighting; no decomposition fitting."""

from spectral import *


def main():
    start = time.perf_counter()
    data = json.loads((H / "tfidf-vectors.json").read_text())
    contract = json.loads((H / "SVD-CONTRACT.json").read_text())
    path = pathlib.Path(contract["cache"])
    identity = json.loads(pathlib.Path(contract["cache_identity"]).read_text())
    assert sha(path) == identity["artifact_sha256"]
    ii = []
    jj = []
    vv = []
    for r in data["rows"]:
        for j, v in r["vector"]:
            ii.append(r["position"])
            jj.append(j)
            vv.append(v)
    X = sparse.csr_matrix((vv, (ii, jj)), shape=data["shape"])
    cache = np.load(path)
    V = cache["components"]
    singular = cache["singular"]
    P = X @ V.T
    energy = np.einsum("ij,ij->i", P, P)
    original = np.asarray(X.multiply(X).sum(axis=1)).ravel()
    assert np.allclose(original[original > 0], 1)

    def normalize(z):
        return z / np.maximum(np.linalg.norm(z, axis=1)[:, None], 1e-30)

    Z = normalize(P)
    assert np.allclose(Z, cache["Z"], atol=1e-10)
    assert np.allclose(V @ V.T, np.eye(64), atol=1e-10)
    tau = float(np.median(singular**2))
    R = normalize(P / np.sqrt(singular**2 + tau))
    cid = contract["cohort_id"]
    I = H / "inputs"
    props = jl(I / "proposals.jsonl")
    seed_rows = list({s["seed_id"]: s for s in jl(I / "seed-exposures.jsonl") if s["cohort_id"] == cid}.values())
    queues = []
    rank_rows = []
    by = collections.defaultdict(list)
    for r in props:
        if r["cohort_id"] == cid:
            by[r["seed_id"], r["method"]].append(r)
    nodes = jl(I / "graphs" / cid / "nodes.jsonl")
    valid = np.array([r["native_eligible"] for r in nodes])
    lookup = {r["source_id"]: i for i, r in enumerate(data["rows"])}
    ids = [r["source_id"] for r in data["rows"]]
    arms = {
        "lsi64_cosine": Z,
        "lsi64_projected_dot": P,
        "ridge_whiten_energy": R,
        "raw_tfidf": None,
        "soft_residual_half": None,
    }
    for s in seed_rows:
        sid = s["seed_id"]
        native = list({pair(r): r for r in by[sid, "current_relatives_native"]}.values())
        nativekeys = {pair(r) for r in native}
        diff = list({pair(r): r for r in by[sid, "bounded_seed_diffusion"]}.values())
        for method, embedding in arms.items():

            def score(r):
                a, b = r["query_position"], r["target_position"]
                if method == "raw_tfidf":
                    return float(X[a].multiply(X[b]).sum())
                if method == "soft_residual_half":
                    return (0.5 * float(X[a].multiply(X[b]).sum()) + 0.5 * float(P[a] @ P[b])) / math.sqrt(
                        (0.5 + 0.5 * energy[a]) * (0.5 + 0.5 * energy[b])
                    )
                v = float(embedding[a] @ embedding[b])
                return v * math.sqrt(energy[a] * energy[b]) if method == "ridge_whiten_energy" else v

            def supported(r):
                return (
                    len(r["operation_identity"]["anchor_api_tokens"]) >= 2
                    or r["source_body_sha256"][0] == r["source_body_sha256"][1]
                )

            ordered = native + sorted(
                [r for r in diff if pair(r) not in nativekeys],
                key=lambda r: (not supported(r), -score(r) if supported(r) else 0),
            )
            for rank, r in enumerate(ordered, 1):
                queues.append(
                    {
                        "seed_id": sid,
                        "method": method,
                        "rank": rank,
                        "proposal_id": r["proposal_id"],
                        "score": score(r),
                        "source_supported": supported(r),
                        "energy_query": float(energy[r["query_position"]]),
                        "energy_target": float(energy[r["target_position"]]),
                    }
                )
        # Distinct diagnostic: ranks of supplied seed pairs among source-resolved rows.
        a, b = s["positions"]
        for q, t in [(a, b), (b, a)]:
            for method, embedding in {"raw_tfidf": None, **arms}.items():
                scores = (X @ X[q].T).toarray().ravel() if embedding is None else embedding @ embedding[q]
                if method == "ridge_whiten_energy":
                    scores = scores * np.sqrt(energy[q] * energy)
                if method == "soft_residual_half":
                    scores = (0.5 * scores + 0.5 * (P @ P[q])) / np.sqrt((0.5 + 0.5 * energy[q]) * (0.5 + 0.5 * energy))
                candidates = [i for i in range(len(ids)) if i != q and valid[i]]
                order = sorted(candidates, key=lambda i: (-float(scores[i]), ids[i], i))
                rank_rows.append(
                    {
                        "seed_id": sid,
                        "seed_mode": s["seed_mode"],
                        "seed_lane": s["lane"],
                        "method": method,
                        "query": q,
                        "target": t,
                        "rank": order.index(t) + 1,
                        "score": float(scores[t]),
                        "interpretation": "supplied seed-pair rank, not sibling discovery or new outcome",
                    }
                )
    write("SVD-queues.jsonl", queues)
    write("SVD-seed-ranks.jsonl", rank_rows)
    # Only now join sibling outcomes; labels never entered matrix or score construction.
    out = {r["proposal_id"]: r["labels"] for r in jl(I / "outcomes.jsonl")}
    prop = {r["proposal_id"]: r for r in props}
    seeds = {s["seed_id"]: s for s in seed_rows}
    funcs = jl(data["source"]["functions_path"])
    metrics = []
    for (sid, method), rs in (
        (key, [r for r in queues if (r["seed_id"], r["method"]) == key])
        for key in sorted((s["seed_id"], method) for s in seed_rows for method in arms)
    ):
        s = seeds[sid]
        for cap in [3, 10, 20, None]:
            picked = rs if cap is None else rs[:cap]
            counts = collections.Counter()
            used = set(s["positions"])
            sourcebytes = contextbytes = 0
            for row in picked:
                p = prop[row["proposal_id"]]
                labels = {x["label"] for x in out[row["proposal_id"]]}
                state = (
                    "known_useful"
                    if labels & USEFUL
                    else "known_negative"
                    if labels & NEGATIVE
                    else "unknown"
                    if labels == {"unknown"}
                    else "other"
                )
                counts[state] += 1
                for t in {p["query_position"], p["target_position"]} - used:
                    sourcebytes += len(funcs[t]["code"].encode())
                    contextbytes += len(funcs[t].get("context", "").encode())
                used |= {p["query_position"], p["target_position"]}
            metrics.append(
                {
                    "seed_id": sid,
                    "seed_mode": s["seed_mode"],
                    "seed_lane": s["lane"],
                    "method": method,
                    "cap": cap,
                    "leads": len(picked),
                    "source_tokens_proxy": math.ceil(sourcebytes / 4),
                    "context_tokens_proxy": math.ceil(contextbytes / 4),
                    **{k: counts[k] for k in ["known_useful", "known_negative", "unknown", "other"]},
                }
            )
    # Compare the very same scenario subset against earlier graph cuts/cheap ranking.
    metrics += [r for r in jl(H / "metrics.jsonl") if r["cohort_id"] == cid]
    grouped = collections.defaultdict(list)
    for r in metrics:
        grouped[r["seed_mode"], r["seed_lane"], r["method"], r["cap"]].append(r)
    summary = []
    for (mode, lane, method, cap), rs in grouped.items():
        summary.append(
            {
                "seed_mode": mode,
                "seed_lane": lane,
                "method": method,
                "cap": cap,
                "scenarios": len(rs),
                **{
                    k: sum(r[k] for r in rs)
                    for k in [
                        "leads",
                        "known_useful",
                        "known_negative",
                        "unknown",
                        "other",
                        "source_tokens_proxy",
                        "context_tokens_proxy",
                    ]
                },
            }
        )
    cases = []
    for q, t in [
        (
            "tests/sdk/conversation/test_fifo_lock.py::test_fifo_lock_context_manager",
            "openhands/sdk/conversation/fifo_lock.py::FIFOLock.__enter__",
        ),
        (
            "openhands/agent_server/bash_service.py::BashEventService.search_bash_events",
            "openhands/agent_server/event_service.py::EventService.search_events",
        ),
    ]:
        a, b = lookup[q], lookup[t]
        raw = float(X[a].multiply(X[b]).sum())
        dot = float(P[a] @ P[b])
        cases.append(
            {
                "query": q,
                "target": t,
                "positions": [a, b],
                "energy_query": float(energy[a]),
                "energy_target": float(energy[b]),
                "raw_cosine": raw,
                "projected_dot": dot,
                "lsi_cosine": float(Z[a] @ Z[b]),
                "ridge_whiten_energy": float(R[a] @ R[b]) * math.sqrt(energy[a] * energy[b]),
                "soft_residual_half": (0.5 * raw + 0.5 * dot)
                / math.sqrt((0.5 + 0.5 * energy[a]) * (0.5 + 0.5 * energy[b])),
                "discarded_inner_product": raw - dot,
                "source_body_sha256": [data["rows"][i]["source_sha256"] for i in [a, b]],
                "label": "not inferred from projection",
            }
        )
    assert abs(cases[0]["lsi_cosine"] - 0.9138066903585003) < 1e-8 and cases[0]["raw_cosine"] == 0
    assert all(
        {r["proposal_id"] for r in queues if r["seed_id"] == s["seed_id"] and r["method"] == "lsi64_cosine"}
        == {r["proposal_id"] for r in queues if r["seed_id"] == s["seed_id"] and r["method"] == "ridge_whiten_energy"}
        for s in seed_rows
    )
    write(
        "SVD-RESULTS.json",
        {
            "schema": 1,
            "cohort_id": cid,
            "cache_sha256": sha(path),
            "contract_sha256": sha(H / "SVD-CONTRACT.json"),
            "cache_reconstruction_max_abs_error": float(np.max(np.abs(Z - cache["Z"]))),
            "fitted_new_decompositions": 0,
            "regularization_tau": tau,
            "matrix_shape": X.shape,
            "matrix_nonzeros": X.nnz,
            "energy_quantiles": {str(p): float(np.quantile(energy, p)) for p in [0.0, 0.1, 0.5, 0.9, 1.0]},
            "global_retained_energy": float(energy.sum() / original.sum()),
            "randomized_singular_energy_fraction": float((singular**2).sum() / original.sum()),
            "seconds": time.perf_counter() - start,
            "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
            "summary": summary,
            "examples": cases,
            "provider_calls": 0,
            "new_source_confirmed_operations": 0,
            "funded_reports": None,
            "seed_count": len(seed_rows),
            "interpretation": "Exact single-cohort fixed-pool complementary ranking; no new sibling truth, no generalization or noise-removal guarantee",
        },
    )
    print(
        "SVD control complete",
        len(seed_rows),
        "seed scenarios; global energy",
        energy.sum() / original.sum(),
        flush=True,
    )


if __name__ == "__main__":
    main()
