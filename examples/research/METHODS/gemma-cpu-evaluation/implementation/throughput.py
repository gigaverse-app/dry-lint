# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B905, F401, I001
"""Fixed native 12-row speed/parity panel. Ranks here measure numerical drift, never accuracy."""

import argparse
import hashlib
import json
from pathlib import Path
import resource
import time
from gemma_adapter import HERE, LIMITS, sha_file, digest
from gemma_variants import EfficientGemmaEncoder


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--threads", type=int, required=True)
    parser.add_argument("--dtype", required=True)
    args = parser.parse_args()
    rows = [json.loads(x) for x in (HERE / "preflight-source-sample.jsonl").read_text().splitlines()]
    timings = [json.loads(x) for x in (HERE / "timings-1024.jsonl").read_text().splitlines()]
    assert len(timings) == 108
    # Fixed 12 quantile positions in actual untruncated native token length; includes two longest.
    order = sorted(range(len(rows)), key=lambda i: (timings[i]["tokens_before"], rows[i]["source_sha256"]))
    positions = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 107]
    indices = [order[p] for p in positions]
    encoder = EfficientGemmaEncoder(dtype=args.dtype, threads=args.threads)
    np = encoder.np
    tag = f"{args.dtype}-t{args.threads}"
    outdir = HERE / "throughput" / tag
    outdir.mkdir(parents=True, exist_ok=True)
    reference = np.load(HERE / "preflight-1024.npy")[indices]
    # Warm one shortest source, then measure fixed panel once. Baseline was also model-warm.
    encoder.encode([rows[indices[0]]["code"]], 1024)
    begin = time.perf_counter()
    matrix = []
    records = []
    for i in indices:
        v = encoder.encode([rows[i]["code"]], 1024)[0]
        matrix.append(v)
        records.append(encoder.last_records[0] | {"sample_row": i})
        print(json.dumps({"variant": tag, "done": len(matrix), "seconds": time.perf_counter() - begin}), flush=True)
    matrix = np.stack(matrix)
    elapsed = time.perf_counter() - begin
    cos = (matrix * reference).sum(1)
    delta = np.abs(matrix - reference)
    rscore = reference @ reference.T
    vscore = matrix @ matrix.T
    np.fill_diagonal(rscore, -np.inf)
    np.fill_diagonal(vscore, -np.inf)
    rr = np.argsort(-rscore, kind="stable")
    vr = np.argsort(-vscore, kind="stable")
    ref_seconds = sum(timings[i]["inference_seconds"] for i in indices)
    result = {
        "tag": tag,
        "contract": encoder.contract,
        "contract_sha256": encoder.contract_sha256,
        "sample_rows": indices,
        "rows": 12,
        "limit": 1024,
        "selection": "fixed untruncated-Gemma-token length rank positions " + str(positions),
        "seconds": elapsed,
        "reference_inference_seconds": ref_seconds,
        "inference_seconds": sum(r["inference_seconds"] for r in records),
        "speedup_vs_saved_reference": ref_seconds / sum(r["inference_seconds"] for r in records),
        "cosine_min": float(cos.min()),
        "cosine_mean": float(cos.mean()),
        "max_abs_vector_difference": float(delta.max()),
        "max_abs_pair_score_difference": float(np.abs((matrix @ matrix.T) - (reference @ reference.T)).max()),
        "top1_identical": int((rr[:, 0] == vr[:, 0]).sum()),
        "top3_sets_identical": sum(set(a[:3]) == set(b[:3]) for a, b in zip(rr, vr)),
        "finite": bool(np.isfinite(matrix).all()),
        "norm_max_error": float(np.max(np.abs(np.linalg.norm(matrix, axis=1) - 1))),
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "accuracy_claims": None,
        "timing_limit": "Different process/time on shared host, single repetition, no throughput guarantee; primary reference used two threads.",
    }
    np.save(outdir / "vectors-1024.npy", matrix)
    (outdir / "records.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    (outdir / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    # Uncached exact-input equality at all limits qualifies reuse within this alternate contract.
    payloads = [encoder.prepare(rows[indices[0]]["code"], k)[0] for k in LIMITS]
    vs = [encoder.forward_payload(p) for p in payloads]
    maxdiff = max(float(np.max(np.abs(v - vs[0]))) for v in vs)
    proof = {
        "contract_sha256": encoder.contract_sha256,
        "equal_inputs": all(p == payloads[0] for p in payloads),
        "max_abs_vector_difference": maxdiff,
        "limits": list(LIMITS),
        "passed": all(p == payloads[0] for p in payloads) and maxdiff == 0,
        "scope": "same fixed batch-size-one unpadded native model input, all modes same contract",
    }
    (outdir / "equivalence-proof.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
