# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B023, E401, E402, F401, F821, I001
"""Bounded structural + cached dense recovery. Never reads outcomes or label values."""

from _recovery_paths import recovery_path
import os

os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[k] = "2"
import sys

sys.dont_write_bytecode = True
import pathlib, json, hashlib, collections, ast, textwrap, time, resource, copy

H = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path(recovery_path(""))
BANK = ROOT / "jobs/complementary-signal-learning/.lab-results"
BASE = ROOT / "jobs/encoder-corpus-evaluation/.lab-results"
sys.path.insert(0, str(BANK))
from build_bank import sha, digest, jl, write, Function, REF
from dry_lint.operation_blocks import _regions, _representations
from dry_lint.bench_background import BenchBackground
import numpy as np

RULE = {
    "schema": 1,
    "version": "structural-dense-v1",
    "product_commit": REF,
    "population": "56 development backgrounds, every source function is a normalized-region query against its own unchanged full background; bank-block route separately marked",
    "signals": [
        "native guarded operation-blocks:2",
        "exact alpha-normalized complete Python AST regions + preserved literals/operators/def-use",
        "cached dense prefix/tail and source-exact CodeRank/Gemma pair corroboration",
    ],
    "weak": "raw cosine < .35; zero postings computed from full frozen index, not bank shared_tokens",
    "bounds": {
        "regions_per_function": 12,
        "min_nodes": 25,
        "max_nodes": 400,
        "min_calls": 2,
        "max_posting_parents": 64,
        "max_structural_targets_per_query": 64,
    },
    "dense_gate": 0.65,
    "ranking": "0.6 * structural_strength + 0.4 * max_available_dense; structural_strength native block score or min(1,normalized_region_nodes/100); ties exact source body hash",
    "unsupported": "Normalized structural route Python only; no inferred TS AST equivalence",
    "exclusions": "No resolved forwarding exemption override. Unknown ownership remains unknown.",
    "budgets": {
        "normal_each_arm": 0.04,
        "native_each_arm": 0.04,
        "physical_research_ceiling": 1.25,
        "provider_owner": "root",
    },
    "labels": "No labels, reference-pairs or inventory rows opened by generator; join after freezing generation",
    "reserved": ["anomalyco/opencode", "firecrawl", "curator"],
}


class Alpha(ast.NodeTransformer):
    def __init__(self):
        self.names = {}
        self.attrs = {}
        self.keys = {}

    def norm(self, d, s, p):
        if s not in d:
            d[s] = p + str(len(d))
        return d[s]

    def visit_Name(self, n):
        return ast.copy_location(ast.Name(id=self.norm(self.names, n.id, "v"), ctx=n.ctx), n)

    def visit_Attribute(self, n):
        self.generic_visit(n)
        n.attr = self.norm(self.attrs, n.attr, "a")
        return n

    def visit_keyword(self, n):
        self.generic_visit(n)
        n.arg = self.norm(self.keys, n.arg, "k") if n.arg else None
        return n

    def visit_arg(self, n):
        n.arg = self.norm(self.names, n.arg, "v")
        n.annotation = None
        return n


def representations(code):
    try:
        tree = ast.parse(textwrap.dedent(code))
        root = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
    except (SyntaxError, StopIteration, ValueError):
        return []
    result = []
    for kind, stmts in _regions(root.body):
        module = ast.Module(body=stmts, type_ignores=[])
        nodes = list(ast.walk(module))
        if not 25 <= len(nodes) <= 400 or sum(isinstance(n, ast.Call) for n in nodes) < 2:
            continue
        if any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)) for n in nodes):
            continue
        if not 4 <= stmts[-1].end_lineno - stmts[0].lineno + 1 <= 80:
            continue
        sig = ast.dump(Alpha().visit(copy.deepcopy(module)), include_attributes=False)
        loads = sorted({n.id for n in nodes if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)})
        stores = sorted({n.id for n in nodes if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)})
        calls = [ast.unparse(n.func) for n in nodes if isinstance(n, ast.Call)]
        result.append(
            {
                "signature": digest(sig),
                "line": stmts[0].lineno,
                "end_line": stmts[-1].end_lineno,
                "nodes": len(nodes),
                "kind": kind,
                "inputs": sorted(set(loads) - set(stores)),
                "assigned": stores,
                "returns": sum(isinstance(n, (ast.Return, ast.Yield)) for n in nodes),
                "calls": calls,
                "source": "\n".join(textwrap.dedent(code).splitlines()[stmts[0].lineno - 1 : stmts[-1].end_lineno]),
            }
        )
    return sorted(result, key=lambda r: (-r["nodes"], r["line"], r["signature"]))[:12]


