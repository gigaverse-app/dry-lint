# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B905, E741, I001
"""Approved complete two-panel OpenHands run, exact body dedup and input-equivalent arm reuse."""

from _recovery_paths import recovery_path
import argparse
import hashlib
import json
from pathlib import Path
import resource
import time
import traceback
from gemma_adapter import HERE, sha_file, digest, LIMITS
from gemma_variants import EfficientGemmaEncoder
from gemma_batch_adapter import BatchedGemmaEncoder

PANELS = Path(recovery_path("jobs/encoder-corpus-evaluation/.lab-results/panels.jsonl"))


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(obj, indent=2) + "\n")
    temp.replace(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=["single", "batch4"], required=True)
    args = ap.parse_args()
    tag = "bfloat16-t4-b4" if args.variant == "batch4" else "bfloat16-t4"
    out = HERE / "openhands" / tag
    out.mkdir(parents=True, exist_ok=True)
    panels = [json.loads(l) for l in PANELS.read_text().splitlines() if l]
    panels = [p for p in panels if p["repository"] == "OpenHands/software-agent-sdk"]
    assert {p["cohort_id"] for p in panels} == {"bg-a068703e185ee6a8", "bg-ebd0031534c954e5"}
    unique = {}
    orders = {}
    proofs = {}
    for panel in panels:
        assert panel["archive_full_source_valid"] and panel["body_rows_missing"] == 0
        assert sha_file(panel["functions_path"]) == panel["functions_sha256"]
        rows = [json.loads(l) for l in Path(panel["functions_path"]).read_text().splitlines()]
        source_proof = [json.loads(l) for l in Path(panel["source_proof_path"]).read_text().splitlines()]
        assert len(rows) == len(source_proof) == panel["functions"]
        hashes = []
        for i, (r, p) in enumerate(zip(rows, source_proof)):
            h = hashlib.sha256(r["code"].encode()).hexdigest()
            assert h == p["source_sha256"] and p["matching_native_symbols"] == 1, (panel["cohort_id"], i)
            assert p["row"] == i
            if h in unique:
                assert unique[h] == r["code"]
            unique[h] = r["code"]
            hashes.append(h)
        orders[panel["cohort_id"]] = hashes
        save(
            out / panel["cohort_id"] / "source-order.json",
            {
                "functions_sha256": panel["functions_sha256"],
                "ordered_source_sha256": hashes,
                "order_digest": digest(hashes),
            },
        )
        proofs[panel["cohort_id"]] = {
            "source_proof_sha256": sha_file(panel["source_proof_path"]),
            "source_rows_verified": len(rows),
        }
    encoder = BatchedGemmaEncoder() if args.variant == "batch4" else EfficientGemmaEncoder(dtype="bfloat16", threads=4)
    trial = json.loads((HERE / "throughput" / tag / "result.json").read_text())
    assert encoder.contract_sha256 == trial["contract_sha256"]
    # Numeric panel qualifies a research variant; these are drift guards, never accuracy thresholds.
    assert trial["finite"] and trial["cosine_min"] >= 0.999 and trial["max_abs_pair_score_difference"] < 0.01
    encoder.enable_cache(out / "vectors.sqlite", HERE / "throughput" / tag / "equivalence-proof.json")
    np = encoder.np
    batch_size = encoder.contract["batch_size"]
    lengths = {h: encoder.prepare(code, 4096)[1]["tokens_before"] for h, code in unique.items()}
    ordered = sorted(unique, key=lambda h: (lengths[h], h))
    save(
        out / "plan.json",
        {
            "panels_manifest_sha256": sha_file(PANELS),
            "panels": panels,
            "unique_bodies": len(unique),
            "occurrences": sum(len(v) for v in orders.values()),
            "source_proofs": proofs,
            "unique_order_digest": digest(ordered),
            "batch_size": batch_size,
            "limits": list(LIMITS),
            "contract_sha256": encoder.contract_sha256,
            "lengths": {
                "minimum": min(lengths.values()),
                "maximum": max(lengths.values()),
                "sum": sum(lengths.values()),
                "overflow": {str(k): sum(n > k for n in lengths.values()) for k in LIMITS},
            },
        },
    )
    save(out / "encoder-contract.json", encoder.contract)
    print(
        json.dumps(
            {"status": "START", "unique_bodies": len(unique), "tag": tag, "threads": 4, "batch_size": batch_size}
        ),
        flush=True,
    )
    receipts = []
    for limit in LIMITS:
        start = time.perf_counter()
        vectors = {}
        records = {}
        hits = 0
        inference_seconds = 0
        with (out / f"unique-timings-{limit}.jsonl").open("w") as log:
            for offset in range(0, len(ordered), batch_size):
                group = ordered[offset : offset + batch_size]
                matrix = encoder.encode([unique[h] for h in group], limit)
                for h, vector, rec in zip(group, matrix, encoder.last_records):
                    assert h == rec["source_sha256"]
                    vectors[h] = vector
                    records[h] = rec
                    hits += bool(rec["cache_hit"])
                    inference_seconds += rec["inference_seconds"]
                    log.write(json.dumps(rec) + "\n")
                log.flush()
                if offset % 100 == 0 or offset + batch_size >= len(ordered):
                    progress = {
                        "limit": limit,
                        "done": min(offset + batch_size, len(ordered)),
                        "unique_bodies": len(ordered),
                        "cache_hits": hits,
                        "elapsed_seconds": time.perf_counter() - start,
                    }
                    save(out / "PROGRESS.json", progress)
                    print(json.dumps(progress), flush=True)
        arm_seconds = time.perf_counter() - start
        for panel in panels:
            key = panel["cohort_id"]
            folder = out / key
            matrix = np.stack([vectors[h] for h in orders[key]])
            assert matrix.shape == (panel["functions"], 768) and np.isfinite(matrix).all()
            path = folder / f"embeddings-{limit}.npy"
            np.save(path, matrix)
            tokens = folder / f"tokens-{limit}.jsonl"
            tokens.write_text("".join(json.dumps({"row": i, **records[h]}) + "\n" for i, h in enumerate(orders[key])))
            receipt = {
                "schema": 1,
                "status": "complete",
                "variant": tag,
                "model": encoder.contract["model"],
                "revision": encoder.contract["revision"],
                "contract_sha256": encoder.contract_sha256,
                "contract_path": str(out / "encoder-contract.json"),
                "cohort_id": key,
                "background_sha256": panel["background_sha256"],
                "repository": panel["repository"],
                "source_revision": panel["revision"],
                "functions_path": panel["functions_path"],
                "functions_sha256": panel["functions_sha256"],
                "input_row_order_digest": digest(orders[key]),
                "source_order_path": str(folder / "source-order.json"),
                "matrix_path": str(path),
                "matrix_sha256": sha_file(path),
                "rows": len(matrix),
                "dimensions": 768,
                "dtype": "float32 vectors from native BF16 inference",
                "inference_dtype": "bfloat16",
                "max_length": limit,
                "mode": "symmetric",
                "prefix": encoder.prefix,
                "missing_rows": 0,
                "finite": bool(np.isfinite(matrix).all()),
                "norm_max_error": float(np.abs(np.linalg.norm(matrix, axis=1) - 1).max()),
                "tokens_path": str(tokens),
                "tokens_sha256": sha_file(tokens),
                "truncated_rows": sum(records[h]["truncated"] for h in orders[key]),
                "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "unique_union_bodies": len(unique),
                "unique_union_cache_hits": hits,
                "union_wall_seconds": arm_seconds,
                "union_inference_seconds": inference_seconds,
                "physical_cost_scope": "Union of both panels; do not add this time once per panel.",
                "command": f".lab-results/run.sh .lab-results/full_openhands.py --variant {args.variant}",
                "accuracy_claims": None,
                "provider_calls": 0,
                "runtime": encoder.contract["runtime"],
                "threads": 4,
                "batch_size": batch_size,
            }
            receipt_path = folder / f"receipt-{limit}.json"
            save(receipt_path, receipt)
            receipts.append(str(receipt_path))
            save(
                HERE / "OPENHANDS-MATRICES.json",
                {"status": "in_progress" if limit != 4096 else "complete", "variant": tag, "receipts": receipts},
            )
            print(json.dumps({"status": "MATRIX_READY", "receipt": str(receipt_path)}), flush=True)
    save(out / "COMPLETE.json", {"receipts": receipts, "unique_bodies": len(unique), "provider_calls": 0})


if __name__ == "__main__":
    try:
        main()
    except Exception:
        (HERE / "openhands-failure.txt").write_text(traceback.format_exc())
        raise
