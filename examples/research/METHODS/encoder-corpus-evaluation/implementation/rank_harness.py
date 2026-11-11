# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, E731, F401, F403, F405, F841, I001
"""Floor-free full-background ranks. No model execution; source-order checked receipts."""

from common import *
import argparse, collections, time, platform, importlib.metadata
import numpy as np
from dry_lint.bench_background import BenchBackground

CAPS = [1, 3, 10, 50, 100]


def ordered(scores, indices, tie):
    return sorted(indices, key=lambda i: (-float(scores[i]), tie[i], i))


def score_query(scores, q, targets, docs, method, panel):
    assert np.isfinite(scores).all()
    tie = [(d["source_id"], d["source_sha256"]) for d in docs]
    order = ordered(scores, [i for i in range(len(docs)) if i != q], tie)
    raw = {i: r for r, i in enumerate(order, 1)}
    path = lambda i: docs[i]["source_id"].split("::")[0]
    language = lambda i: "python" if path(i).endswith(".py") else "typescript"
    cross = [i for i in order if path(i) != path(q) and language(i) == language(q)]
    eligible = {i: r for r, i in enumerate(cross, 1)}
    vals = scores[np.asarray(order)]
    dist = {str(p): float(np.quantile(vals, p)) for p in [0, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99, 1]} if order else {}
    return [
        dict(
            schema=1,
            method=method,
            cohort_id=panel["cohort_id"],
            repository=panel["repository"],
            revision=panel["revision"],
            background_sha256=panel["background_sha256"],
            row_id=m["row_id"],
            pair_identity=m["pair_identity"],
            family_component=m["family_component"],
            split=m["split"],
            label=m["label"],
            accepted_gold=m["accepted_gold"],
            calibration_eligible=m["calibration_eligible"],
            direction=direction,
            query_position=q,
            target_position=t,
            score=float(scores[t]),
            raw_rank=raw.get(t),
            eligible_rank=eligible.get(t),
            same_file=path(q) == path(t),
            same_language=language(q) == language(t),
            competitors=len(order),
            eligible_competitors=len(cross),
            score_distribution=dist,
            raw_top100=order[:100],
            eligible_top100=cross[:100],
            top_scores=[float(scores[i]) for i in order[:100]],
        )
        for m, t, direction in targets
    ]


