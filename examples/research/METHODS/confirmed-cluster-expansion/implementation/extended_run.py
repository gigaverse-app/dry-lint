# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B023, B904, E401, E402, F401, I001
from status_fields import augment_status

"""Serial, bounded-resource extension of frozen cluster recipe; no providers."""
import os, sys

sys.dont_write_bytecode = True
for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[key] = "2"
import pathlib, json, time, collections, math, resource, subprocess, traceback, shutil, inspect, argparse, fcntl, uuid, functools
import run_cluster as base
from run_cluster import np, sha, digest, canonical, jl, Graph

LAB = pathlib.Path(__file__).resolve().parent
CONTRACT = LAB / "EXTENDED-CONTRACT.json"
EXECUTOR_SHA = sha(__file__)
_EXECUTOR_SNAPSHOT = LAB / "extended/executor-snapshots" / (EXECUTOR_SHA + ".py")
_EXECUTOR_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
if not _EXECUTOR_SNAPSHOT.exists():
    shutil.copyfile(__file__, _EXECUTOR_SNAPSHOT)


def atomic(path, value):
    path = pathlib.Path(path)
    assert path.resolve().is_relative_to(LAB)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w") as f:
        if path.suffix == ".jsonl":
            for row in value:
                f.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
        else:
            json.dump(value, f, sort_keys=True, indent=2, allow_nan=False)
            f.write("\n")
    temp.replace(path)


def stream(path):
    with pathlib.Path(path).open() as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


