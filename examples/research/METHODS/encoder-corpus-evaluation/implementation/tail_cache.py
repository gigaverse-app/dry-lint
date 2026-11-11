# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: I001
"""Read frozen vectors by recorded owner/ordinal; never zip against omitted spans."""

from common import jl, digest, sha
import numpy as np


def read_tail_cache(panel):
    path = panel["minilm_tail_matrix_path"]
    if panel.get("minilm_tail_matrix_sha256"):
        assert sha(path) == panel["minilm_tail_matrix_sha256"]
    rows = jl(panel["minilm_tail_views_path"])
    by = {r["position"]: r for r in rows}
    with np.load(path, allow_pickle=False) as data:
        vectors = data["vectors"].copy()
        owners = data["owners"]
        if "ordinals" in data.files:
            indices = list(zip(owners, data["ordinals"], strict=True))
        else:
            indices = [(r["position"], j) for r in rows for j in range(len(r["views"]))]
            assert [int(i) for i in owners] == [i for i, j in indices]
        assert len(indices) == len(vectors)
        texts = []
        for owner, ordinal in indices:
            r = by[int(owner)]
            assert r.get("native", True)
            v = r["views"][int(ordinal)]
            assert digest(v["text"]) == v["input_sha256"]
            texts.append(v["text"])
    assert vectors.ndim == 2 and vectors.shape[1] == 384 and np.isfinite(vectors).all()
    assert not len(vectors) or np.max(np.abs(np.linalg.norm(vectors, axis=1) - 1)) < 1e-4
    return texts, vectors
