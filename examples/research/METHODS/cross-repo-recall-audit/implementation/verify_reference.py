# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B023, E401, E402, E731, I001
"""Verify independent rank reconstruction and pinned production-index semantics."""

import os

for k in ["OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"]:
    os.environ[k] = "2"
import collections, json, pathlib, sys
from inventory import HERE, BASE, jl, sha, write

sys.path.insert(0, str(BASE / "runtime/src"))
import numpy as np
from dry_lint.bench_background import BenchBackground
from dry_lint.models import Function
from dry_lint.comparers import TfidfComparer
from dry_lint.cpu_embedding import CpuEmbeddingComparer


def main():
    run = json.loads((HERE / "reference/RUN.json").read_text())
    panels = {p["cohort_id"]: p for p in jl(HERE / "frozen-panels.jsonl")}
    checks = []
    mismatches = []
    for receipt in run["receipts"]:
        cid = receipt["cohort_id"]
        rows = jl(HERE / "reference" / (cid + ".jsonl"))
        bykey = {(r["row_id"], r["query"], r["target"]): r for r in rows}
        for method, folder in [("tfidf", "tfidf-frozen-raw"), ("minilm", "minilm256-raw")]:
            old = BASE / "ranks" / folder / (cid + ".jsonl")
            meta = old.with_suffix(".receipt.json")
            if not old.exists() or not meta.exists():
                continue
            rm = json.loads(meta.read_text())
            assert sha(old) == rm["output_sha256"]
            assert rm["inputs"]["background_sha256"] == panels[cid]["background_sha256"]
            if method == "minilm":
                assert rm["inputs"]["document_matrix_sha256"] == panels[cid]["minilm_matrix_sha256"]
            n = 0
            for r in jl(old):
                new = bykey.get((r["row_id"], r["query_position"], r["target_position"]))
                if new is None:
                    continue
                n += 1
                if (
                    abs(new["scores"][method] - r["score"]) > 1e-6
                    or new["raw_ranks"][method] != r["raw_rank"]
                    or new["eligible_ranks"][method] != r["eligible_rank"]
                ):
                    mismatches.append(
                        {
                            "row_id": r["row_id"],
                            "cohort": cid,
                            "method": method,
                            "old": [r["score"], r["raw_rank"], r["eligible_rank"]],
                            "new": [new["scores"][method], new["raw_ranks"][method], new["eligible_ranks"][method]],
                        }
                    )
            checks.append({"cohort_id": cid, "method": method, "matched_directions": n, "old_output_sha256": sha(old)})
    audits = []
    # Full large Python, TypeScript, and historical configured Python corpora.
    for cid in ["bg-7489aa1946c16153", "bg-62d8145fa0144191", "bg-fb2e166253479293"]:
        p = panels[cid]
        bg = BenchBackground.decode(pathlib.Path(p["background_path"]).read_bytes())
        raw = jl(p["functions_path"])
        fs = []
        for r, d in zip(raw, bg.documents, strict=True):
            f = Function.model_validate(r if r.get("line") is not None else r | {"line": 0, "end_line": -1})
            f.tokens = d.tokens()
            fs.append(f)
        sparse = TfidfComparer()
        sparse.functions = fs
        sparse.position = {f.qualname: i for i, f in enumerate(fs)}
        sparse.tfidf = bg.index()
        v = np.load(p["minilm_matrix_path"], mmap_mode="r")
        dense = CpuEmbeddingComparer.__new__(CpuEmbeddingComparer)
        dense.np = np
        dense.functions = fs
        dense.vectors = v
        dense.min_similarity = 0.8
        dense._ambiguous = {n for n, c in collections.Counter(f.qualname for f in fs).items() if c > 1}
        body = {f.code: x for f, x in zip(fs, v, strict=True)}
        dense._vectors = lambda codes: np.asarray([body[c] for c in codes])  # missing cache raises; cannot encode
        directions = jl(HERE / "reference" / (cid + ".jsonl"))
        qs = sorted({d["query"] for d in directions})
        # Source-position spread, independent of score or labels. Complete indexes, six queries each.
        qs = [qs[i] for i in np.linspace(0, len(qs) - 1, min(6, len(qs)), dtype=int)]
        for q in qs:
            allow = lambda f: (
                f.path != fs[q].path and f.qualname != fs[q].qualname and f.analysis.language == fs[q].analysis.language
            )
            got_s = sparse.neighbours(fs[q], 20, allow)
            got_d = dense.neighbours(fs[q], 20, allow)
            expected_s = [
                (fs[i], s)
                for i, s in sparse.tfidf.similar(fs[q].tokens, exclude={q})
                if s >= sparse.floor(fs[q]) and allow(fs[i])
            ][:20]
            values = v @ v[q]
            expected_d = (
                [
                    (fs[i], min(1.0, max(0.0, float(values[i]))))
                    for i in np.argsort(-values, kind="stable")
                    if values[i] >= 0.8
                    and allow(fs[i])
                    and fs[i].qualname not in dense._ambiguous
                    and dense._source_known(fs[i])
                ][:20]
                if fs[q].qualname not in dense._ambiguous and dense._source_known(fs[q])
                else []
            )
            assert [(f.qualname, s) for f, s in got_s] == [(f.qualname, s) for f, s in expected_s]
            assert [(f.qualname, s) for f, s in got_d] == [(f.qualname, s) for f, s in expected_d]
            audits.append(
                {
                    "cohort_id": cid,
                    "query": q,
                    "functions": len(fs),
                    "sparse_returned": len(got_s),
                    "prefix_returned": len(got_d),
                    "raw_reference_floor_free": True,
                    "production_floor_applied": {"tfidf": sparse.floor(fs[q]), "minilm": 0.8},
                    "source_order_ties_native": True,
                    "no_refit_no_encoder": True,
                }
            )
    result = {
        "frozen_rank_receipts": checks,
        "matched_directional_method_records": sum(c["matched_directions"] for c in checks),
        "mismatches": mismatches,
        "production_index_audits": audits,
        "contract_sha256": sha(HERE / "SPLIT-CONTRACT.json"),
        "caution": "Independent reference uses lexicographic source tie order; native comparer uses corpus stable tie order, floors and source-ambiguity rules. Raw recall is not native candidate admission.",
    }
    write(HERE / "VERIFICATION.json", result)
    assert not mismatches
    print(
        "matched",
        result["matched_directional_method_records"],
        "mismatches",
        len(mismatches),
        "native full-index checks",
        len(audits),
    )


if __name__ == "__main__":
    main()