class ExtendedGraph(Graph):
    def __init__(self, cid):
        super().__init__(cid)
        # Exact immutable source/parser identity: cache native structure hashes,
        # never judgments. Preserve the original native hash implementation.
        for extractor in self.det.extractors:
            original = extractor.structure_hash
            memo = {}

            def cached(function, original=original, memo=memo):
                key = (function.path, function.code)
                if key not in memo:
                    memo[key] = original(function)
                return memo[key]

            extractor.structure_hash = cached
        self.regions = functools.lru_cache(maxsize=16384)(self.regions)

    def build(self):
        if hasattr(self, "built_receipt"):
            return self.built_receipt
        dest = LAB / "graphs" / self.cid
        dest.mkdir(parents=True, exist_ok=True)
        start = time.perf_counter()
        p = self.p
        # The untouched base script binds the recipe. Execution optimizations do not
        # invalidate exact existing graph evidence, and don't change score arithmetic.
        key = canonical({"script": sha(base.__file__), "source": p, "graph_schema": 1})
        rp = dest / "RECEIPT.json"
        if rp.exists():
            receipt = json.loads(rp.read_text())
            if receipt["cache_key"] == key:
                assert sha(dest / "adjacency.jsonl") == receipt["adjacency_sha256"]
                for e in stream(dest / "adjacency.jsonl"):
                    assert e["edge_id"] not in self.edges, "duplicate adjacency row"
                    self.edges[e["edge_id"]] = e
                    self.adj[e["query_position"]][e["target_position"]] = e
                self.finish()
                self.built_receipt = receipt
                self.execution = {"cache_reused": True, "seconds": time.perf_counter() - start}
                return receipt
            raise ValueError("existing graph recipe/source mismatch; refusing overwrite")
        vectors = None
        tail = None
        tailby = collections.defaultdict(list)
        if p.get("minilm_matrix_path"):
            assert sha(p["minilm_matrix_path"]) == p["minilm_matrix_sha256"]
            vectors = np.load(p["minilm_matrix_path"], mmap_mode="r")
            assert vectors.shape == (self.n, 384)
        if p.get("minilm_tail_matrix_path"):
            assert sha(p["minilm_tail_matrix_path"]) == p["minilm_tail_matrix_sha256"]
            views = jl(p["minilm_tail_views_path"])
            vby = {r["position"]: r for r in views}
            with np.load(p["minilm_tail_matrix_path"]) as z:
                tail = z["vectors"].copy()
                owners = z["owners"].astype(int)
                ords = z["ordinals"] if "ordinals" in z.files else [j for v in views for j in range(len(v["views"]))]
                for i, (o, k) in enumerate(zip(owners, ords, strict=True)):
                    v = vby[int(o)]["views"][int(k)]
                    assert digest(v["text"]) == v["input_sha256"]
                    tailby[int(o)].append(i)
            del views, vby
        copies = collections.defaultdict(list)
        for i, f in enumerate(self.fs):
            copies[digest(f.code)].append(i)
        valid = np.asarray(self.valid)
        langs = np.asarray(self.lang)
        ties = np.asarray(self.tie)
        # Same float64 multiply then add in native query-token order; avoid
        # Python per-posting dispatch and sorting scores that will be ranked later.
        postings = {
            tok: (
                np.asarray([i for i, w in entries], dtype=np.int32),
                np.asarray([w for i, w in entries], dtype=np.float64),
            )
            for tok, entries in self.idx.postings.items()
        }
        partial = dest / "adjacency.partial.jsonl"
        progress = dest / "PROGRESS.json"
        done = -1
        if progress.exists():
            state = json.loads(progress.read_text())
            assert state["cache_key"] == key
            done = state["completed_query_position"]
            nbytes = state["committed_bytes"]
            with partial.open("r+b") as f:
                f.truncate(nbytes)
            for e in stream(partial):
                self.edges[e["edge_id"]] = e
                self.adj[e["query_position"]][e["target_position"]] = e
        # Selecting above-floor entries in frozen tie order then stable sorting has
        # exactly the old Python sorted semantics. Dot products remain identical.
        out = partial.open("a")
        try:
            for q in range(done + 1, self.n):
                if not self.valid[q]:
                    continue
                tf = np.zeros(self.n)
                for token, weight in self.idx.vector(self.fs[q].tokens).items():
                    pos, weights = postings[token]
                    tf[pos] += weight * weights
                if q in {0, self.n // 2, self.n - 1}:
                    reference = np.zeros(self.n)
                    for t, value in self.idx.similar(self.fs[q].tokens):
                        reference[t] = value
                    assert np.array_equal(tf, reference), "native sparse accumulation mismatch"
                scores = {"tfidf": tf}
                floors = {"tfidf": 0.35, "minilm_prefix": 0.65, "minilm_tail": 0.8}
                if vectors is not None:
                    scores["minilm_prefix"] = vectors @ vectors[q]
                if tail is not None and vectors is not None:
                    vals = np.full(self.n, -1.0, np.float32)
                    qix = tailby[q]
                    if qix:
                        vals = np.maximum(vals, (vectors @ tail[qix].T).max(axis=1))
                    if len(tail):
                        query = np.vstack([vectors[q], tail[qix]]) if qix else vectors[q : q + 1]
                        np.maximum.at(vals, owners, (tail @ query.T).max(axis=1))
                    scores["minilm_tail"] = vals
                eligible = valid & (langs == langs[q])
                eligible[q] = False
                found = collections.defaultdict(dict)
                for name, values in scores.items():
                    candidates = ties[(eligible & (values >= floors[name]))[ties]]
                    order = candidates[np.argsort(-values[candidates], kind="stable")[:20]]
                    # Check equivalence on fixed positions, including all ties.
                    if q in {0, self.n // 2, self.n - 1}:
                        reference = sorted(
                            (t for t in self.tie if self.eligible(q, t) and values[t] >= floors[name]),
                            key=lambda t: -float(values[t]),
                        )[:20]
                        assert list(order) == reference
                    for rank, t in enumerate(order, 1):
                        found[int(t)][name] = {"score": float(values[t]), "rank": rank}
                for rank, (f, s) in enumerate(
                    self.ops.neighbours(self.fs[q], 64, lambda f: self.eligible(q, self.pos[f.qualname])), 1
                ):
                    found[self.pos[f.qualname]]["operation_block"] = {"score": s, "rank": rank}
                for t in copies[digest(self.fs[q].code)]:
                    if self.eligible(q, t):
                        found[t]["exact_source_copy"] = {"score": 1.0, "rank": 1}
                for t, signals in sorted(found.items()):
                    common = sorted(self.api[q] & self.api[t])
                    rare = [s for s in common if self.df[s] <= max(2, math.ceil(0.05 * self.n))]
                    e = {
                        "schema": 1,
                        "edge_id": self.edge_id(q, t),
                        "cohort_id": self.cid,
                        "query_position": q,
                        "target_position": t,
                        "signals": signals,
                        "operation_evidence": self.regions(q, t) if "operation_block" in signals else [],
                        "shared_api_tokens": common,
                        "rare_shared_api_tokens": rare,
                        "same_file": self.fs[q].path == self.fs[t].path,
                        "weight": sum(
                            1 / (60 + min(v["rank"] for k, v in signals.items() if k in family))
                            for family in [
                                set(signals) & {"tfidf"},
                                set(signals) & {"minilm_prefix", "minilm_tail"},
                                set(signals) & {"operation_block"},
                                set(signals) & {"exact_source_copy"},
                            ]
                            if family
                        ),
                    }
                    self.edges[e["edge_id"]] = e
                    self.adj[q][t] = e
                    out.write(json.dumps(e, sort_keys=True, allow_nan=False) + "\n")
                if q % 256 == 0 or q == self.n - 1:
                    out.flush()
                    atomic(
                        progress,
                        {
                            "cache_key": key,
                            "completed_query_position": q,
                            "committed_bytes": out.tell(),
                            "nodes": self.n,
                            "edges": len(self.edges),
                            "elapsed_seconds": time.perf_counter() - start,
                            "rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                        },
                    )
                    if q % 2048 == 0:
                        print("graph_progress", self.cid, q, self.n, round(time.perf_counter() - start, 1), flush=True)
        finally:
            out.close()
        self.finish()
        partial.replace(dest / "adjacency.jsonl")

        def nodes():
            for i, f in enumerate(self.fs):
                yield {
                    "position": i,
                    "source_id": f.qualname,
                    "source_sha256": digest(f.code),
                    "path": f.path,
                    "line": f.line,
                    "end_line": f.end_line,
                    "source_characters": len(f.code),
                    "source_utf8_bytes": len(f.code.encode()),
                    "native_eligible": self.valid[i],
                    "indegree": self.indegree[i],
                    "hub": i in self.hubs,
                    "scc": int(self.scc[i]),
                    "weak_component": int(self.weak[i]),
                    "operation_regions": [
                        {"line": b.line, "end_line": b.end_line, "kind": b.kind, "tokens": sorted(b.operations)}
                        for b in self.ops._query_blocks(f, fallback=True)
                    ],
                }

        atomic(dest / "nodes.jsonl", nodes())
        receipt = {
            "schema": 1,
            "cache_key": key,
            "product_commit": base.REF,
            "source": p,
            "bank_sha256": self.receipt["bank_sha256"],
            "nodes": self.n,
            "expanded_query_nodes": sum(self.valid),
            "bank_queries": self.receipt["queries"],
            "edges": len(self.edges),
            "hubs": len(self.hubs),
            "scc_scope": "global over retained full-source top20-per-signal graph, not full similarity relation",
            "max_scc": max(collections.Counter(self.scc).values()),
            "max_weak_component": max(collections.Counter(self.weak).values()),
            "seconds": time.perf_counter() - start,
            "adjacency_sha256": sha(dest / "adjacency.jsonl"),
            "label_inputs": [],
            "threads": 2,
            "executor_sha256": EXECUTOR_SHA,
            "executor_snapshot": str(_EXECUTOR_SNAPSHOT),
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        }
        atomic(rp, receipt)
        self.built_receipt = receipt
        self.execution = {"cache_reused": False, "seconds": time.perf_counter() - start}
        return receipt


def freeze_inputs():
    path = LAB / "extended/FROZEN-INPUTS.json"
    if path.exists():
        return json.loads(path.read_text())
    contract = json.loads(CONTRACT.read_text())
    allowed = {r["receipt_source"]["background_sha256"] for r in contract["cohorts"]}
    observations = []
    for folder in ["encoder-judging", "combined-judging", "enablement-judging"]:
        for p in sorted((base.ROOT / ".lab-results" / folder / "physical-account/observations").glob("*.json")):
            x = json.loads(p.read_text())
            if x.get("identity", {}).get("background_sha256") not in allowed:
                continue
            dest = LAB / "extended/observation-snapshot" / folder / p.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dest)
            observations.append({"original": str(p), "snapshot": str(dest), "sha256": sha(dest)})
    inputs = {
        str(base.ROOT / "jobs/cross-repo-recall-audit/.lab-results/inventory-rows.jsonl"): sha(
            base.ROOT / "jobs/cross-repo-recall-audit/.lab-results/inventory-rows.jsonl"
        )
    }
    for c in contract["cohorts"]:
        for name in ["RECEIPT.json", "targets.jsonl", "queries.jsonl"]:
            p = base.BANK / c["cohort_id"] / name
            inputs[str(p)] = sha(p)
    snapshot = {"schema": 1, "base_script_sha256": sha(base.__file__), "inputs": inputs, "observations": observations}
    atomic(path, snapshot)
    return snapshot


def run_one(cid, seen_path):
    resource.setrlimit(resource.RLIMIT_AS, (6 * 1024**3, 6 * 1024**3))
    contract = json.loads(CONTRACT.read_text())
    c = next(c for c in contract["cohorts"] if c["cohort_id"] == cid)
    frozen = json.loads((LAB / "extended/FROZEN-INPUTS.json").read_text())
    assert sha(base.__file__) == frozen["base_script_sha256"]
    for p, h in frozen["inputs"].items():
        if cid in p or "inventory-rows" in p:
            assert sha(p) == h, (p, "changed input")
    out = LAB / "extended" / cid
    out.mkdir(parents=True, exist_ok=True)
    seen = set(json.loads(pathlib.Path(seen_path).read_text()))
    selected_components = set()
    original_targets = base.targets

    def targets(g):
        rows = original_targets(g)
        for r in rows:
            if r["canonical_evaluation"] and r["accepted_gold"] and r["current_label"] in base.USEFUL:
                if r["source_component"] in seen:
                    r["canonical_evaluation"] = False
                else:
                    selected_components.add(r["source_component"])
        return rows

    loader_source = inspect.getsource(base.load_recorded_seeds).replace(
        "ROOT/'.lab-results'/folder/'physical-account/observations'", "LAB/'extended/observation-snapshot'/folder"
    )
    ns = dict(vars(base))
    ns["LAB"] = LAB
    exec(compile(loader_source, "frozen_recorded_seed_loader", "exec"), ns)
    base.load_recorded_seeds = ns["load_recorded_seeds"]
    base.targets = targets
    base.HERE = out
    base.write = atomic
    base.Graph = ExtendedGraph
    base.plan = lambda: [
        {
            "cohort_id": cid,
            "bank_available": True,
            "stage": 2,
            "status": "planned",
            "functions": c["functions"],
            "repository": c["repository"],
            "revision": c["revision"],
        }
    ]
    # Keep exact instantiated graph for baseline/source verification without reindexing.
    captured = {}

    def construct(cid):
        g = ExtendedGraph(cid)
        captured["graph"] = g
        return g

    base.Graph = construct
    start = time.perf_counter()
    base.run(argparse.Namespace(stage="extended", max_cohorts=None))
    g = captured["graph"]
    seeds = jl(out / "seed-exposures.jsonl")
    counts = collections.Counter()
    by_seed = collections.defaultdict(list)
    for p in stream(out / "proposals.jsonl"):
        q, t = p["query_position"], p["target_position"]
        assert p["source_body_sha256"] == [digest(g.fs[q].code), digest(g.fs[t].code)]
        assert p["candidate"]["new"]["code"] == g.fs[q].code and p["candidate"]["existing"]["code"] == g.fs[t].code
        assert not p["reported"] and not p["blocking"] and p["confidence"] is None
        assert p["depth"] <= 2 and all(e in g.edges for e in p["edge_ids"])
        by_seed[p["seed_id"]].append((p["method"], tuple(sorted((q, t)))))
        counts["source_complete_proposals"] += 1
    for s in seeds:
        a, b = s["positions"]
        parent = base.Candidate.model_validate(s["seed_candidate"])
        parent = parent.model_copy(
            update={
                "new": parent.new.model_copy(update={"tokens": g.fs[a].tokens}),
                "existing": parent.existing.model_copy(update={"tokens": g.fs[b].tokens}),
            }
        )
        native = {
            tuple(sorted((g.pos[c.new.qualname], g.pos[c.existing.qualname])))
            for c in g.det.relatives([g.fs[a]], [parent])
        }
        by_method = {m: {p for mm, p in by_seed[s["seed_id"]] if mm == m} for m in base.METHODS}
        assert native == by_method["current_relatives_native"]
        assert all(native <= by_method[m] for m in base.METHODS[2:])
        counts["native_baseline_reexecutions"] += 1
    result = {
        "schema": 1,
        "cohort_id": cid,
        "status": "complete",
        "seconds": time.perf_counter() - start,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "graph_execution": g.execution,
        "selected_components": sorted(selected_components),
        "verification": dict(counts),
        "outputs": {
            f: sha(out / f)
            for f in [
                "RESULTS.json",
                "seed-exposures.jsonl",
                "proposals.jsonl",
                "metrics.jsonl",
                "outcomes.jsonl",
                "frontier-handoff.jsonl",
            ]
        },
        "source": g.p,
        "executor_sha256": EXECUTOR_SHA,
        "executor_snapshot": str(_EXECUTOR_SNAPSHOT),
        "input_seen_components_sha256": sha(seen_path),
    }
    from available_seed import run_for_graph

    run_for_graph(g, out, original_targets)
    atomic(out / "COMPLETE.json", result)


def update_index(contract, attempts):
    index = []
    for c in contract["cohorts"]:
        cid = c["cohort_id"]
        dest = LAB / "graphs" / cid
        rp = dest / "RECEIPT.json"
        r = json.loads(rp.read_text()) if rp.exists() else None
        a = attempts.get(cid, {})
        index.append(
            c
            | {
                "status": "available" if r else a.get("status", "pending"),
                "evaluation_status": a.get("status", "pending"),
                "failure": a.get("error"),
                "adjacency": str(dest / "adjacency.jsonl"),
                "nodes": str(dest / "nodes.jsonl"),
                "receipt": str(rp),
                "adjacency_sha256": r.get("adjacency_sha256") if r else None,
                "scc_scope": "global on retained all-node graph, never equivalence",
                "seed_exposures": str(LAB / "extended" / cid / "seed-exposures.jsonl"),
                "proposals": str(LAB / "extended" / cid / "proposals.jsonl"),
            }
        )
    atomic(
        LAB / "GRAPH-CACHE-INDEX.json",
        {
            "schema": 1,
            "worker": "confirmed-cluster-expansion",
            "consumer": "spectral-family-recovery",
            "ready": sum(x["status"] == "available" for x in index),
            "denominator": 56,
            "cohorts": index,
        },
    )
    atomic(
        LAB / "STATUS.json",
        augment_status(
            LAB,
            {
                "worker": "confirmed-cluster-expansion",
                "stage": "executing extended56",
                "completed": sum(x.get("status") == "complete" for x in attempts.values()),
                "failures": sum(x.get("status") == "failed" for x in attempts.values()),
                "denominator": 56,
                "graph_index": str(LAB / "GRAPH-CACHE-INDEX.json"),
                "provider_calls": 0,
                "limits": contract["limits"],
            },
        ),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohort")
    parser.add_argument("--seen")
    parser.add_argument("--child-token")
    args = parser.parse_args()
    if args.cohort:
        if not args.child_token or args.child_token != (LAB / "extended/active-token").read_text():
            raise RuntimeError("stale runner generation; no cohort execution")
        childlock = (LAB / "extended" / args.cohort / "child.lock").open("w")
        fcntl.flock(childlock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return run_one(args.cohort, args.seen)
    lock = (LAB / "extended/runner.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    previous = LAB / "extended/ATTEMPTS.json"
    if previous.exists():
        archive = LAB / "extended/sweep-history" / f"{sha(previous)}.json"
        archive.parent.mkdir(exist_ok=True)
        if not archive.exists():
            shutil.copyfile(previous, archive)
    token = uuid.uuid4().hex
    (LAB / "extended/active-token").write_text(token)
    contract = json.loads(CONTRACT.read_text())
    freeze_inputs()
    attempts = {}
    seen = set()
    started = time.monotonic()
    for c in contract["cohorts"]:
        cid = c["cohort_id"]
        out = LAB / "extended" / cid
        out.mkdir(parents=True, exist_ok=True)
        seen_path = out / "prior-components.json"
        atomic(seen_path, sorted(seen))
        cp = out / "COMPLETE.json"
        if cp.exists():
            done = json.loads(cp.read_text())
            if done["input_seen_components_sha256"] == sha(seen_path) and (out / "available/COMPLETE.json").exists():
                for f, h in done["outputs"].items():
                    assert sha(out / f) == h
                attempts[cid] = done
                seen.update(done["selected_components"])
                update_index(contract, attempts)
                continue
            cp.rename(out / f"PRIOR-COMPLETE-{done['input_seen_components_sha256'][:12]}.json")
        attempts[cid] = {"status": "running"}
        update_index(contract, attempts)
        print("START", c["order"], cid, c["functions"], flush=True)
        begin = time.monotonic()
        try:
            with (out / "execution.log").open("a") as log:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        str(pathlib.Path(__file__).resolve()),
                        "--cohort",
                        cid,
                        "--seen",
                        str(seen_path),
                        "--child-token",
                        token,
                    ],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                try:
                    code = process.wait(timeout=contract["limits"]["per_cohort_timeout_seconds"])
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    raise TimeoutError("per-cohort wall cap reached; partial adjacency retained")
            if code or not cp.exists():
                raise RuntimeError(f"cohort process exit={code}; see execution.log")
            done = json.loads(cp.read_text())
            attempts[cid] = done
            seen.update(done["selected_components"])
        except Exception as exc:
            attempts[cid] = {
                "cohort_id": cid,
                "status": "failed",
                "error": str(exc),
                "seconds": time.monotonic() - begin,
                "log": str(out / "execution.log"),
            }
            atomic(out / "FAILURE.json", attempts[cid])
        atomic(
            LAB / "extended/ATTEMPTS.json",
            {"schema": 1, "denominator": 56, "attempts": attempts, "seconds": time.monotonic() - started},
        )
        update_index(contract, attempts)
        print("END", cid, attempts[cid]["status"], round(time.monotonic() - begin, 1), flush=True)
    atomic(
        LAB / "extended/ATTEMPTS.json",
        {
            "schema": 1,
            "denominator": 56,
            "attempts": attempts,
            "seconds": time.monotonic() - started,
            "complete_sweep": True,
        },
    )


if __name__ == "__main__":
    main()
