# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B007, F401, I001
"""108 native unlabeled source rows: cold first pass, explicit equivalence, incremental limits."""

import argparse
import copy
import json
import os
from pathlib import Path
import platform
import resource
import sys
import time
import traceback
from coderank_adapter import CodeRankEncoder, canonical, digest, file_hash

HERE = Path(__file__).resolve().parent


def save(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="preflight")
    parser.add_argument("--stop-after-1024", action="store_true")
    args = parser.parse_args()
    out = HERE / args.out
    out.mkdir(exist_ok=True)
    source = HERE / "preflight-source-sample.jsonl"
    rows = [json.loads(x) for x in source.read_text().splitlines()]
    assert (
        len(rows) == 108
        and file_hash(source) == json.loads((HERE / "preflight-source-sample.manifest.json").read_text())["sha256"]
    )
    assert all(digest(r["code"].encode()) == r["source_sha256"] for r in rows)
    texts = [r["code"] for r in rows]
    started = time.perf_counter()
    e = CodeRankEncoder(cache_path=out / "vectors.sqlite3")
    import numpy as np

    status = {
        "status": "running",
        "source_sha256": file_hash(source),
        "rows": len(rows),
        "contract": e.contract,
        "contract_digest": e.contract_digest,
        "load_seconds": e.load_seconds,
        "strict_state_dict_load": e.load_result,
        "cold_definition": "Fresh process; first inference is all 108 at 1024. OS page cache not flushed. 2048/4096 are incremental after proof, not cold all-row passes.",
        "cpu": platform.processor(),
        "platform": platform.platform(),
        "visible_cpus": os.cpu_count(),
        "affinity": sorted(os.sched_getaffinity(0)),
        "arms": {},
        "no_accuracy_claim": True,
    }
    save(out / "status.json", status)
    v = e.encode(texts, 1024)
    s = copy.deepcopy(e.last_stats)
    status["arms"]["1024"] = s
    status["peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    np.save(out / "embeddings-1024.npy", v)
    save(out / "status.json", status)
    print("cold 1024 completed", s["seconds"], s["encoded_rows"], "RSS KiB", status["peak_rss_kib"], flush=True)
    if args.stop_after_1024:
        status["status"] = "reference_1024_complete"
        save(out / "status.json", status)
        return
    # Limit does not enter forward; prove exact token inputs and normalized outputs agree.
    ids = [i for i, n in enumerate(s["tokens_before"]) if n <= 1024]
    ids = sorted(ids, key=lambda i: s["tokens_before"][i])
    check_ids = [ids[round(k * (len(ids) - 1) / 7)] for k in range(8)]
    check = [texts[i] for i in check_ids]
    inputs = [e.token_inputs(check, limit)[0] for limit in (1024, 2048, 4096)]
    assert inputs[0] == inputs[1] == inputs[2]
    refs = [e.encode(check, limit, use_cache=False) for limit in (1024, 2048, 4096)]
    delta = max(float(np.max(np.abs(refs[0] - x))) for x in refs[1:])
    assert delta < 1e-5, delta
    alone = e.encode([check[0]], 1024, use_cache=False)[0]
    pad_delta = float(np.max(np.abs(alone - refs[0][0])))
    assert pad_delta < 1e-5, pad_delta
    proof = {
        "contract_digest": e.contract_digest,
        "source_rows": check_ids,
        "input_arrays_equal": True,
        "limits": [1024, 2048, 4096],
        "max_abs_delta": delta,
        "batch_vs_singleton_max_abs_delta": pad_delta,
        "tolerance": 1e-5,
        "rationale": "No max_length passed into model. Fixed-base RoPE, no NTK or XPos scaling; right padding masked. Reuse only identical complete token input dictionaries and encoder/role contract. Full source and requested limit retained in arms table.",
        "status": "passed",
    }
    save(out / "equivalence-proof.json", proof)
    # Migrate only the measured 1024 vectors after explicit numeric proof.
    e.allow_cross_limit_reuse = True
    for i, text in enumerate(texts):
        key = digest(canonical([e.contract_digest, "code", s["input_hashes"][i], None]))
        e.db.execute(
            "INSERT OR IGNORE INTO vectors VALUES(?,?,?,?,?)",
            (key, e.contract_digest, s["input_hashes"][i], 1024, v[i].tobytes()),
        )
    e.db.commit()
    for limit in (2048, 4096):
        arr = e.encode(texts, limit)
        status["arms"][str(limit)] = copy.deepcopy(e.last_stats)
        np.save(out / f"embeddings-{limit}.npy", arr)
        status["peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        save(out / "status.json", status)
        print(
            "incremental",
            limit,
            "seconds",
            e.last_stats["seconds"],
            "encoded",
            e.last_stats["encoded_rows"],
            "reused",
            e.last_stats["cache_hits"],
            "RSS KiB",
            status["peak_rss_kib"],
            flush=True,
        )
    # Re-run short input after long RoPE cache history; reused inputs must remain invariant.
    after = e.encode(check, 4096, use_cache=False)
    proof["after_long_history_max_abs_delta"] = float(np.max(np.abs(refs[0] - after)))
    assert proof["after_long_history_max_abs_delta"] < 1e-5
    save(out / "equivalence-proof.json", proof)
    # Prefix arm is explicit and never shares code vector identity.
    pref = e.encode(check, 1024, role="nl_query", use_cache=False)
    code = e.encode(check, 1024, use_cache=False)
    smoke = {
        "source_rows": check_ids,
        "query_prefix": "Represent this query for searching relevant code: ",
        "prefix_code_cosine": (pref * code).sum(1).tolist(),
        "prefix_max_abs_delta": float(np.max(np.abs(pref - code))),
        "identity_cosines": (code * code).sum(1).tolist(),
        "pairwise_cosine": (code @ code.T).tolist(),
        "purpose": "Numerical/semantic sanity only: native inputs and prefix effect, no gold labels or recall estimate.",
    }
    assert smoke["prefix_max_abs_delta"] > 1e-5
    save(out / "semantic-smoke.json", smoke)
    status.update(
        status="complete",
        total_seconds=time.perf_counter() - started,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        equivalence_proof="equivalence-proof.json",
        semantic_smoke="semantic-smoke.json",
    )
    save(out / "status.json", status)
    save(out / "output-hashes.json", {f.name: file_hash(f) for f in out.glob("*.npy")})
    print("complete", status["total_seconds"], flush=True)


if __name__ == "__main__":
    try:
        run()
    except Exception:
        (HERE / "logs" / "preflight-failure.txt").write_text(traceback.format_exc())
        raise
