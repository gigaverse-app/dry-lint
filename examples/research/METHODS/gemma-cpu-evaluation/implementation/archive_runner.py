# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B905, I001, UP017
"""Resumable, outcome-blind allocation runner. One local encoder, persistent exact-input cache."""

from __future__ import annotations
from _recovery_paths import recovery_path
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
import traceback
from gemma_adapter import HERE, sha_file, digest, LIMITS
from gemma_variants import EfficientGemmaEncoder

OUT = HERE / "archive"
RANK_PY = recovery_path("jobs/recall-promotion/.venv/bin/python")
CACHE = HERE / "openhands/bfloat16-t4/vectors.sqlite"


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2) + "\n")
    tmp.replace(path)


def event(kind, **details):
    record = {"timestamp": now(), "kind": kind, **details}
    with (OUT / "events.jsonl").open("a") as f:
        f.write(json.dumps(record) + "\n")
    print(json.dumps(record), flush=True)


def rank(receipt):
    command = [RANK_PY, str(HERE / "ranking/rank_harness.py"), "--method", "worker", "--matrix-receipt", str(receipt)]
    with (OUT / "ranking.log").open("a") as log:
        p = subprocess.run(
            command, stdout=log, stderr=subprocess.STDOUT, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        )
    # Preserve encoding and continue the frozen allocation if a non-encoding rank operation fails.
    event("rank_finished", receipt=str(receipt), returncode=p.returncode, command=command)


def existing_receipt(path, panel, contract, limit):
    if not path.exists():
        return False
    r = json.loads(path.read_text())
    if r.get("status") != "complete" or r.get("contract_sha256") != contract or r.get("max_length") != limit:
        return False
    if r["functions_sha256"] != panel["functions_sha256"] or r["background_sha256"] != panel["background_sha256"]:
        return False
    if sha_file(r["matrix_path"]) != r["matrix_sha256"]:
        raise ValueError(f"Corrupt complete matrix: {path}")
    return True


