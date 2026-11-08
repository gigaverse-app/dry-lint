# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B023, E401, E402, E741, F841, I001
"""Provider-free full-background retrieval. All output stays beside this script.
Two CPU threads; immutable source/cache bindings; no model inference.
"""

from _recovery_paths import recovery_path
import os

for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[key] = "2"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
import sys, pathlib, json, hashlib, time, collections, platform, resource

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path(recovery_path(""))
BASE = ROOT / "jobs/encoder-corpus-evaluation/.lab-results"
SRC = BASE / "runtime/src"
sys.path.insert(0, str(SRC))
import numpy as np
from dry_lint.models import Function
from dry_lint.bench_background import BenchBackground
from dry_lint.operation_blocks import OperationBlocksComparer

REF = "a10a288530c4aa25711c7ec3b86ac164d182899a"


def sha(p):
    with pathlib.Path(p).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def digest(s):
    return hashlib.sha256(s.encode()).hexdigest()


def jl(p):
    import gzip

    with gzip.open(p, "rt") if str(p).endswith(".gz") else open(p) as f:
        return [json.loads(l) for l in f if l.strip()]


def write(p, x):
    p = pathlib.Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    temp = p.with_suffix(p.suffix + ".tmp")
    temp.write_text(
        ("".join(json.dumps(r, sort_keys=True, allow_nan=False) + "\n" for r in x))
        if p.suffix == ".jsonl"
        else json.dumps(x, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    temp.replace(p)


def rank(scores, tie, q, eligible=None, valid=None):
    order = tie[np.argsort(-scores[tie], kind="stable")]
    order = order[order != q]
    if eligible is not None:
        order = order[eligible[order]]
    if valid is not None:
        order = order[valid[order]]
    ranks = np.full(len(scores), len(scores) + 1, np.int32)
    ranks[order] = np.arange(1, len(order) + 1)
    return ranks, order


def run(limit=58):
    started = time.monotonic()
    plan = json.loads((BASE / "ordered-full-background-plan.json").read_text())["plan"][:limit]
    panels = {p["cohort_id"]: p for p in jl(BASE / "panels.jsonl")}
    overrides = json.loads((BASE / "baseline-matrices.json").read_text())
    maps = jl(BASE / "mapped-gold.jsonl")
    chosen = {}
    for step in plan:
        for rid in step["new_rows"]:
            chosen.setdefault(rid, step["cohort_id"])
    write(
        HERE / "FROZEN-INPUTS.json",
        {
            "schema": 1,
            "product_commit": REF,
            "worktree_head": "b74a6223b4b41b8bb881c445c86c2dba82d62dd2",
            "product_src": str(SRC),
            "python": platform.python_version(),
            "numpy": np.__version__,
            "threads": 2,
            "plan": plan,
            "inputs": {
                str(BASE / f): sha(BASE / f)
                for f in [
                    "panels.jsonl",
                    "mapped-gold.jsonl",
                    "ordered-full-background-plan.json",
                    "baseline-matrices.json",
                ]
            },
            "input_panels": [{**panels[p["cohort_id"]], **overrides.get(p["cohort_id"], {})} for p in plan],
            "script_sha256": sha(__file__),
            "target_selection": "all mapped function endpoints per background; canonical evaluation row chosen by first plan new_rows assignment",
            "source_labels_used_for_generation": False,
        },
    )
    receipts = []
    for step in plan:
        cid = step["cohort_id"]
        p = {**panels[cid], **overrides.get(cid, {})}
        dest = HERE / "bank" / cid
        if (dest / "RECEIPT.json").exists():
            receipt = json.loads((dest / "RECEIPT.json").read_text())
            assert receipt["script_sha256"] == sha(__file__)
            receipts.append(receipt)
            continue
        tick = time.monotonic()
        assert "firecrawl" not in p["repository"].lower() and "curator" not in p["repository"].lower()
        assert sha(p["functions_path"]) == p["functions_sha256"] and sha(p["background_path"]) == p["background_sha256"]
        raw = jl(p["functions_path"])
        docs = jl(p["documents_path"])
        bg = BenchBackground.decode(pathlib.Path(p["background_path"]).read_bytes())
        idx = bg.index()
        fs = []
        for f, d, doc in zip(raw, bg.documents, docs, strict=True):
            unit = Function.model_validate(f if f.get("line") is not None else f | {"line": 0, "end_line": -1})
            assert (
                unit.qualname == d.id == doc["source_id"]
                and digest(unit.code) == d.source_sha256 == doc["source_sha256"]
            )
            unit.tokens = d.tokens()
            fs.append(unit)
        n = len(fs)
        identities = [f.qualname for f in fs]
        amb = {k for k, v in collections.Counter(identities).items() if v > 1}
        tie = np.array(sorted(range(n), key=lambda i: (docs[i]["source_id"], docs[i]["source_sha256"], i)))
        paths = np.array([f.path for f in fs])
        langs = np.array(
            [f.analysis.language if f.analysis else ("python" if f.path.endswith(".py") else "typescript") for f in fs]
        )
        known = np.array([f.line > 0 and f.qualname not in amb for f in fs])
        lengths = np.array([len(f.code) for f in fs])
        lines = np.array([max(0, f.end_line - f.line + 1) for f in fs])
        vectors = None
        if p.get("minilm_matrix_path"):
            assert sha(p["minilm_matrix_path"]) == p["minilm_matrix_sha256"]
            vectors = np.load(p["minilm_matrix_path"], mmap_mode="r", allow_pickle=False)
            assert (
                vectors.shape == (n, 384)
                and np.isfinite(vectors).all()
                and np.max(np.abs(np.linalg.norm(vectors, axis=1) - 1)) < 1e-4
            )
        tailvectors = None
        owners = None
        tailby = {}
        if p.get("minilm_tail_matrix_path"):
            assert sha(p["minilm_tail_matrix_path"]) == p["minilm_tail_matrix_sha256"]
            views = jl(p["minilm_tail_views_path"])
            vby = {r["position"]: r for r in views}
            with np.load(p["minilm_tail_matrix_path"], allow_pickle=False) as z:
                tailvectors = z["vectors"].copy()
                owners = z["owners"].astype(np.int32)
                ords = (
                    z["ordinals"]
                    if "ordinals" in z.files
                    else np.array([j for r in views for j in range(len(r["views"]))])
                )
                for ix, (owner, ordinal) in enumerate(zip(owners, ords, strict=True)):
                    view = vby[int(owner)]["views"][int(ordinal)]
                    assert digest(view["text"]) == view["input_sha256"]
                    tailby.setdefault(int(owner), []).append(ix)
                assert tailvectors.shape == (len(owners), 384) and np.isfinite(tailvectors).all()
        blocks = OperationBlocksComparer()
        blocks.index(fs)
        positions = {id(f): i for i, f in enumerate(fs)}
        # Reuse frozen IDF, without refitting a selected-candidate corpus.
        tokens = [set(t for t in f.tokens if not t.startswith(("fn:", "ctl:")) and t in idx.idf) for f in fs]
        api = [{t for t in ts if t.startswith(("call:", "attr:", "key:"))} for ts in tokens]
        contracts = [{t for t in f.tokens if t.startswith(("ctl:", "key:"))} for f in fs]
        masses = np.array([sum(idx.idf[t] for t in ts) for ts in tokens])
        post = collections.defaultdict(list)
        for i, ts in enumerate(tokens):
            for tok in ts:
                post[tok].append(i)
        post = {t: np.array(v, np.int32) for t, v in post.items()}
        targets = [
            r | {"canonical_evaluation": chosen.get(r["row_id"]) == cid}
            for r in maps
            if r["cohort_id"] == cid and r["record_kind"] == "function"
        ]
        queries = sorted({i for r in targets for i in r["query_positions"]})
        setup = time.monotonic() - tick
        dest.mkdir(parents=True, exist_ok=True)
        write(dest / "targets.jsonl", targets)
        out = (dest / "candidates.jsonl.tmp").open("w")
        goldrows = []
        queryrows = []
        total = 0
        for q in queries:
            native = known & (langs == langs[q]) & np.array([name != fs[q].qualname for name in identities])
            native &= known[q]
            cross = (paths != paths[q]) & (langs == langs[q])
            scores = {}
            tf = np.zeros(n, np.float64)
            for i, s in idx.similar(bg.documents[q].tokens()):
                tf[i] = s
            scores["tfidf"] = tf
            if vectors is not None:
                scores["minilm"] = vectors @ vectors[q]
            if tailvectors is not None and vectors is not None:
                tail = np.full(n, -1.0, np.float32)
                qix = tailby.get(q, [])
                if qix:
                    tail = np.maximum(tail, (vectors @ tailvectors[qix].T).max(axis=1))
                if len(tailvectors):
                    qvec = np.vstack([vectors[q], tailvectors[qix]]) if qix else vectors[q : q + 1]
                    np.maximum.at(tail, owners, (tailvectors @ qvec.T).max(axis=1))
                scores["tail"] = tail
            block = np.zeros(n, np.float64)
            for f, s in blocks.neighbours(fs[q], 64, lambda f: f.qualname != fs[q].qualname):
                block[positions[id(f)]] = s
            scores["block"] = block
            shared = np.zeros(n, np.int32)
            ashared = np.zeros(n, np.int32)
            mass = np.zeros(n, np.float64)
            for tok in tokens[q]:
                ii = post[tok]
                shared[ii] += 1
                mass[ii] += idx.idf[tok]
                if tok in api[q]:
                    ashared[ii] += 1
            containment = np.divide(
                mass, np.minimum(masses, masses[q]), out=np.zeros(n), where=np.minimum(masses, masses[q]) > 0
            )
            scores["containment"] = containment
            contain_ok = (shared >= 8) & (ashared >= 3) & (containment >= 0.75) & (tf >= 0.1)
            ranks = {}
            orders = {}
            xranks = {}
            xorders = {}
            pool = set()
            for name, score in scores.items():
                valid = (
                    (block > 0)
                    if name == "block"
                    else contain_ok
                    if name == "containment"
                    else (score >= 0)
                    if name == "tail"
                    else None
                )
                ranks[name], orders[name] = rank(score, tie, q, valid=valid)
                xranks[name], xorders[name] = rank(score, tie, q, eligible=cross, valid=valid)
                pool.update(map(int, orders[name][:100]))
                pool.update(map(int, xorders[name][:100]))
                if name in ["block", "containment"]:
                    pool.update(map(int, orders[name]))
            fusion = 1 / (60 + ranks["tfidf"]).astype(float)
            if "minilm" in ranks:
                fusion += 1 / (60 + ranks["minilm"])
            # Embedding views share one evidence family, do not count as independent votes.
            dense_rank = np.minimum(ranks.get("minilm", np.full(n, n + 1)), ranks.get("tail", np.full(n, n + 1)))
            dense_rr = np.maximum(
                1 / (60 + ranks.get("minilm", np.full(n, n + 1))),
                np.where(scores.get("tail", np.full(n, -1)) >= 0.8, 1 / (60 + ranks.get("tail", np.full(n, n + 1))), 0),
            )
            conditional = (
                1 / (60 + ranks["tfidf"])
                + dense_rr
                + np.where(block > 0, 1 / (60 + ranks["block"]), 0)
                + np.where(contain_ok, 1 / (60 + ranks["containment"]), 0)
            )
            # Conditional routes are evidence thresholds, not per-route funded slots.
            routed = (
                (tf >= 0.35)
                | (block > 0)
                | contain_ok
                | (scores.get("tail", np.full(n, -1)) >= 0.8)
                | (scores.get("minilm", np.full(n, -1)) >= 0.65)
            )
            for name, value in [("fixed_fusion", fusion), ("conditional", conditional)]:
                ranks[name], orders[name] = rank(value, tie, q, valid=routed if name == "conditional" else None)
                xranks[name], xorders[name] = rank(
                    value, tie, q, eligible=cross, valid=routed if name == "conditional" else None
                )
                pool.update(map(int, orders[name][:100]))
                pool.update(map(int, xorders[name][:100]))
            for t in sorted(pool, key=lambda i: (docs[i]["source_id"], docs[i]["source_sha256"], i)):
                assert t != q
                c_union = contracts[q] | contracts[t]
                c_inter = contracts[q] & contracts[t]
                feature = {
                    **{name + "_score": float(val[t]) for name, val in scores.items()},
                    **{name + "_rank": int(val[t]) for name, val in ranks.items()},
                    **{name + "_cross_rank": int(val[t]) for name, val in xranks.items()},
                    "minilm_available": vectors is not None,
                    "tail_available": tailvectors is not None,
                    "block_supported": langs[q] == "python" and langs[t] == "python",
                    "shared_tokens": int(shared[t]),
                    "shared_api_tokens": int(ashared[t]),
                    "shared_idf_mass": float(mass[t]),
                    "contract_jaccard": len(c_inter) / len(c_union) if c_union else 0.0,
                    "contract_available": bool(c_union),
                    "length_ratio": float(min(lengths[q], lengths[t]) / max(1, lengths[q], lengths[t])),
                    "query_lines": int(lines[q]),
                    "target_lines": int(lines[t]),
                    "same_file": bool(paths[q] == paths[t]),
                    "same_language": bool(langs[q] == langs[t]),
                    "same_name": fs[q].name == fs[t].name,
                    "forwarding_target_new": fs[q].analysis.forward_target if fs[q].analysis else None,
                    "forwarding_target_existing": fs[t].analysis.forward_target if fs[t].analysis else None,
                    "direct_call_name_overlap": ("call:" + fs[t].name) in fs[q].tokens
                    or ("call:" + fs[q].name) in fs[t].tokens,
                }
                row = {
                    "schema": 1,
                    "candidate_id": digest(f"{cid}:{q}:{t}"),
                    "cohort_id": cid,
                    "repository": p["repository"],
                    "revision": p["revision"],
                    "query_position": q,
                    "target_position": t,
                    "source": {
                        "functions_path": p["functions_path"],
                        "functions_sha256": p["functions_sha256"],
                        "background_sha256": p["background_sha256"],
                        "query": docs[q],
                        "target": docs[t],
                    },
                    "features": feature,
                    "routes": {
                        "tfidf": bool(tf[t] >= 0.35),
                        "block": bool(block[t] > 0),
                        "containment": bool(contain_ok[t]),
                        "minilm": float(scores.get("minilm", np.full(1, -1))[t if vectors is not None else 0]) >= 0.65,
                        "tail": float(scores["tail"][t]) >= 0.8 if "tail" in scores else False,
                        "conditional": bool(routed[t]),
                    },
                    "scores": {
                        "tfidf": float(tf[t]),
                        "fixed_fusion": float(fusion[t]),
                        "conditional": float(conditional[t]) if routed[t] else None,
                    },
                    "native_eligible": bool(native[t]),
                }
                out.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
                total += 1
            for r in targets:
                if q not in r["query_positions"]:
                    continue
                t = r["query_positions"][1] if q == r["query_positions"][0] else r["query_positions"][0]
                goldrows.append(
                    {
                        **r,
                        "query_position": q,
                        "target_position": t,
                        "in_bank": t in pool,
                        "native_eligible": bool(native[t]),
                        "same_file": bool(paths[q] == paths[t]),
                        "same_language": bool(langs[q] == langs[t]),
                        "ranks": {k: int(v[t]) for k, v in ranks.items()},
                        "cross_ranks": {k: (int(v[t]) if cross[t] else None) for k, v in xranks.items()},
                        "scores": {k: float(v[t]) for k, v in scores.items()},
                    }
                )
            queryrows.append(
                {
                    "query_position": q,
                    "bank_size": len(pool),
                    "full_competitors": n - 1,
                    "conditional_candidates": int(np.count_nonzero(routed & native)),
                    "guarded_block_matches": int(np.count_nonzero(block)),
                    "containment_matches": int(np.count_nonzero(contain_ok)),
                }
            )
        out.close()
        (dest / "candidates.jsonl.tmp").replace(dest / "candidates.jsonl")
        write(dest / "target-ranks.jsonl", goldrows)
        write(dest / "queries.jsonl", queryrows)
        receipt = {
            "cohort_id": cid,
            "repository": p["repository"],
            "revision": p["revision"],
            "scope": p["scope"],
            "functions": n,
            "queries": len(queries),
            "candidate_rows": total,
            "setup_seconds": setup,
            "seconds": time.monotonic() - tick,
            "minilm": vectors is not None,
            "tail": tailvectors is not None,
            "source": p,
            "script_sha256": sha(__file__),
            "bank_sha256": sha(dest / "candidates.jsonl"),
            "bank_bytes": (dest / "candidates.jsonl").stat().st_size,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "label_free_generation": True,
        }
        write(dest / "RECEIPT.json", receipt)
        receipts.append(receipt)
        write(
            HERE / "BANK-MANIFEST.json",
            {
                "complete": len(receipts) == len(plan),
                "planned_backgrounds": len(plan),
                "backgrounds": receipts,
                "seconds": time.monotonic() - started,
            },
        )
        write(
            HERE / "STATUS.json",
            {
                "title": "Broad complementary discovery from exact-source cached signals",
                "stage": "Building candidate bank",
                "measured_coverage": {
                    "backgrounds": len(receipts),
                    "planned": len(plan),
                    "queries": sum(r["queries"] for r in receipts),
                    "candidate_rows": sum(r["candidate_rows"] for r in receipts),
                    "provider_calls": 0,
                },
                "next_artifact": "Complete bank, grouped residual ranking and blind frontier",
            },
        )
        print(cid, n, len(queries), total, round(time.monotonic() - tick, 2), flush=True)
    import shutil

    with (HERE / "candidates.jsonl.tmp").open("wb") as out:
        for r in receipts:
            with (HERE / "bank" / r["cohort_id"] / "candidates.jsonl").open("rb") as f:
                shutil.copyfileobj(f, out)
    (HERE / "candidates.jsonl.tmp").replace(HERE / "candidates.jsonl")
    print("COMPLETE", len(receipts), round(time.monotonic() - started, 2), flush=True)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=58)
    args = ap.parse_args()
    run(args.limit)
