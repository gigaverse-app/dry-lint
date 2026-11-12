# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B904, F401, I001, UP017
"""Resumable, single-encoder, allocation-bounded runner. Publishes only complete atomic matrices."""

import datetime
import fcntl
import json
import os
from pathlib import Path
import sys
import time
import traceback
from coderank_adapter import canonical, digest, file_hash, HERE
from cpu_variant import CPUVariant
from preflight import save


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def read(path):
    return json.loads(path.read_text())


def publish_registry():
    records = []
    for p in sorted(HERE.glob("*/matrix-*.json")):
        r = read(p)
        if r.get("ready"):
            records.append(
                {
                    "cohort_id": r["cohort_id"],
                    "token_limit": r["token_limit"],
                    "receipt": str(p),
                    "sha256": file_hash(p),
                }
            )
    save(HERE / "BATCH-MATRICES.json", records)
    return records


def main():
    lock = (HERE / "batch.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    lock.write(str(os.getpid()))
    lock.flush()
    started = time.time()
    plan = read(HERE / "batch-source-plan.json")
    entries = plan["plan"]
    assert len(entries) == 58
    assert file_hash(HERE / "ordered-full-background-plan.json") == plan["source_plan_sha256"]
    status = {
        "schema": 1,
        "status": "waiting_for_allocated_preflight",
        "pid": os.getpid(),
        "started_utc": utc(),
        "updated_utc": utc(),
        "source_plan_sha256": file_hash(HERE / "batch-source-plan.json"),
        "allocation_through_order": 58,
        "authorized_unique_bodies": 151481,
        "completed_panels": [],
        "completed_matrices": [],
        "errors": [],
    }
    save(HERE / "BATCH-STATUS.json", status)
    while True:
        required = [
            HERE / "openhands-a068703e/receipt.json",
            HERE / "openhands-ebd00315/receipt.json",
            HERE / "preflight-bf16/status.json",
        ]
        if all(p.exists() and read(p).get("status") == "complete" for p in required):
            break
        if (HERE / "logs/efficient-preflight-failure.txt").exists():
            raise RuntimeError("Required efficient preflight failed; stop before broad encoding")
        if time.time() - started > 1800:
            raise RuntimeError("Prerequisite timeout; no panels skipped")
        status["updated_utc"] = utc()
        save(HERE / "BATCH-STATUS.json", status)
        time.sleep(10)
    # Whole-background costs must exist before any larger panel starts.
    openhands = [read(p) for p in required[:2]]
    save(
        HERE / "OPENHANDS-COST.json",
        {
            "panels": [
                {
                    "rows": x["source"]["rows"],
                    "unique_bodies": x["source"]["unique_full_source_hashes"],
                    "total_seconds": x["total_seconds"],
                    "load_seconds": x["load_seconds"],
                    "peak_rss_kib": x["peak_rss_kib"],
                    "arms": {
                        k: {q: a[q] for q in ("seconds", "encoded_rows", "cache_hits", "cross_limit_hits")}
                        for k, a in x["arms"].items()
                    },
                }
                for x in openhands
            ],
            "unique_union_bodies": 2309,
            "forecast": read(HERE / "cost-projection-steady.json"),
            "forecast_note": "Higher-limit cost from preflight-bf16; corpus mix estimate, not completed broad evidence.",
        },
    )
    e = CPUVariant(
        cache_path=HERE / "shared-vectors.sqlite3",
        threads=4,
        precision="bf16",
        attention="sdpa",
        batch_mode="singleton",
    )
    proof = read(HERE / "preflight-bf16/equivalence-proof.json")
    assert (
        proof["contract_digest"] == e.contract_digest
        and proof["max_abs_delta"] < 1e-5
        and proof["after_long_history_max_abs_delta"] < 1e-5
    )
    e.allow_cross_limit_reuse = True
    import numpy as np

    panels = {
        p["cohort_id"]: p for p in [json.loads(x) for x in (HERE / "evaluation/panels.jsonl").read_text().splitlines()]
    }
    baseline_seen = e.db.execute(
        "SELECT COUNT(DISTINCT source_hash) FROM arms WHERE contract=? AND role=? AND limit_tokens=1024",
        (e.contract_digest, "code"),
    ).fetchone()[0]
    status.update(
        status="running",
        contract_digest=e.contract_digest,
        baseline_cached_source_bodies=baseline_seen,
        encoder_load_seconds=e.load_seconds,
    )
    active_start = time.time()
    inference_total = 0.0
    for entry in entries:
        panel = panels[entry["cohort_id"]]
        path = Path(entry["functions_path"])
        assert file_hash(path) == entry["functions_sha256"] == panel["functions_sha256"]
        assert entry["background_sha256"] == panel["background_sha256"]
        prefix = entry["cohort_id"][3:11]
        folder = HERE / f"openhands-{prefix}" if entry["order"] <= 2 else HERE / "backgrounds" / entry["cohort_id"]
        folder.mkdir(parents=True, exist_ok=True)
        source = [json.loads(x) for x in path.read_text().splitlines()]
        assert len(source) == entry["documents"]
        texts = [r["code"] for r in source]
        hashes = [digest(t.encode()) for t in texts]
        docs = [json.loads(x) for x in Path(panel["documents_path"]).read_text().splitlines()]
        assert len(docs) == len(source)
        for r, d, h in zip(source, docs, hashes, strict=True):
            ident = r["path"] + "::" + ((r.get("owner") + ".") if r.get("owner") else "") + r["name"]
            assert ident == d["source_id"] and h == d["source_sha256"]
        counts = [
            len(ids)
            for ids in e.tokenizer(texts, add_special_tokens=True, truncation=False, padding=False, verbose=False)[
                "input_ids"
            ]
        ]
        source_record = folder / "source-order.json"
        save(
            source_record,
            {
                "source_path": str(path),
                "source_sha256": file_hash(path),
                "source_hashes": hashes,
                "row_order_digest": digest(canonical(hashes)),
                "tokens_before": counts,
                "rows": len(source),
            },
        )
        status.update(
            current_order=entry["order"],
            current_cohort=entry["cohort_id"],
            repository=entry["repository"],
            current_documents=len(source),
            updated_utc=utc(),
        )
        for limit in (1024, 2048, 4096):
            receipt_path = folder / f"matrix-{limit}.json"
            if receipt_path.exists():
                receipt = read(receipt_path)
                assert (
                    receipt["contract_digest"] == e.contract_digest
                    and receipt["functions_sha256"] == entry["functions_sha256"]
                )
                assert file_hash(receipt["document_matrix_path"]) == receipt["document_matrix_sha256"]
                status["completed_matrices"].append(str(receipt_path))
                continue
            attempt = utc().replace(":", "-")
            chunk_path = folder / f"chunks-{limit}-{attempt}.jsonl"
            temp = folder / f"embeddings-{limit}.partial.npy"
            final = folder / f"embeddings-{limit}.npy"
            matrix = np.lib.format.open_memmap(temp, mode="w+", dtype=np.float32, shape=(len(source), 768))
            order = sorted(range(len(source)), key=lambda i: (min(counts[i], limit), hashes[i], i))
            chunks = []
            pending = []
            tokens = 0
            for i in order:
                n = min(counts[i], limit)
                if pending and (len(pending) >= 128 or tokens + n > 8192):
                    chunks.append(pending)
                    pending = []
                    tokens = 0
                pending.append(i)
                tokens += n
            if pending:
                chunks.append(pending)
            arm = {"seconds": 0.0, "encoded_rows": 0, "cache_hits": 0, "cross_limit_hits": 0, "rows_completed": 0}
            arm_start = time.time()
            with chunk_path.open("w") as log:
                for ids in chunks:
                    first_by_hash = {}
                    for i in ids:
                        first_by_hash.setdefault(hashes[i], i)
                    unique_ids = list(first_by_hash.values())
                    encoded = e.encode([texts[i] for i in unique_ids], limit)
                    offset_by_hash = {hashes[i]: j for j, i in enumerate(unique_ids)}
                    matrix[ids] = encoded[[offset_by_hash[hashes[i]] for i in ids]]
                    stats = e.last_stats
                    stats["source_row_indices"] = unique_ids
                    stats["all_source_row_indices"] = ids
                    stats["within_chunk_exact_source_reuses"] = len(ids) - len(unique_ids)
                    stats["finished_utc"] = utc()
                    log.write(json.dumps(stats, sort_keys=True) + "\n")
                    log.flush()
                    matrix.flush()
                    for key in ("seconds", "encoded_rows", "cache_hits", "cross_limit_hits"):
                        arm[key] += stats[key]
                    arm["rows_completed"] += len(ids)
                    inference_total += stats["seconds"]
                    seen = e.db.execute(
                        "SELECT COUNT(DISTINCT source_hash) FROM arms WHERE contract=? AND role=? AND limit_tokens=1024",
                        (e.contract_digest, "code"),
                    ).fetchone()[0]
                    new_seen = seen - baseline_seen
                    eta = (time.time() - active_start) / new_seen * max(0, 151481 - seen) if new_seen > 20 else None
                    status.update(
                        status="running",
                        updated_utc=utc(),
                        current_limit=limit,
                        current_arm=arm.copy(),
                        current_arm_elapsed_seconds=time.time() - arm_start,
                        unique_source_bodies_seen=seen,
                        elapsed_seconds=time.time() - started,
                        inference_seconds=inference_total,
                        eta_seconds=eta,
                        eta_basis="observed elapsed / new unique source bodies, including completed higher arms; fluctuates with length mix",
                    )
                    save(HERE / "BATCH-STATUS.json", status)
                    if (HERE / "STOP-BATCH").exists():
                        raise RuntimeError("Explicit STOP-BATCH requested; cache checkpointed")
            assert np.isfinite(matrix).all() and np.max(np.abs(np.linalg.norm(matrix, axis=1) - 1)) < 1e-5
            del matrix
            temp.replace(final)
            receipt = {
                "schema": 1,
                "method": f"coderank-sdpa-bf16-t4-singleton-{limit}",
                "cohort_id": entry["cohort_id"],
                "repository": entry["repository"],
                "revision": entry["revision"],
                "background_sha256": entry["background_sha256"],
                "functions_sha256": entry["functions_sha256"],
                "token_limit": limit,
                "document_matrix_path": str(final),
                "document_matrix_sha256": file_hash(final),
                "query_matrix_path": str(final),
                "query_matrix_sha256": file_hash(final),
                "dimensions": [len(source), 768],
                "contract_digest": e.contract_digest,
                "contract": e.contract,
                "row_order_digest": digest(canonical(hashes)),
                "source_hashes_path": str(source_record),
                "source_hashes_sha256": file_hash(source_record),
                "token_counts_before_path": str(source_record),
                "tokens_after": [min(n, limit) for n in counts],
                "truncated_rows": sum(n > limit for n in counts),
                "chunks_path": str(chunk_path),
                "chunks_sha256": file_hash(chunk_path),
                "equivalence_proof": str(HERE / "preflight-bf16/equivalence-proof.json"),
                "precision_evidence": "BF16 alternate; FP32 parity separately measured",
                "started_unix": arm_start,
                "finished_utc": utc(),
                "arm_wall_seconds": time.time() - arm_start,
                **arm,
                "ready": True,
            }
            save(receipt_path, receipt)
            status["completed_matrices"].append(str(receipt_path))
            # The watcher reads this append-only publication list. Never includes partial matrices.
            with (HERE / "MATRIX-EVENTS.jsonl").open("a") as events:
                events.write(
                    json.dumps(
                        {
                            "utc": utc(),
                            "order": entry["order"],
                            "cohort_id": entry["cohort_id"],
                            "limit": limit,
                            "receipt": str(receipt_path),
                            "receipt_sha256": file_hash(receipt_path),
                        }
                    )
                    + "\n"
                )
            save(HERE / "BATCH-STATUS.json", status)
            registry = []
            for item in status["completed_matrices"]:
                rr = read(Path(item))
                registry.append(
                    {
                        "cohort_id": rr["cohort_id"],
                        "token_limit": rr["token_limit"],
                        "receipt": item,
                        "sha256": file_hash(item),
                    }
                )
            save(HERE / "MATRICES.json", registry)
            save(HERE / "BATCH-MATRICES.json", registry)
            print(
                json.dumps(
                    {
                        "event": "matrix_ready",
                        "order": entry["order"],
                        "limit": limit,
                        "receipt": str(receipt_path),
                        "arm": arm,
                    }
                ),
                flush=True,
            )
        status["completed_panels"].append(entry["cohort_id"])
        status["updated_utc"] = utc()
        save(HERE / "BATCH-STATUS.json", status)
        save(
            HERE / "BATCH-MATRICES.json", [{"receipt": r, "sha256": file_hash(r)} for r in status["completed_matrices"]]
        )
    status.update(status="complete", finished_utc=utc(), elapsed_seconds=time.time() - started, eta_seconds=0)
    save(HERE / "BATCH-STATUS.json", status)
    print("all 58 authorized panels complete", flush=True)


if __name__ == "__main__":
    try:
        main()
    except BlockingIOError:
        with (HERE / "logs/duplicate-launches.jsonl").open("a") as f:
            f.write(json.dumps({"utc": utc(), "pid": os.getpid(), "status": "rejected_existing_runner_lock"}) + "\n")
        raise SystemExit(2)
    except BaseException as exc:
        p = HERE / "BATCH-STATUS.json"
        s = read(p) if p.exists() else {}
        s.update(
            status="failed",
            updated_utc=utc(),
            error_type=type(exc).__name__,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        save(p, s)
        with (HERE / "logs/batch-failures.jsonl").open("a") as f:
            f.write(json.dumps(s) + "\n")
        raise