def main():
    OUT.mkdir(exist_ok=True)
    lock = (OUT / "runner.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert (HERE / "openhands/bfloat16-t4/COMPLETE.json").exists(), "Finish allocated OpenHands preflight first"
    assert (HERE / "OPENHANDS-FORECAST.json").exists(), "Publish actual OpenHands runtime and archive forecast first"
    plan_path = HERE / "allocation-through58.json"
    allocation = json.loads(plan_path.read_text())
    plan = allocation["plan"]
    assert len(plan) == 58 and [p["order"] for p in plan] == list(range(1, 59))
    assert plan[-1]["cumulative_unique_source_bodies"] == 151481
    panels = {p["cohort_id"]: p for p in map(json.loads, (HERE / "ranking/panels.jsonl").read_text().splitlines())}
    expected = json.loads((HERE / "throughput/bfloat16-t4/result.json").read_text())["contract_sha256"]
    attempt = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    attempt_dir = OUT / "attempts" / attempt
    attempt_dir.mkdir(parents=True)
    event(
        "started",
        attempt=attempt,
        pid=os.getpid(),
        plan_sha256=sha_file(plan_path),
        runner_sha256=sha_file(__file__),
        max_order=58,
        provider_calls=0,
    )
    save(
        OUT / "PROCESS.json",
        {
            "attempt": attempt,
            "pid_in_process_namespace": os.getpid(),
            "started": now(),
            "executable": sys.executable,
            "command": sys.argv,
            "stop_file": str(OUT / "STOP"),
            "resume_command": ".lab-results/run.sh .lab-results/archive_runner.py",
        },
    )
    encoder = EfficientGemmaEncoder(dtype="bfloat16", threads=4)
    assert encoder.contract_sha256 == expected
    encoder.enable_cache(CACHE, HERE / "throughput/bfloat16-t4/equivalence-proof.json")
    encoder.cache.execute("PRAGMA journal_mode=WAL")
    encoder.cache.execute("PRAGMA busy_timeout=30000")
    save(OUT / "encoder-contract.json", encoder.contract)
    np = encoder.np
    index = []
    session_start = time.perf_counter()
    physical = 0
    physical_seconds = 0.0
    current_sources = set()
    openhands = json.loads((HERE / "OPENHANDS-MATRICES.json").read_text())["receipts"]
    prior = {
        (r["cohort_id"], r["max_length"]): (path, r) for path in openhands for r in [json.loads(Path(path).read_text())]
    }
    for p in plan:
        cid = p["cohort_id"]
        panel = panels[cid]
        assert panel["functions_sha256"] == p["functions_sha256"]
        assert sha_file(p["functions_path"]) == p["functions_sha256"]
        rows = [json.loads(s) for s in Path(p["functions_path"]).read_text().splitlines()]
        assert len(rows) == p["documents"]
        ordered_hashes = [hashlib.sha256(r["code"].encode()).hexdigest() for r in rows]
        docs = [json.loads(s) for s in Path(panel["documents_path"]).read_text().splitlines()]
        assert len(docs) == len(rows) and all(h == d["source_sha256"] for h, d in zip(ordered_hashes, docs))
        current_sources.update(ordered_hashes)
        unique = {h: r["code"] for h, r in zip(ordered_hashes, rows)}
        folder = OUT / "panels" / cid
        folder.mkdir(parents=True, exist_ok=True)
        save(
            folder / "source-order.json",
            {
                "functions_sha256": p["functions_sha256"],
                "ordered_source_sha256": ordered_hashes,
                "order_digest": digest(ordered_hashes),
            },
        )
        # Stable source-hash order, independent of labels, ranks or model scores.
        keys = sorted(unique)
        for limit in LIMITS:
            receipt_path = folder / f"receipt-{limit}.json"
            if (cid, limit) in prior and not receipt_path.exists():
                source, r = prior[(cid, limit)]
                r = {**r, "plan_order": p["order"], "reused_openhands_receipt": source}
                save(receipt_path, r)
            if existing_receipt(receipt_path, p, expected, limit):
                index.append(str(receipt_path))
                save(
                    OUT / "MATRICES.json",
                    {"status": "running", "receipts": index, "updated": now(), "plan_sha256": sha_file(plan_path)},
                )
                rank(receipt_path)
                event("reused_complete_matrix", order=p["order"], limit=limit, receipt=str(receipt_path))
                continue
            arm_start = time.perf_counter()
            vectors = {}
            records = {}
            hits = 0
            arm_inference = 0.0
            timing = attempt_dir / f"{cid}-{limit}.jsonl"
            with timing.open("w") as log:
                for i, h in enumerate(keys):
                    if (OUT / "STOP").exists():
                        save(
                            OUT / "PROGRESS.json",
                            {
                                "status": "stopped_at_checkpoint",
                                "timestamp": now(),
                                "attempt": attempt,
                                "order": p["order"],
                                "cohort_id": cid,
                                "limit": limit,
                                "done": i,
                                "total": len(keys),
                                "receipts": len(index),
                            },
                        )
                        event("stopped_at_checkpoint", order=p["order"], limit=limit, done=i)
                        return
                    vector = encoder.encode([unique[h]], limit)[0]
                    rec = encoder.last_records[0]
                    assert rec["source_sha256"] == h
                    vectors[h] = vector
                    records[h] = rec
                    hits += rec["cache_hit"]
                    arm_inference += rec["inference_seconds"]
                    if not rec["cache_hit"]:
                        physical += 1
                        physical_seconds += rec["inference_seconds"]
                    log.write(json.dumps({"timestamp": now(), **rec}) + "\n")
                    if i % 50 == 0 or i + 1 == len(keys):
                        log.flush()
                        elapsed = time.perf_counter() - session_start
                        mean = physical_seconds / physical if physical else None
                        pending = max(0, 151481 - len(current_sources)) + max(0, len(keys) - i - 1)
                        forecast = json.loads((HERE / "OPENHANDS-FORECAST.json").read_text())
                        progress = {
                            "status": "running",
                            "timestamp": now(),
                            "attempt": attempt,
                            "order": p["order"],
                            "max_order": 58,
                            "cohort_id": cid,
                            "repository": p["repository"],
                            "limit": limit,
                            "done": i + 1,
                            "total_unique_panel": len(keys),
                            "panel_occurrences": len(rows),
                            "panel_cache_hits": hits,
                            "complete_matrices": len(index),
                            "session_physical_vectors": physical,
                            "session_inference_seconds": physical_seconds,
                            "session_elapsed_seconds": elapsed,
                            "mean_seconds_per_new_vector": mean,
                            "remaining_1k_bodies_upper_bound": pending,
                            "eta_hours_1k_proxy": pending * mean / 3600
                            if mean
                            else forecast["archive151481_1k_hours_proxy"],
                            "eta_note": "Proxy for remaining1K bodies; longer changed inputs and ranking add work. Mixed arm/sample distributions, not completion guarantee.",
                            "source_coverage_at_current_panel": len(current_sources),
                            "cached_total_entries": encoder.cache.execute("SELECT COUNT(*) FROM vectors").fetchone()[0],
                        }
                        save(OUT / "PROGRESS.json", progress)
                        event(
                            "progress",
                            **{
                                k: progress[k]
                                for k in (
                                    "order",
                                    "limit",
                                    "done",
                                    "total_unique_panel",
                                    "complete_matrices",
                                    "session_physical_vectors",
                                    "eta_hours_1k_proxy",
                                )
                            },
                        )
            matrix = np.stack([vectors[h] for h in ordered_hashes])
            assert matrix.shape == (len(rows), 768) and np.isfinite(matrix).all()
            matrix_path = folder / f"embeddings-{limit}.npy"
            tmp = folder / f"embeddings-{limit}.partial.npy"
            np.save(tmp, matrix)
            tmp.replace(matrix_path)
            token_path = folder / f"tokens-{limit}.jsonl"
            with token_path.open("w") as f:
                for i, h in enumerate(ordered_hashes):
                    f.write(json.dumps({"row": i, **records[h]}) + "\n")
            matrix_hash = sha_file(matrix_path)
            method = f"gemma2-bf16-t4-symmetric-{limit}"
            receipt = {
                "schema": 1,
                "status": "complete",
                "created": now(),
                "attempt": attempt,
                "method": method,
                "model": encoder.contract["model"],
                "revision": encoder.contract["revision"],
                "contract_sha256": expected,
                "model_contract_digest": expected,
                "model_contract": encoder.contract,
                "contract_path": str(OUT / "encoder-contract.json"),
                "cohort_id": cid,
                "plan_order": p["order"],
                "plan_sha256": sha_file(plan_path),
                "repository": p["repository"],
                "source_revision": p["revision"],
                "background_sha256": p["background_sha256"],
                "functions_path": p["functions_path"],
                "functions_sha256": p["functions_sha256"],
                "source_order_path": str(folder / "source-order.json"),
                "input_row_order_digest": digest(ordered_hashes),
                "matrix_path": str(matrix_path),
                "matrix_sha256": matrix_hash,
                "document_matrix_path": str(matrix_path),
                "document_matrix_sha256": matrix_hash,
                "query_matrix_path": str(matrix_path),
                "query_matrix_sha256": matrix_hash,
                "rows": len(rows),
                "dimensions": 768,
                "token_limit": limit,
                "max_length": limit,
                "mode": "symmetric",
                "prefix": encoder.prefix,
                "dtype": "float32",
                "inference_dtype": "bfloat16",
                "threads": 4,
                "batch_size": 1,
                "missing_rows": 0,
                "finite": True,
                "norm_max_error": float(np.abs(np.linalg.norm(matrix, axis=1) - 1).max()),
                "truncated_rows": sum(records[h]["truncated"] for h in ordered_hashes),
                "unique_panel_bodies": len(keys),
                "cache_hit_unique_bodies": hits,
                "wall_seconds": time.perf_counter() - arm_start,
                "inference_seconds": arm_inference,
                "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "tokens_path": str(token_path),
                "tokens_sha256": sha_file(token_path),
                "attempt_timing_path": str(timing),
                "attempt_timing_sha256": sha_file(timing),
                "command": ".lab-results/run.sh .lab-results/archive_runner.py",
                "runner_sha256": sha_file(__file__),
                "provider_calls": 0,
                "accuracy_claims": None,
            }
            save(receipt_path, receipt)
            index.append(str(receipt_path))
            save(
                OUT / "MATRICES.json",
                {"status": "running", "receipts": index, "updated": now(), "plan_sha256": sha_file(plan_path)},
            )
            event(
                "matrix_ready",
                order=p["order"],
                limit=limit,
                receipt=str(receipt_path),
                inference_seconds=arm_inference,
                cache_hits=hits,
            )
            rank(receipt_path)
    assert len(index) == 58 * 3
    save(
        OUT / "MATRICES.json",
        {"status": "complete", "receipts": index, "updated": now(), "plan_sha256": sha_file(plan_path)},
    )
    save(
        OUT / "COMPLETE.json",
        {
            "completed": now(),
            "panels": 58,
            "matrices": 174,
            "unique_source_bodies": len(current_sources),
            "accepted_coverage": 593,
            "mapped_function_records_coverage": 816,
            "accepted_denominator": 593,
            "mapped_function_records_denominator": 822,
            "session_physical_vectors": physical,
            "session_inference_seconds": physical_seconds,
            "provider_calls": 0,
            "note": "Coverage is source/ranking readiness, not accuracy or independent-family count.",
        },
    )
    event("allocation_complete", matrices=174)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        OUT.mkdir(exist_ok=True)
        save(OUT / "FAILURE.json", {"timestamp": now(), "traceback": traceback.format_exc(), "command": sys.argv})
        raise
