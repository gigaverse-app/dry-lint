# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B007, B023, B905, E401, E402, E741, I001
"""Provider-free sparse graph study. Run with supplied scientific Python."""

from _recovery_paths import recovery_path
import os

for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[k] = "2"
import sys

sys.dont_write_bytecode = True
if hasattr(os, "sched_getaffinity"):
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
import json, pathlib, hashlib, math, collections, time, resource, argparse
import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import connected_components, laplacian
from scipy.sparse.linalg import eigsh, ArpackNoConvergence

H = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path(recovery_path(""))
G = ROOT / "jobs/confirmed-cluster-expansion/.lab-results"
USEFUL = {"duplicate", "drifted", "useful-extractable", "actionable-whole-duplication", "useful-bounded-extraction"}
NEGATIVE = {"separate", "already-shared", "related", "related/too-generic", "tiny-convenience", "tiny"}


def digest(x):
    return hashlib.sha256(x.encode()).hexdigest()


def sha(p):
    with pathlib.Path(p).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def jl(p):
    with pathlib.Path(p).open() as f:
        return [json.loads(l) for l in f if l.strip()]


def write(name, data):
    p = H / name
    p.parent.mkdir(parents=True, exist_ok=True)
    assert p.resolve().is_relative_to(H)
    p.write_text(
        "".join(json.dumps(r, sort_keys=True, allow_nan=False) + "\n" for r in data)
        if p.suffix == ".jsonl"
        else json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )


def matrix(edges, n, mode="mutual", tight=False, remove_hubs=None):
    rows = []
    cols = []
    vals = []
    for e in edges:
        q, t = e["query_position"], e["target_position"]
        if q == t or remove_hubs and (q in remove_hubs or t in remove_hubs):
            continue
        if tight:
            floors = {"tfidf": 0.40, "minilm_prefix": 0.70, "minilm_tail": 0.85}
            signals = {k: v for k, v in e["signals"].items() if k not in floors or v["score"] >= floors[k]}
            if not signals:
                continue
            w = sum(
                1 / (60 + min(signals[k]["rank"] for k in family))
                for family in [
                    set(signals) & {"tfidf"},
                    set(signals) & {"minilm_prefix", "minilm_tail"},
                    set(signals) & {"operation_block"},
                    set(signals) & {"exact_source_copy"},
                ]
                if family
            )
        else:
            w = e["weight"]
        rows.append(q)
        cols.append(t)
        vals.append(w)
    a = sparse.csr_matrix((vals, (rows, cols)), shape=(n, n))
    a = a.minimum(a.T) if mode == "mutual" else a.maximum(a.T)
    a.setdiag(0)
    a.eliminate_zeros()
    a.sort_indices()
    return a


def sweep(a):
    """Minimum-conductance Fiedler sweep, with both sides at least three."""
    n = a.shape[0]
    if n < 6:
        return None
    d = np.asarray(a.sum(axis=1)).ravel()
    if np.any(d <= 0):
        return None
    try:
        vals, vec = eigsh(
            laplacian(a, normed=True), k=2, which="SM", v0=np.linspace(0.3, 1.3, n), tol=1e-6, maxiter=3000
        )
    except ArpackNoConvergence:
        return {"failure": "arpack_nonconvergence"}
    idx = np.argsort(vals)
    v = vec[:, idx[1]] / np.sqrt(d)
    order = np.lexsort((np.arange(n), v))
    inside = np.zeros(n, bool)
    cut = 0.0
    volume = 0.0
    total = float(d.sum())
    best = None
    for j, u in enumerate(order[:-1], 1):
        neighbors = a.indices[a.indptr[u] : a.indptr[u + 1]]
        weights = a.data[a.indptr[u] : a.indptr[u + 1]]
        cut += float(d[u]) - 2 * float(weights[inside[neighbors]].sum())
        volume += float(d[u])
        inside[u] = True
        if j < 3 or n - j < 3:
            continue
        phi = max(0.0, cut) / min(volume, total - volume)
        if best is None or phi < best["conductance"] - 1e-12:
            best = {
                "conductance": phi,
                "ncut": max(0.0, cut) * (1 / volume + 1 / (total - volume)),
                "left": sorted(map(int, order[:j])),
                "lambda2": float(vals[idx[1]]),
            }
    return best