def summarize(rows):
    groups = collections.defaultdict(list)
    for r in rows:
        groups[(r["method"], r["cohort_id"], str(r["label"]), r["split"])].append(r)
    result = []
    for (method, cid, label, split), rs in sorted(groups.items()):
        pairs = collections.defaultdict(list)
        for r in rs:
            pairs[r["pair_identity"]].append(r)
        result.append(
            dict(
                method=method,
                cohort_id=cid,
                label=label,
                split=split,
                directional_rows=len(rs),
                unique_pairs=len(pairs),
                independent_family_components=len({r["family_component"] for r in rs}),
                directional_raw_hits={
                    str(k): sum(r["raw_rank"] is not None and r["raw_rank"] <= k for r in rs) for k in CAPS
                },
                pair_either_raw_hits={
                    str(k): sum(
                        any(r["raw_rank"] is not None and r["raw_rank"] <= k for r in rr) for rr in pairs.values()
                    )
                    for k in CAPS
                },
                pair_either_eligible_hits={
                    str(k): sum(
                        any(r["eligible_rank"] is not None and r["eligible_rank"] <= k for r in rr)
                        for rr in pairs.values()
                    )
                    for k in CAPS
                },
                gold_score_quantiles={
                    str(p): float(np.quantile([r["score"] for r in rs], p)) for p in [0, 0.25, 0.5, 0.75, 1]
                },
            )
        )
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", choices=["tfidf", "minilm", "worker"], required=True)
    ap.add_argument("--panel")
    ap.add_argument("--matrix-receipt")
    args = ap.parse_args()
    panels = jl(HERE / "panels.jsonl")
    mappings = jl(HERE / "mapped-gold.jsonl")
    receipt = json.loads(Path(args.matrix_receipt).read_text()) if args.matrix_receipt else None
    if receipt:
        args.panel = receipt["cohort_id"]
    selected = [p for p in panels if not args.panel or p["cohort_id"] == args.panel]
    started = time.monotonic()
    processed = []
    overrides = (
        json.loads((HERE / "baseline-matrices.json").read_text()) if (HERE / "baseline-matrices.json").exists() else {}
    )
    for p in selected:
        p = {**p, **overrides.get(p["cohort_id"], {})}
        ms = [m for m in mappings if m["cohort_id"] == p["cohort_id"] and m["record_kind"] == "function"]
        docs = jl(p["documents_path"])
        method = (
            "tfidf-frozen-raw"
            if args.method == "tfidf"
            else "minilm256-raw"
            if args.method == "minilm"
            else receipt["method"]
        )
        dest = HERE / "ranks" / method / (p["cohort_id"] + ".jsonl")
        meta = dest.with_suffix(".receipt.json")
        if not ms:
            continue
        if args.method != "tfidf" and not p["archive_full_source_valid"]:
            continue
        if args.method == "minilm" and not p["minilm_matrix_path"]:
            continue
        inputs = {
            "panel_manifest_sha256": sha(HERE / "panels.jsonl"),
            "mapped_gold_sha256": sha(HERE / "mapped-gold.jsonl"),
            "harness_sha256": sha(__file__),
        }
        assert sha(p["background_path"]) == p["background_sha256"]
        inputs["background_sha256"] = sha(p["background_path"])
        if receipt:
            inputs["matrix_receipt_sha256"] = sha(args.matrix_receipt)
            inputs["document_matrix_sha256"] = sha(receipt["document_matrix_path"])
            inputs["query_matrix_sha256"] = sha(receipt.get("query_matrix_path", receipt["document_matrix_path"]))
            inputs["model_contract_digest"] = receipt.get(
                "model_contract_digest", receipt.get("contract_digest")
            ) or digest(json.dumps(receipt.get("model_contract", receipt), sort_keys=True))
            assert inputs["document_matrix_sha256"] == receipt["document_matrix_sha256"]
            assert inputs["query_matrix_sha256"] == receipt.get(
                "query_matrix_sha256", receipt["document_matrix_sha256"]
            )
        elif args.method == "minilm":
            inputs["document_matrix_sha256"] = sha(p["minilm_matrix_path"])
            assert inputs["document_matrix_sha256"] == p["minilm_matrix_sha256"]
        if dest.exists() and meta.exists() and json.loads(meta.read_text()).get("inputs") == inputs:
            print("reuse", method, p["cohort_id"], flush=True)
            continue
        t = time.monotonic()
        fs = None
        vectors = None
        if args.method == "tfidf":
            b = BenchBackground.decode(Path(p["background_path"]).read_bytes())
            index = b.index()
        else:
            if receipt:
                assert receipt["functions_sha256"] == p["functions_sha256"]
                assert receipt["background_sha256"] == p["background_sha256"]
                assert receipt["token_limit"] in [1024, 2048, 4096]
                mp = Path(receipt["document_matrix_path"])
                assert sha(mp) == receipt["document_matrix_sha256"]
                qp = Path(receipt.get("query_matrix_path", str(mp)))
                assert sha(qp) == receipt.get("query_matrix_sha256", receipt["document_matrix_sha256"])
            else:
                mp = qp = Path(p["minilm_matrix_path"])
                assert sha(mp) == p["minilm_matrix_sha256"]
            vectors = np.load(mp, mmap_mode="r", allow_pickle=False)
            query = vectors if mp == qp else np.load(qp, mmap_mode="r", allow_pickle=False)
            for a in [vectors, query]:
                assert a.dtype == np.float32 and a.ndim == 2 and a.shape[0] == len(docs) and np.isfinite(a).all()
                assert np.max(np.abs(np.linalg.norm(a, axis=1) - 1)) < 1e-4
            assert vectors.shape == query.shape
        queries = collections.defaultdict(list)
        for m in ms:
            a, z = m["query_positions"]
            queries[a].append((m, z, "new_to_existing"))
            queries[z].append((m, a, "existing_to_new"))
        output = []
        for q, targets in sorted(queries.items()):
            if args.method == "tfidf":
                scores = np.zeros(len(docs), dtype=np.float64)
                for i, s in index.similar(b.documents[q].tokens()):
                    scores[i] = s
            else:
                scores = vectors @ query[q]
            output.extend(score_query(scores, q, targets, docs, method, p))
        write(dest, output)
        write(dest.with_suffix(".summary.json"), summarize(output))
        write(
            meta,
            dict(
                inputs=inputs,
                method=method,
                rows=len(output),
                queries=len(queries),
                documents=len(docs),
                seconds=time.monotonic() - t,
                output_sha256=sha(dest),
                matrix_receipt=receipt,
            ),
        )
        processed.append(str(dest))
        print(method, p["cohort_id"], len(output), "directions", round(time.monotonic() - t, 3), "s", flush=True)
    write(
        HERE / ("rank-run-" + args.method + ".json"),
        dict(
            processed=processed,
            seconds=time.monotonic() - started,
            python=platform.python_version(),
            numpy=np.__version__,
            product_commit=REF,
            inference=False,
        ),
    )


if __name__ == "__main__":
    main()