def matrix_receipts():
    found = collections.defaultdict(list)
    for name in ["coderank-cpu-evaluation", "gemma-cpu-evaluation"]:
        base = ROOT / "jobs" / name / ".lab-results"
        # Metadata only; never traverse/read held-out source or outcomes.
        for f in sorted(base.rglob("matrix-4096.json")):
            if "bf60fb3615061d02" in str(f) or "faef200af37c7cb5" in str(f):
                continue
            r = json.loads(f.read_text())
            if r.get("repository") == "anomalyco/opencode":
                continue
            if r.get("ready") and r.get("document_matrix_path"):
                found[r["cohort_id"]].append((f, r))
    return found


def main():
    start = time.monotonic()
    write(H / "RECIPE.json", RULE)
    receipts = json.loads((BANK / "BANK-MANIFEST.json").read_text())["backgrounds"]
    cache = {}
    metrics = []
    allrows = []
    matrices = matrix_receipts()
    inputs = [
        ROOT / "reports/utility-recovery/ADOPTION-CONTRACT.md",
        ROOT / "jobs/cross-repo-recall-audit/.lab-results/SPLIT-CONTRACT.json",
        BANK / "BANK-CONTRACT.json",
        BANK / "bank_loader.py",
        ROOT / "jobs/confirmed-cluster-expansion/.lab-results/GRAPH-CACHE-INDEX.json",
    ]
    write(
        H / "INPUTS.json",
        {
            "files": [{"path": str(f), "sha256": sha(f)} for f in inputs],
            "runtime": str(BASE / "runtime/src"),
            "python": sys.version,
            "threads": 2,
            "rule_sha256": sha(H / "RECIPE.json"),
        },
    )
    for receipt in receipts:
        p = receipt["source"]
        cid = p["cohort_id"]
        if p["repository"] == "anomalyco/opencode":
            continue
        dest = H / "generation" / cid
        if (dest / "METRICS.json").exists():
            metrics.append(json.loads((dest / "METRICS.json").read_text()))
            allrows += jl(dest / "candidates.jsonl")
            continue
        tick = time.monotonic()
        assert not any(x in p["repository"].lower() for x in ["firecrawl", "curator"])
        assert sha(p["functions_path"]) == p["functions_sha256"] and sha(p["background_path"]) == p["background_sha256"]
        fs = jl(p["functions_path"])
        bg = BenchBackground.decode(pathlib.Path(p["background_path"]).read_bytes())
        idx = bg.index()
        bankpath = BANK / "deterministic-v2/bank" / cid / "candidates.jsonl"
        rows = jl(bankpath)
        queries = sorted({r["query_position"] for r in rows})
        bankby = {(r["query_position"], r["target_position"]): r for r in rows}
        opps = {}
        counts = collections.Counter()
        counts["bank_rows"] = len(rows)
        counts["queries"] = len(queries)
        counts["functions"] = len(fs)
        for r in rows:
            f = r["features"]
            if not r["native_eligible"]:
                counts["structural_scope_excluded"] += 1
                continue
            if f["tfidf_score"] < 0.35:
                counts["below035_bank"] += 1
                if f["block_score"] > 0:
                    counts["native_block_below035"] += 1
                    opps[(r["query_position"], r["target_position"])] = {
                        "route": "native-block",
                        "strength": f["block_score"],
                        "region_match": None,
                    }
        regs = []
        post = collections.defaultdict(list)
        for i, f in enumerate(fs):
            code = f["code"]
            key = digest(code)
            if not str(f["path"]).endswith(".py"):
                rs = []
            else:
                if key not in cache:
                    cache[key] = representations(code)
                rs = cache[key]
            regs.append(rs)
            for sig in {r["signature"] for r in rs}:
                post[sig].append(i)
        counts["normalized_regions"] = sum(map(len, regs))
        counts["common_signature_rejected"] = sum(len(v) > 64 for v in post.values())
        sparse = {}
        vectors = {}

        def sparse_score(q, t):
            for i in (q, t):
                if i not in vectors:
                    vectors[i] = idx.vector(bg.documents[i].tokens())
            return sum(vectors[q][k] * vectors[t].get(k, 0) for k in sorted(vectors[q]))

        for q in range(len(fs)):
            for a in regs[q]:
                targets = post[a["signature"]]
                if len(targets) > 64:
                    continue
                for t in targets:
                    if t == q or fs[q]["path"] == fs[t]["path"] and fs[q]["name"] == fs[t]["name"]:
                        continue
                    if sparse_score(q, t) >= 0.35:
                        continue
                    counts["normalized_weak_occurrences"] += 1
                    b = next(x for x in regs[t] if x["signature"] == a["signature"])
                    key = (q, t)
                    strength = min(1, a["nodes"] / 100)
                    if key not in opps or strength > opps[key]["strength"]:
                        opps[key] = {"route": "normalized-region", "strength": strength, "region_match": [a, b]}
        # Bound each source query before inspecting dense scores or labels.
        grouped = collections.defaultdict(list)
        for key, e in opps.items():
            grouped[key[0]].append((key, e))
        opps = {
            key: e
            for q, items in grouped.items()
            for key, e in sorted(items, key=lambda x: (-x[1]["strength"], x[0][1]))[:64]
        }
        counts["all_source_queries"] = len(fs)
        counts["structural_query_candidates"] = len(grouped)
        counts["bounded_structural_pairs"] = len(opps)
        dense = {}
        availability = {}
        assert sha(p["minilm_matrix_path"]) == p["minilm_matrix_sha256"]
        vec = np.load(p["minilm_matrix_path"], mmap_mode="r")
        dense["minilm"] = vec
        availability["minilm"] = {
            "available": True,
            "path": p["minilm_matrix_path"],
            "sha256": p["minilm_matrix_sha256"],
        }
        assert sha(p["minilm_tail_matrix_path"]) == p["minilm_tail_matrix_sha256"]
        z = np.load(p["minilm_tail_matrix_path"])
        tv = z["vectors"]
        owners = z["owners"]
        tailby = collections.defaultdict(list)
        for i, owner in enumerate(owners):
            tailby[int(owner)].append(i)
        availability["tail"] = {
            "available": True,
            "path": p["minilm_tail_matrix_path"],
            "sha256": p["minilm_tail_matrix_sha256"],
        }
        for fp, m in matrices.get(cid, []):
            if (
                m.get("functions_sha256") != p["functions_sha256"]
                or m.get("background_sha256") != p["background_sha256"]
            ):
                continue
            assert sha(m["document_matrix_path"]) == m["document_matrix_sha256"]
            name = "coderank" if "coderank" in str(fp) else "gemma"
            dense[name] = np.load(m["document_matrix_path"], mmap_mode="r")
            availability[name] = {
                "available": True,
                "receipt": str(fp),
                "receipt_sha256": sha(fp),
                "method": m["method"],
                "path": m["document_matrix_path"],
                "sha256": m["document_matrix_sha256"],
            }
        for name in ["coderank", "gemma"]:
            availability.setdefault(
                name, {"available": False, "reason": "no exact full-background 4096 matrix receipt found; no inference"}
            )
        emitted = []
        for (q, t), e in sorted(opps.items()):
            f, g = fs[q], fs[t]
            if not f.get("line") or not g.get("line") or f["line"] < 1 or g["line"] < 1:
                counts["unknown_source_span"] += 1
                continue
            score = sparse_score(q, t)
            br = bankby.get((q, t))
            scores = {name: float(v[q] @ v[t]) for name, v in dense.items()}
            qa = np.vstack([vec[q : q + 1], tv[tailby[q]]])
            ta = np.vstack([vec[t : t + 1], tv[tailby[t]]])
            scores["tail"] = float((qa @ ta.T).max()) if tailby[q] or tailby[t] else -1
            counts["structural_weak_pairs"] += 1
            if max(scores.values()) < 0.65:
                counts["dense_gate_rejected"] += 1
                continue
            if q not in sparse:
                sparse[q] = dict(idx.similar(bg.documents[q].tokens()))
            left = idx.vector(bg.documents[q].tokens())
            right = idx.vector(bg.documents[t].tokens())
            shared = sorted(set(left) & set(right))
            rawsorted = sorted(sparse[q], key=lambda i: (-sparse[q][i], i))
            rawsorted = [i for i in rawsorted if i != q]
            rank = rawsorted.index(t) + 1 if t in rawsorted else None
            if e["route"] == "native-block":
                af = Function.model_validate(f)
                bf = Function.model_validate(g)
                aa, ah = _representations(af)
                bb, bh = _representations(bf)
                ar = aa + ([ah] if ah else [])
                bs = bb + ([bh] if bh else [])
                matches = []
                for a in ar:
                    for b in bs:
                        ops = sorted(a.operations & b.operations)
                        calls = sorted(a.calls & b.calls)
                        if len(ops) >= 3 and len(calls) >= 2:
                            matches.append((len(ops), a, b, ops, calls))
                if matches:
                    _, a, b, ops, calls = max(matches, key=lambda x: x[0])
                    e["region_match"] = [
                        {
                            "line": x.line,
                            "end_line": x.end_line,
                            "source": "\n".join(
                                fn["code"].splitlines()[x.line - fn["line"] : x.end_line - fn["line"] + 1]
                            ),
                            "calls": sorted(x.calls),
                            "operations": sorted(x.operations),
                            "coordinates": "native_absolute",
                        }
                        for x, fn in [(a, f), (b, g)]
                    ]
                    e["shared_operations"] = ops
                    e["shared_calls"] = calls
            row = {
                "id": "BS-" + digest(cid + ":" + str(q) + ":" + str(t))[:20],
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
                "mechanism": e,
                "dense": scores,
                "score": 0.6 * e["strength"] + 0.4 * max(scores.values()),
                "trace": {
                    "tfidf_score": score,
                    "retained_shared_postings": shared,
                    "zero_shared_postings": not shared,
                    "raw_rank_positive_scores_corpus_ties": rank,
                    "bank_raw_rank": br["features"]["tfidf_rank"] if br else None,
                    "default_floor": 0.3 if f["end_line"] - f["line"] + 1 < 6 else 0.5,
                    "balanced_exploration_floor": 0.35,
                    "same_file": f["path"] == g["path"],
                    "first_sparse_loss": "zero_postings" if not shared else "below_score_floor",
                    "funding": "not_yet_evaluated",
                },
                "query_in_bank": q in queries,
                "in_original_bank": br is not None,
                "ownership": "independent executable regions; resolved sharing and semantic input/output contract require source review",
                "provider_outcome": "unknown",
            }
            emitted.append(row)
        counts["generated"] = len(emitted)
        counts["zero_postings"] = sum(r["trace"]["zero_shared_postings"] for r in emitted)
        counts["outside_bank"] = sum(not r["in_original_bank"] for r in emitted)
        metric = {
            "cohort_id": cid,
            "repository": p["repository"],
            "revision": p["revision"],
            "scope": p["scope"],
            "counts": dict(counts),
            "availability": availability,
            "seconds": time.monotonic() - tick,
            "source": p,
            "bank_sha256": sha(bankpath),
            "rule_sha256": sha(H / "RECIPE.json"),
        }
        write(dest / "candidates.jsonl", emitted)
        write(dest / "METRICS.json", metric)
        metrics.append(metric)
        allrows += emitted
        write(
            H / "PROGRESS.json",
            {"complete": len(metrics), "planned": 56, "generated": len(allrows), "provider_calls": 0},
        )
        print(cid, dict(counts), "seconds", round(metric["seconds"], 2), flush=True)
        del fs, rows, bankby, bg, idx, vec, tv, z, dense, regs, post, sparse
    allrows.sort(key=lambda r: (-r["score"], r["id"]))
    write(H / "generated.jsonl", allrows)
    write(
        H / "GENERATION.json",
        {
            "schema": 1,
            "backgrounds": len(metrics),
            "counts": dict(sum((collections.Counter(m["counts"]) for m in metrics), collections.Counter())),
            "seconds": time.monotonic() - start,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "provider_calls": 0,
            "inference_calls": 0,
            "recipe_sha256": sha(H / "RECIPE.json"),
            "generated_sha256": sha(H / "generated.jsonl"),
        },
    )
    write(H / "coverage.jsonl", metrics)


if __name__ == "__main__":
    main()