def perturb(a, ids):
    coo = sparse.triu(a, k=1).tocoo()
    values = []
    for i, j, w in zip(coo.row, coo.col, coo.data):
        u, v = sorted((int(ids[i]), int(ids[j])))
        r = int(digest(f"{u}:{v}")[:8], 16) / (2**32 - 1)
        values.append(w * (0.95 + 0.10 * r))
    out = sparse.csr_matrix((values, (coo.row, coo.col)), shape=a.shape)
    return out + out.T


def partition(a):
    start = time.perf_counter()
    cuts = []
    leaves = []

    def rec(ids, depth):
        if len(ids) < 6 or depth >= 4:
            leaves.append(ids)
            return
        local = a[ids][:, ids].tocsr()
        num, cc = connected_components(local, directed=False)
        if num > 1:
            for label in range(num):
                rec(ids[cc == label], depth)
            return
        result = sweep(local)
        row = {"nodes": len(ids), "depth": depth, "members_sha256": digest(str(ids.tolist()))}
        if result is None or "failure" in result:
            cuts.append(row | {"accepted": False, "reason": (result or {}).get("failure", "too_small")})
            leaves.append(ids)
            return
        left = set(result["left"])
        trial = None
        agreement = None
        if result["conductance"] <= 0.20:
            trial = sweep(perturb(local, ids))
            if trial and "left" in trial:
                alt = set(trial["left"])
                agreement = max(
                    len(left & alt) + len((set(range(len(ids))) - left) & (set(range(len(ids))) - alt)),
                    len(left - alt) + len(alt - left),
                ) / len(ids)
        accept = bool(agreement is not None and agreement >= 0.90 and trial["conductance"] <= 0.20)
        cuts.append(
            row
            | {k: v for k, v in result.items() if k != "left"}
            | {
                "accepted": accept,
                "stability_agreement": agreement,
                "perturbed_conductance": trial.get("conductance") if trial else None,
            }
        )
        if accept:
            mask = np.array([i in left for i in range(len(ids))])
            rec(ids[mask], depth + 1)
            rec(ids[~mask], depth + 1)
        else:
            leaves.append(ids)

    count, labels = connected_components(a, directed=False)
    for c in range(count):
        rec(np.flatnonzero(labels == c), 0)
    out = np.empty(a.shape[0], dtype=int)
    for i, ids in enumerate(leaves):
        out[ids] = i
    return {
        "labels": out.tolist(),
        "cuts": cuts,
        "seconds": time.perf_counter() - start,
        "components": int(count),
        "leaves": len(leaves),
        "accepted_cuts": sum(r["accepted"] for r in cuts),
        "edges": a.nnz // 2,
        "isolates": int(np.sum(np.asarray(a.sum(axis=1)).ravel() == 0)),
        "sparse_bytes": a.data.nbytes + a.indices.nbytes + a.indptr.nbytes,
    }


def groups_for(seed, nodes, edges, allowed_tokens=None):
    """A single common signature must occur within each member's one source region."""
    a, b = seed
    df = collections.Counter(
        t for node in nodes for t in set(t for r in node["operation_regions"] for t in r["tokens"])
    )
    allowed = (
        set(allowed_tokens) if allowed_tokens is not None else {t for e in edges for t in e["rare_shared_api_tokens"]}
    )
    threshold = max(2, math.ceil(0.05 * len(nodes)))
    signatures = set()
    for x in nodes[a]["operation_regions"]:
        for y in nodes[b]["operation_regions"]:
            sig = frozenset(t for t in set(x["tokens"]) & set(y["tokens"]) & allowed if df[t] <= threshold)
            if len(sig) >= 2 and any(t.startswith(("call:", "attr:")) for t in sig):
                signatures.add(sig)
    out = []
    for sig in sorted(signatures, key=lambda s: (-len(s), sorted(s))):
        members = []
        for i, node in enumerate(nodes):
            spans = [
                {"line": r["line"], "end_line": r["end_line"], "kind": r["kind"]}
                for r in node["operation_regions"]
                if sig <= set(r["tokens"])
            ]
            if spans:
                members.append({"position": i, "spans": spans})
        out.append(
            {
                "signature": sorted(sig),
                "members": members,
                "authority": "common bounded-region retrieval tokens, NOT reviewed same-operation truth",
                "group_id": digest(json.dumps(sorted(sig)))[:16],
            }
        )
    return out


