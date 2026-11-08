# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, E402, I001
"""Export pinned original TFIDF sparse vectors; no new SVD fitting."""

from _recovery_paths import recovery_path
import os, sys

sys.dont_write_bytecode = True
for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[k] = "2"
if hasattr(os, "sched_getaffinity"):
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
assert os.environ.get("PYTHONHASHSEED") == "0", "Frozen feature order requires PYTHONHASHSEED=0"
import pathlib, json, hashlib

H = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path(recovery_path(""))
SRC = ROOT / "jobs/encoder-corpus-evaluation/.lab-results/runtime/src"
sys.path.insert(0, str(SRC))
from dry_lint.bench_background import BenchBackground

p = json.loads((H / "inputs/graphs/bg-ebd0031534c954e5/RECEIPT.json").read_text())["source"]
identity = json.loads((ROOT / "jobs/experiment-vector-expansion/.lab-results/latent-cache-identity.json").read_text())
assert (
    p["background_sha256"] == identity["background"]["sha256"]
    and p["revision"] == identity["revision"]
    and p["scope"] == identity["scope"]
)
raw = pathlib.Path(p["background_path"]).read_bytes()
assert hashlib.sha256(raw).hexdigest() == p["background_sha256"]
bg = BenchBackground.decode(raw)
ix = bg.index()
terms = list(ix.idf)
pos = {t: i for i, t in enumerate(terms)}
rows = []
for i, d in enumerate(bg.documents):
    rows.append(
        {
            "position": i,
            "source_id": d.id,
            "source_sha256": d.source_sha256,
            "vector": [[pos[t], v] for t, v in ix.vector(d.tokens()).items()],
        }
    )
(H / "tfidf-vectors.json").write_text(
    json.dumps({"source": p, "terms": terms, "rows": rows, "shape": [len(rows), len(terms)], "product_src": str(SRC)})
    + "\n"
)
print("exported sparse", len(rows), len(terms), "no fit")
