# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: F401, I001
"""Publish only complete matrices; unfinished memmaps never become scoring inputs."""

import json
from pathlib import Path
from coderank_adapter import file_hash, digest, canonical, setup_environment
from preflight import save

HERE = Path(__file__).resolve().parent


def main():
    setup_environment()
    import numpy as np

    published = []
    for prefix in ("a068703e", "ebd00315"):
        folder = HERE / f"openhands-{prefix}"
        if not (folder / "receipt.json").exists():
            continue
        record = json.loads((folder / "receipt.json").read_text())
        panel = json.loads((HERE / f"openhands-{prefix}-panel.json").read_text())
        assert record["source"]["source_sha256"] == panel["functions_sha256"]
        for limit, arm in record["arms"].items():
            if sum(c["rows"] for c in arm["chunks"]) != panel["functions"]:
                continue
            matrix = folder / f"embeddings-{limit}.npy"
            vectors = np.load(matrix, mmap_mode="r", allow_pickle=False)
            assert vectors.shape == (panel["functions"], 768) and vectors.dtype == np.float32
            assert np.isfinite(vectors).all() and np.max(np.abs(np.linalg.norm(vectors, axis=1) - 1)) < 1e-5
            receipt = {
                "schema": 1,
                "method": f"coderank-sdpa-bf16-t4-singleton-{limit}",
                "cohort_id": panel["cohort_id"],
                "repository": panel["repository"],
                "revision": panel["revision"],
                "background_sha256": panel["background_sha256"],
                "functions_sha256": panel["functions_sha256"],
                "token_limit": int(limit),
                "document_matrix_path": str(matrix),
                "document_matrix_sha256": file_hash(matrix),
                "query_matrix_path": str(matrix),
                "query_matrix_sha256": file_hash(matrix),
                "dimensions": list(vectors.shape),
                "contract_digest": record["contract_digest"],
                "contract": record["contract"],
                "row_order_digest": record["source"]["row_order_digest"],
                "source_hashes": record["source"]["source_hashes"],
                "source_receipt": str(folder / "receipt.json"),
                "arm_seconds": arm["seconds"],
                "encoded_rows": arm["encoded_rows"],
                "cache_hits": arm["cache_hits"],
                "cross_limit_hits": arm["cross_limit_hits"],
                "equivalence_proof": str(folder / "equivalence-proof.json"),
                "precision_evidence": "BF16 alternate; not FP32 exact; parity documented in VARIANT-DECISION.json",
                "ready": True,
            }
            dest = folder / f"matrix-{limit}.json"
            save(dest, receipt)
            published.append(
                {
                    "cohort_id": panel["cohort_id"],
                    "token_limit": int(limit),
                    "receipt": str(dest),
                    "sha256": file_hash(dest),
                }
            )
    save(HERE / "MATRICES.json", published)
    print(json.dumps(published))


if __name__ == "__main__":
    main()