def toy():
    # Source-backed, hand-constructed affinity controls. Weights intentionally model
    # two operation families and a function containing BOTH fragments, not empirical similarity.
    page = """def page(client, cursor):\n    result = client.fetch_page(cursor)\n    while result.next_cursor:\n        yield from result.items\n        result = client.fetch_page(result.next_cursor)\n"""
    retry = """def retry(client, tries):\n    for attempt in range(tries):\n        try:\n            return client.send_request()\n        except TransientError:\n            sleep(backoff(attempt))\n"""
    nodes = []
    truth = []
    sources = []

    def region(sig, start=1):
        return {"line": start, "end_line": start + 4, "kind": "synthetic_complete_operation", "tokens": sig}

    pg = ["call:fetch_page", "attr:next_cursor"]
    rt = ["call:send_request", "call:backoff"]
    for i in range(4):
        nodes.append({"operation_regions": [region(pg)]})
        truth.append({"pagination"})
        sources.append(page.replace("def page", "def page" + str(i)))
    for i in range(4):
        nodes.append({"operation_regions": [region(rt)]})
        truth.append({"retry"})
        sources.append(retry.replace("def retry", "def retry" + str(i)))
    nodes.append({"operation_regions": [region(pg), region(rt, 7)]})
    truth.append({"pagination", "retry"})
    sources.append(
        "def mixed(client, cursor, tries):\n"
        + "\n".join(page.splitlines()[1:])
        + "\n"
        + "\n".join(retry.splitlines()[1:])
        + "\n"
    )
    for i in range(8):
        nodes.append({"operation_regions": [region(["call:log", "attr:status"])]})
        truth.append(set())
        sources.append("def boilerplate():\n    log(status)\n")
    nodes.append({"operation_regions": []})
    truth.append(set())
    sources.append("def isolated():\n    return 7\n")
    n = len(nodes)
    weights = {}
    for family in [range(4), range(4, 8)]:
        for i in family:
            for j in family:
                if i < j:
                    weights[i, j] = 1.0
            weights[min(i, 8), max(i, 8)] = 0.20
    for i in range(9):
        weights[i, 9] = 0.01
    for i in range(9, 17):
        for j in range(i + 1, 17):
            weights[i, j] = 0.8
    a = sparse.lil_matrix((n, n))
    for (i, j), w in weights.items():
        a[i, j] = a[j, i] = w
    a = a.tocsr()
    part = partition(a)
    groups = groups_for((0, 1), nodes, [], pg + rt)
    # Toy rarity threshold relaxed only by adding 100 isolated no-evidence controls,
    # preserving the production 5% criterion. No forced graph edges.
    extra = [{"operation_regions": []} for _ in range(100)]
    groups = groups_for((0, 1), nodes + extra, [], pg + rt)
    retrygroups = groups_for((4, 5), nodes + extra, [], pg + rt)
    pset = {r["position"] for g in groups for r in g["members"]}
    rset = {r["position"] for g in retrygroups for r in g["members"]}
    assert pset == {0, 1, 2, 3, 8} and rset == {4, 5, 6, 7, 8}
    assert 8 in pset & rset and not groups_for((0, 4), nodes + extra, [], pg + rt)
    after = list(nodes) + extra
    after[2] = {"operation_regions": []}
    assert 2 not in {r["position"] for g in groups_for((0, 1), after, [], pg + rt) for r in g["members"]}
    assert part["accepted_cuts"] > 0 and part["labels"][17] != part["labels"][0]
    # Dense generic clique: no useful low-conductance split is manufactured.
    clique = sparse.csr_matrix(np.ones((12, 12)) - np.eye(12))
    cliquep = partition(clique)
    assert cliquep["accepted_cuts"] == 0
    labels = part["labels"]
    region = {i for i, x in enumerate(labels) if x in {labels[0], labels[1]}} - {0, 1}
    rows = []
    for method, got in [
        ("broad_component", set(range(17)) - {0, 1}),
        ("spectral_region", region),
        ("overlap_same_signature", pset - {0, 1}),
    ]:
        rows.append(
            {
                "method": method,
                "lead_nodes": len(got),
                "useful": len(got & {2, 3, 8}),
                "useful_denominator": 3,
                "unrelated": len(got - {2, 3, 8}),
                "operation_purity": len(got & {2, 3, 8}) / len(got) if got else None,
                "positions": sorted(got),
            }
        )
    write(
        "TOY.json",
        {
            "schema": 1,
            "authority": "synthetic mechanistic truth, not real code-graph generalization",
            "partition": part,
            "comparisons": rows,
            "pagination_members": sorted(pset),
            "retry_members": sorted(rset),
            "bridge_overlaps": sorted(pset & rset),
            "false_seed_groups": 0,
            "after_shared_wrapper_omitted": True,
            "generic_clique_accepted_cuts": 0,
            "sources": sources,
            "rare_token_control_padding_isolates": 100,
            "edge_weights": [[i, j, w] for (i, j), w in weights.items()],
        },
    )
    print("toy passed", rows, flush=True)


