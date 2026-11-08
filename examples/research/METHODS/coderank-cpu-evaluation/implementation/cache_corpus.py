# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: I001
"""Label-free whole-background encoder with exact source, input and per-arm cache receipts."""

import argparse
import copy
import json
from pathlib import Path
import resource
import time
from coderank_adapter import CodeRankEncoder, canonical, digest, file_hash, setup_environment
from cpu_variant import CPUVariant
from preflight import save

HERE = Path(__file__).resolve().parent


def load_rows(path):
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    for i, r in enumerate(rows):
        if not isinstance(r.get("code"), str) or not r["code"].strip():
            raise ValueError(f"missing full native code at {i}")
        expected = r.get("code_sha256", r.get("source_sha256"))
        if expected and expected != digest(r["code"].encode()):
            raise ValueError(f"code hash mismatch at {i}")
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--cache", type=Path, default=HERE / "shared-vectors.sqlite3")
    p.add_argument("--threads", type=int, default=2)
    p.add_argument("--precision", choices=["fp32", "bf16"], default="fp32")
    p.add_argument("--attention", choices=["eager", "sdpa"], default="eager")
    p.add_argument("--chunk", type=int, default=128)
    p.add_argument("--batch-mode", choices=["dynamic", "singleton"], default="dynamic")
    a = p.parse_args()
    a.out = a.out.resolve()
    if not a.out.is_relative_to(HERE):
        raise ValueError("Outputs must remain in own .lab-results")
    a.out.mkdir(exist_ok=True, parents=True)
    if not a.cache.resolve().is_relative_to(HERE):
        raise ValueError("Cache must remain in own .lab-results")
    source = load_rows(a.input)
    texts = [r["code"] for r in source]
    source_hashes = [digest(t.encode()) for t in texts]
    setup_environment()
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(str(HERE / "model"), local_files_only=True)
    counts = [
        len(x)
        for x in tokenizer(texts, add_special_tokens=True, truncation=False, padding=False, verbose=False)["input_ids"]
    ]
    unique = {h: (t, n) for h, t, n in zip(source_hashes, texts, counts, strict=True)}
    plan = {
        "source_path": str(a.input.resolve()),
        "source_sha256": file_hash(a.input),
        "rows": len(source),
        "unique_full_source_hashes": len(unique),
        "source_hashes": source_hashes,
        "row_order_digest": digest(canonical(source_hashes)),
        "tokens_before": counts,
        "limits": {
            str(limit): {
                "truncated_occurrences": sum(n > limit for n in counts),
                "unique_inputs_needing_encoding": len(unique)
                if limit == 1024
                else sum(n > (1024 if limit == 2048 else 2048) for _, n in unique.values()),
            }
            for limit in (1024, 2048, 4096)
        },
        "precision": a.precision,
        "attention": a.attention,
        "threads": a.threads,
        "authorization": "Execution requires caller --execute after coordinator allocation",
        "labels_used": False,
    }
    save(a.out / "plan.json", plan)
    if not a.execute:
        print("plan", len(source), "rows", len(unique), "unique bodies")
        return
    start = time.perf_counter()
    variant = a.attention != "eager" or a.precision != "fp32" or a.threads != 2
    e = (
        CPUVariant(
            cache_path=a.cache, threads=a.threads, precision=a.precision, attention=a.attention, batch_mode=a.batch_mode
        )
        if variant
        else CodeRankEncoder(cache_path=a.cache)
    )
    import numpy as np

    # Before any cross-limit reuse, compare fresh singleton and batched normalized vectors.
    eligible = [i for i, n in enumerate(counts) if n <= 1024]
    check = [texts[eligible[round(k * (len(eligible) - 1) / 3)]] for k in range(4)]
    inp = [e.token_inputs(check, n)[0] for n in (1024, 2048, 4096)]
    assert inp[0] == inp[1] == inp[2]
    vs = [e.encode(check, n, use_cache=False) for n in (1024, 2048, 4096)]
    delta = max(float(np.max(np.abs(vs[0] - v))) for v in vs[1:])
    assert delta < 1e-5, delta
    singleton = e.encode([check[0]], 1024, use_cache=False)[0]
    padding_delta = float(np.max(np.abs(singleton - vs[0][0])))
    # BF16 padding can change numeric kernels; do not claim strict parity if that occurs.
    if padding_delta > 1e-5:
        raise ValueError(f"Padding invariance not proven: {padding_delta}")
    proof = {
        "contract_digest": e.contract_digest,
        "input_arrays_equal": True,
        "max_abs_limit_delta": delta,
        "singleton_batch_delta": padding_delta,
        "tolerance": 1e-5,
        "source_hashes": [digest(t.encode()) for t in check],
        "reason": "max_length never enters forward; fixed-base RoPE; exact model-input equality and separately tested padding invariance",
    }
    save(a.out / "equivalence-proof.json", proof)
    e.allow_cross_limit_reuse = True
    receipt = {
        "status": "running",
        "source": plan,
        "contract": e.contract,
        "contract_digest": e.contract_digest,
        "load_seconds": e.load_seconds,
        "arms": {},
        "started_unix": time.time(),
    }
    save(a.out / "receipt.json", receipt)
    for limit in (1024, 2048, 4096):
        matrix = np.lib.format.open_memmap(
            a.out / f"embeddings-{limit}.npy", mode="w+", dtype=np.float32, shape=(len(texts), 768)
        )
        arm = {"limit": limit, "chunks": [], "encoded_rows": 0, "cache_hits": 0, "cross_limit_hits": 0, "seconds": 0}
        # Length-sort chunks to avoid every small function padding toward a single long source.
        ordered = sorted(range(len(texts)), key=lambda i: (min(counts[i], limit), source_hashes[i], i))
        for offset in range(0, len(ordered), a.chunk):
            ids = ordered[offset : offset + a.chunk]
            matrix[ids] = e.encode([texts[i] for i in ids], limit)
            s = copy.deepcopy(e.last_stats)
            s["source_row_indices"] = ids
            for key in ("encoded_rows", "cache_hits", "cross_limit_hits", "seconds"):
                arm[key] += s[key]
            arm["chunks"].append(s)
            matrix.flush()
            receipt["arms"][str(limit)] = arm
            receipt["peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            save(a.out / "receipt.json", receipt)
            print(
                "limit",
                limit,
                "rows",
                offset + len(ids),
                "/",
                len(texts),
                "encoded",
                arm["encoded_rows"],
                "seconds",
                round(arm["seconds"], 2),
                flush=True,
            )
        arm["matrix_sha256"] = file_hash(a.out / f"embeddings-{limit}.npy")
    receipt.update(status="complete", total_seconds=time.perf_counter() - start)
    save(a.out / "receipt.json", receipt)


if __name__ == "__main__":
    main()
