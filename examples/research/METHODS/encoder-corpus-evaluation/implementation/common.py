# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, I001
"""Local-only research I/O; never load environment credentials or provider clients."""

from _recovery_paths import recovery_path
import gzip, hashlib, json, os, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(recovery_path(""))
REF = "a10a288530c4aa25711c7ec3b86ac164d182899a"
os.environ["OMP_NUM_THREADS"] = "2"
os.environ["OPENBLAS_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["CUDA_VISIBLE_DEVICES"] = ""
sys.path.insert(0, str(HERE / "runtime/src"))


def sha(p):
    with Path(p).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def digest(s):
    return hashlib.sha256(s.encode()).hexdigest()


def jl(p):
    op = gzip.open if str(p).endswith(".gz") else open
    with op(p, "rt") as f:
        return [json.loads(s) for s in f if s.strip()]


def write(p, x):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    raw = (
        "".join(json.dumps(r, sort_keys=True, allow_nan=False) + "\n" for r in x)
        if p.suffix == ".jsonl"
        else json.dumps(x, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(raw)
    tmp.replace(p)


def ident(f):
    return f["path"] + "::" + ((f.get("owner") + ".") if f.get("owner") else "") + f["name"]