def pair(r):
    return tuple(sorted((r["query_position"], r["target_position"])))


def run(graph_root):
    start = time.perf_counter()
    cpu = time.process_time()
    sources = []
    allpart = {}
    group_rows = []
    queues = []
    queue_records = []
    metrics = []
    seeds = list({r["seed_id"]: r for r in jl(graph_root / "seed-exposures.jsonl")}.values())
    props = jl(graph_root / "proposals.jsonl")
    by = collections.defaultdict(list)
    for r in props:
        if r["method"] in {"bounded_seed_diffusion", "current_relatives_native", "unseeded_changed_endpoint"}:
            by[r["seed_id"], r["method"]].append(r)
    plan = json.loads((H / "CONTINUATION.json").read_text())["cohorts"]
    cids = [p["cohort_id"] for p in plan if (graph_root / "graphs" / p["cohort_id"] / "RECEIPT.json").exists()]
    for cid in cids:
        print("partition", cid, flush=True)
        folder = graph_root / "graphs" / cid
        receipt = json.loads((folder / "RECEIPT.json").read_text())
        p = receipt["source"]
        assert not any(x in p["repository"].lower() for x in ["opencode", "firecrawl", "curator"])
        assert sha(folder / "adjacency.jsonl") == receipt["adjacency_sha256"]
        for name in ("functions", "background"):
            assert sha(p[name + "_path"]) == p[name + "_sha256"]
        nodes = jl(folder / "nodes.jsonl")
        functions = jl(p["functions_path"])
        edges = jl(folder / "adjacency.jsonl")
        n = len(nodes)
        for node, f in zip(nodes, functions, strict=True):
            assert node["source_sha256"] == digest(f["code"])
        variants = {}
        for name, mode, tight, hub in [
            ("mutual", "mutual", False, None),
            ("union", "union", False, None),
            ("tight_mutual", "mutual", True, None),
            ("without_hubs", "mutual", False, {r["position"] for r in nodes if r["hub"]}),
        ]:
            variants[name] = partition(matrix(edges, n, mode, tight, hub))
        allpart[cid] = variants
        write("partitions/" + cid + ".json", variants)
        sources.append(
            {
                "cohort_id": cid,
                "source": p,
                "graph_receipt_sha256": sha(folder / "RECEIPT.json"),
                "adjacency_sha256": sha(folder / "adjacency.jsonl"),
                "nodes_sha256": sha(folder / "nodes.jsonl"),
                "nodes": n,
                "variants": {
                    k: {
                        f: v[f]
                        for f in [
                            "components",
                            "leaves",
                            "edges",
                            "accepted_cuts",
                            "isolates",
                            "seconds",
                            "sparse_bytes",
                        ]
                    }
                    for k, v in variants.items()
                },
            }
        )
        for seed in [s for s in seeds if s["cohort_id"] == cid]:
            tick = time.perf_counter()
            sid = seed["seed_id"]
            a, b = seed["positions"]
            native = list({pair(r): r for r in by[sid, "current_relatives_native"]}.values())
            diff = list({pair(r): r for r in by[sid, "bounded_seed_diffusion"]}.values())
            nativekeys = {pair(r) for r in native}
            groups = groups_for((a, b), nodes, edges)
            membership = collections.defaultdict(list)
            for group in groups:
                group_rows.append(group | {"seed_id": sid, "cohort_id": cid, "seed_positions": [a, b]})
                for member in group["members"]:
                    membership[member["position"]].append(group["group_id"])

            def is_member(r):
                return bool(
                    membership[r["query_position"]]
                    and set(membership[r["query_position"]]) & set(membership[r["target_position"]])
                )

            def inside(r, variant):
                lab = variants[variant]["labels"]
                return lab[r["target_position"]] in {lab[a], lab[b]}

            def protect(rows):
                return native + [r for r in rows if pair(r) not in nativekeys]

            arms = {
                "current_relatives_native": native,
                "bounded_seed_diffusion": diff,
                "cheap_onehop": protect(list({pair(r): r for r in by[sid, "unseeded_changed_endpoint"]}.values())),
                "operation_only_ranking": protect(sorted(diff, key=lambda r: not is_member(r))),
                "spectral_overlap_ranking": protect(
                    sorted(diff, key=lambda r: (not is_member(r), not inside(r, "mutual")))
                ),
            }
            for variant in ["mutual", "union", "tight_mutual", "without_hubs"]:
                arms["spectral_region_" + variant] = protect([r for r in diff if inside(r, variant)])
            for method, rs in arms.items():
                for rank, r in enumerate(rs, 1):
                    groupids = sorted(set(membership[r["query_position"]]) & set(membership[r["target_position"]]))
                    queues.append(
                        {
                            "seed_id": sid,
                            "cohort_id": cid,
                            "method": method,
                            "rank": rank,
                            "proposal_id": r["proposal_id"],
                            "pair": list(pair(r)),
                            "group_ids": groupids,
                        }
                    )
                    if method == "spectral_overlap_ranking":
                        queue_records.append(
                            r
                            | {
                                "spectral_method": method,
                                "spectral_rank": rank,
                                "common_operation_group_ids": groupids,
                                "spectral_in_seed_region": inside(r, "mutual"),
                                "spectral_contract_sha256": sha(H / "SPECTRAL-CONTRACT.json"),
                                "review_status": "unverified_nonblocking",
                                "funding": {"executed": False, "physical_usd": 0, "real_004_reporting": False},
                                "same_operation_confirmed": False,
                            }
                        )
            seed["_arms"] = arms
            seed["_rank_seconds"] = time.perf_counter() - tick
            seed["_functions"] = functions
        print("complete", cid, {k: v["accepted_cuts"] for k, v in variants.items()}, flush=True)
    # Freeze queues BEFORE reading outcomes. Labels never enter the above computation.
    write("queues.jsonl", queues)
    write("operation-groups.jsonl", group_rows)
    write("ranked-leads.jsonl", queue_records)
    write("SOURCE-MATRIX.json", sources)
    outcome_rows = jl(graph_root / "outcomes.jsonl")
    outcomes = {r["proposal_id"]: r["labels"] for r in outcome_rows}
    oldmetrics = {(r["seed_id"], r["method"]): r for r in jl(graph_root / "metrics.jsonl")}
    inventory = (
        jl(graph_root / "CONTROL-INVENTORY.jsonl")
        if (graph_root / "CONTROL-INVENTORY.jsonl").exists()
        else jl(G / "CONTROL-INVENTORY.jsonl")
    )
    useful_components = collections.defaultdict(set)
    # Inventory is pinned development data from the graph worker; do not transfer revisions.
    for r in inventory:
        if r["cohort_id"] not in cids:
            continue
        if r.get("label") in USEFUL:
            useful_components[r["cohort_id"], r.get("source_component") or r.get("family_component")].add(
                tuple(sorted(r["query_positions"]))
            )
    for seed in seeds:
        if "_arms" not in seed:
            continue
        a, b = seed["positions"]
        nativekeys = {pair(r) for r in seed["_arms"]["current_relatives_native"]}
        funcs = seed["_functions"]
        sid = seed["seed_id"]
        # Same conditional denominator as published graph worker; exact pair membership
        # is joined from outcomes of reached leads, never a ranking feature.
        denominator = oldmetrics[sid, "bounded_seed_diffusion"]["conditional_sibling_recall_denominator"]
        for method, rows in seed["_arms"].items():
            for cap in [3, 10, 20, None]:
                rs = rows if cap is None else rows[:cap]
                used = {a, b}
                counts = collections.Counter()
                got = set()
                knownsiblings = set()
                bytes_code = 0
                bytes_context = 0
                categories = collections.Counter()
                for r in rs:
                    labs = outcomes[r["proposal_id"]]
                    labels = {l["label"] for l in labs}
                    categories.update(labels)
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
                    got.add(pair(r))
                    if state == "known_useful" and any(
                        l.get("source_component") == seed.get("source_component") and l["label"] in USEFUL for l in labs
                    ):
                        knownsiblings.add(pair(r))
                    for pos in {r["query_position"], r["target_position"]} - used:
                        bytes_code += len(funcs[pos]["code"].encode())
                        bytes_context += len(funcs[pos].get("context", "").encode())
                    used |= {r["query_position"], r["target_position"]}
                metrics.append(
                    {
                        "seed_id": sid,
                        "source_component": seed.get("source_component"),
                        "cohort_id": seed["cohort_id"],
                        "seed_mode": seed["seed_mode"],
                        "seed_lane": seed["lane"],
                        "method": method,
                        "cap": cap,
                        "leads": len(rs),
                        **{k: counts[k] for k in ["known_useful", "known_negative", "unknown", "other"]},
                        "conditional_recall_numerator": len(knownsiblings),
                        "conditional_recall_denominator": denominator,
                        "source_tokens_proxy": math.ceil(bytes_code / 4),
                        "context_tokens_proxy": math.ceil(bytes_context / 4),
                        "lost_native_pairs": len(nativekeys - got),
                        "label_categories": dict(categories),
                        "ranking_seconds_shared_all_arms": seed["_rank_seconds"],
                    }
                )
    groups = collections.defaultdict(list)
    for m in metrics:
        groups[m["seed_mode"], m["seed_lane"], m["method"], m["cap"]].append(m)
    summary = []
    for (mode, lane, method, cap), ms in groups.items():
        summary.append(
            {
                "seed_mode": mode,
                "seed_lane": lane,
                "method": method,
                "cap": cap,
                "scenarios": len(ms),
                "independent_source_components": len({m["source_component"] for m in ms}),
                **{
                    k: sum(m[k] for m in ms)
                    for k in [
                        "leads",
                        "known_useful",
                        "known_negative",
                        "unknown",
                        "other",
                        "conditional_recall_numerator",
                        "conditional_recall_denominator",
                        "source_tokens_proxy",
                        "context_tokens_proxy",
                        "lost_native_pairs",
                    ]
                },
            }
        )
    frontier = {}
    for r in queue_records:
        if (
            r["seed_mode"] != "false_seed_control"
            and all(l["label"] == "unknown" for l in outcomes[r["proposal_id"]])
            and r["incremental_vs_current_relatives"]
        ):
            frontier.setdefault((r["cohort_id"], pair(r)), r)
    write("frontier-handoff.jsonl", list(frontier.values()))
    write("metrics.jsonl", metrics)
    write(
        "RESULTS.json",
        {
            "schema": 1,
            "summary": summary,
            "cohorts": len(sources),
            "seed_scenarios": len({s["seed_id"] for s in seeds}),
            "seconds": time.perf_counter() - start,
            "cpu_seconds": time.process_time() - cpu,
            "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
            "provider_calls": 0,
            "physical_usd": 0,
            "real_004_reporting": "not executed; root owned",
            "source_frontier_pairs": len(frontier),
            "operation_group_count": len(group_rows),
            "operation_family_purity_real": None,
            "script_sha256": sha(__file__),
            "queue_sha256_before_outcome_join": sha(H / "queues.jsonl"),
            "graph_input": str(graph_root),
            "numpy": np.__version__,
            "reused_graph_build_seconds": sum(
                json.loads((graph_root / "graphs" / p["cohort_id"] / "RECEIPT.json").read_text())["seconds"]
                for p in sources
            ),
        },
    )
    write(
        "STATUS.json",
        {
            "schema": 1,
            "stage": "executed spectral milestone; validation pending",
            "cohorts": len(sources),
            "pending_available": 56 - len(sources),
            "provider_calls": 0,
            "physical_usd": 0,
            "frontier_pairs": len(frontier),
            "decision": "iterate; no product promotion",
            "no_holdout_opened": True,
            "coordinator_delivery": "tool approval policy never blocked message; local handoff available",
        },
    )
    print("DONE", len(metrics), "metrics", len(frontier), "frontier", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--toy-only", action="store_true")
    ap.add_argument("--graph-root", type=pathlib.Path, default=H / "inputs")
    ap.add_argument("--output-dir", type=pathlib.Path)
    args = ap.parse_args()
    if args.output_dir:
        assert args.output_dir.resolve().is_relative_to(H)
        H = args.output_dir.resolve()
        H.mkdir(parents=True, exist_ok=True)
    toy()
    if not args.toy_only:
        run(args.graph_root)
