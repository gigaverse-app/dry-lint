# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, E402, F401, I001
"""Independent frozen TF-IDF/MiniLM reference; no fitting, encoding or providers."""

import os

for k in ["OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"]:
    os.environ[k] = "2"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
import argparse, collections, hashlib, json, pathlib, sys, time
from inventory import HERE, ROOT, BASE, jl, sha, write

PIN = BASE / "runtime/src"
sys.path.insert(0, str(PIN))
import numpy as np
from dry_lint.bench_background import BenchBackground

CAPS = [1, 3, 4, 10, 50, 100]


def rank(scores, ties, mask):
    order = ties[np.argsort(-scores[ties], kind="stable")]
    order = order[mask[order]]
    ranks = np.full(len(scores), len(scores) + 1, dtype=np.int32)
    ranks[order] = np.arange(1, len(order) + 1)
    return ranks, order


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=pathlib.Path, default=HERE / "reference")
    ap.add_argument("--panel")
    a = ap.parse_args()
    a.out.mkdir(exist_ok=True, parents=True)
    inv = jl(HERE / "inventory-rows.jsonl")
    maps = jl(BASE / "mapped-gold.jsonl")
    panels = jl(HERE / "frozen-panels.jsonl")
    byrow = {r["row_id"]: r for r in inv}
    contract = json.loads((HERE / "SPLIT-CONTRACT.json").read_text())
    assert sha(HERE / "inventory-rows.jsonl") == contract["inventory_rows_sha256"]
    bypanel = collections.defaultdict(list)
    for m in maps:
        r = byrow[m["row_id"]]
        if (
            r["wave_role"] == "development"
            and r["canonical_cohort"] == m["cohort_id"]
            and m["record_kind"] == "function"
        ):
            bypanel[m["cohort_id"]].append(m)
    start = time.monotonic()
    receipts = []
    missing = []
    for p in panels:
        cid = p["cohort_id"]
        if a.panel and cid != a.panel:
            continue
        targets = bypanel[cid]
        if not targets:
            continue
        assert not p["wave_reserved"]
        if not p.get("minilm_matrix_path"):
            missing.append(
                {"cohort_id": cid, "rows": [m["row_id"] for m in targets], "reason": "prefix matrix unavailable"}
            )
            continue
        dest = a.out / (cid + ".jsonl")
        receiptfile = a.out / (cid + ".receipt.json")
        bound = {
            "background": p["background_sha256"],
            "functions": p["functions_sha256"],
            "matrix": p["minilm_matrix_sha256"],
            "script": sha(__file__),
            "contract": sha(HERE / "SPLIT-CONTRACT.json"),
            "targets": hashlib.sha256(json.dumps(targets, sort_keys=True).encode()).hexdigest(),
        }
        if dest.exists() and receiptfile.exists():
            old = json.loads(receiptfile.read_text())
            if old["bound"] == bound and sha(dest) == old["output_sha256"]:
                receipts.append(old)
                print("reuse", cid, flush=True)
                continue
        t = time.monotonic()
        assert sha(p["background_path"]) == p["background_sha256"]
        assert sha(p["functions_path"]) == p["functions_sha256"]
        assert sha(p["minilm_matrix_path"]) == p["minilm_matrix_sha256"]
        bg = BenchBackground.decode(pathlib.Path(p["background_path"]).read_bytes())
        index = bg.index()
        docs = jl(p["documents_path"])
        fs = jl(p["functions_path"])
        n = len(docs)
        v = np.load(p["minilm_matrix_path"], mmap_mode="r", allow_pickle=False)
        assert v.shape == (n, 384) and v.dtype == np.float32 and np.isfinite(v).all()
        assert np.max(np.abs(np.linalg.norm(v, axis=1) - 1)) < 1e-4
        for i, (d, f, bd) in enumerate(zip(docs, fs, bg.documents, strict=True)):
            assert (
                d["position"] == i
                and d["source_id"] == bd.id
                and hashlib.sha256(f["code"].encode()).hexdigest() == d["source_sha256"] == bd.source_sha256
            )
        ids = np.array([d["source_id"] for d in docs])
        paths = np.array([f["path"] for f in fs])
        langs = np.array(["python" if f["path"].endswith(".py") else "typescript" for f in fs])
        ties = np.array(sorted(range(n), key=lambda i: (docs[i]["source_id"], docs[i]["source_sha256"], i)))
        qs = collections.defaultdict(list)
        for m in targets:
            q, z = m["query_positions"]
            qs[q].append((m, z))
            qs[z].append((m, q))
        rows = []
        exposures = []
        known = {tuple(sorted(m["query_positions"])) for m in maps if m["cohort_id"] == cid}
        for q, items in sorted(qs.items()):
            scores = np.zeros(n, dtype=np.float64)
            for i, s in index.similar(bg.documents[q].tokens()):
                scores[i] = s
            dense = v @ v[q]
            rawmask = ids != ids[q]
            eligible = rawmask & (paths != paths[q]) & (langs == langs[q])
            sr, so = rank(scores, ties, rawmask)
            dr, do = rank(dense, ties, rawmask)
            fusion = 1 / (60 + sr.astype(float)) + 1 / (60 + dr.astype(float))
            fr, fo = rank(fusion, ties, rawmask)
            values = {"tfidf": scores, "minilm": dense, "rrf60": fusion}
            raws = {"tfidf": sr, "minilm": dr, "rrf60": fr}
            eranks = {}
            orders = {}
            for meth, s in values.items():
                eranks[meth], eo = rank(s, ties, eligible)
                orders[meth] = {"raw": {"tfidf": so, "minilm": do, "rrf60": fo}[meth], "eligible": eo}
                for scope, order in orders[meth].items():
                    for k in CAPS:
                        exposed = order[:k]
                        exposures.append(
                            {
                                "cohort_id": cid,
                                "query": q,
                                "method": meth,
                                "scope": scope,
                                "cap": k,
                                "selected": len(exposed),
                                "targets": list(map(int, exposed)),
                                "inventory_known_pairs": sum(tuple(sorted((q, int(z)))) in known for z in exposed),
                            }
                        )
            for m, z in items:
                r = byrow[m["row_id"]]
                nonblank = [sum(bool(x.strip()) for x in fs[i]["code"].splitlines()) for i in [q, z]]
                chars = [len(fs[i]["code"]) for i in [q, z]]
                rows.append(
                    {
                        "cohort_id": cid,
                        "repository": p["repository"],
                        "revision": p["revision"],
                        "background_sha256": p["background_sha256"],
                        "row_id": m["row_id"],
                        "pair_identity": m["pair_identity"],
                        "component": r["component"],
                        "family_component": m["family_component"],
                        "query": q,
                        "target": z,
                        "query_source_id": docs[q]["source_id"],
                        "target_source_id": docs[z]["source_id"],
                        "query_body_sha256": docs[q]["source_sha256"],
                        "target_body_sha256": docs[z]["source_sha256"],
                        "label": r["current_label"],
                        "accepted_gold": r["accepted_gold"],
                        "calibration_eligible": r["calibration_eligible"],
                        "label_scope": r["label_scope"],
                        "whole_function_label": r["whole_function_label"],
                        "prior_ensemble_evaluated": r["previous_ensemble_evaluated"],
                        "same_file": bool(paths[q] == paths[z]),
                        "same_language": bool(langs[q] == langs[z]),
                        "self_identity_collision": bool(ids[q] == ids[z]),
                        "nonblank_lines": nonblank,
                        "characters": chars,
                        "size_ratio": min(chars) / max(chars),
                        "size_stratum": "tiny_under8_lines"
                        if min(nonblank) < 8
                        else "long_over80_lines"
                        if max(nonblank) > 80
                        else "8_to80_lines",
                        "sparse_score_stratum": "below035"
                        if scores[z] < 0.35
                        else "035_to075"
                        if scores[z] < 0.75
                        else "075_plus",
                        "raw_rank_stratum": "long_tail_over50"
                        if min(sr[z], sr[q] if q == z else n + 1) > 50
                        else "rank11_to50"
                        if sr[z] > 10
                        else "top10",
                        "competitors": int(rawmask.sum()),
                        "eligible_competitors": int(eligible.sum()),
                        "scores": {meth: float(s[z]) for meth, s in values.items()},
                        "raw_ranks": {meth: int(rr[z]) if rawmask[z] else None for meth, rr in raws.items()},
                        "eligible_ranks": {meth: int(rr[z]) if eligible[z] else None for meth, rr in eranks.items()},
                    }
                )
        write(dest, rows)
        write(a.out / (cid + ".exposure.jsonl"), exposures)
        receipt = {
            "cohort_id": cid,
            "bound": bound,
            "output_sha256": sha(dest),
            "documents": n,
            "queries": len(qs),
            "directions": len(rows),
            "seconds": time.monotonic() - t,
            "sparse_refitted": False,
            "embedding_inference": False,
        }
        write(receiptfile, receipt)
        receipts.append(receipt)
        print(cid, len(qs), len(rows), round(time.monotonic() - t, 2), "s", flush=True)
        write(
            HERE / "STATUS.json",
            {
                "title": "Independent generalization and source-quality audit",
                "stage": "broad frozen reference running",
                "measured_coverage": {
                    "backgrounds_complete": len(receipts),
                    "directional_rows": sum(x["directions"] for x in receipts),
                },
                "next_artifact": "REFERENCE.json",
                "provider_calls": 0,
            },
        )
    write(
        a.out / "RUN.json",
        {
            "receipts": receipts,
            "missing": missing,
            "seconds": time.monotonic() - start,
            "product_commit": "a10a288530c4aa25711c7ec3b86ac164d182899a",
            "module_file": str(pathlib.Path(sys.modules["dry_lint.bench_background"].__file__).resolve()),
            "python": sys.version,
            "numpy": np.__version__,
            "threads": 2,
            "recipe": "full-corpus RRF60 equal sparse/prefix rank weights; cross-file ranking filters full raw fusion; self source identity excluded; ties source ID, body SHA256, corpus position",
            "contract_sha256": sha(HERE / "SPLIT-CONTRACT.json"),
            "providers": 0,
            "fit_calls": 0,
            "encoding_calls": 0,
        },
    )


if __name__ == "__main__":
    main()
