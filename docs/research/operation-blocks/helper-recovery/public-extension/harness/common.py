# ruff: noqa: E402 -- freeze source and thread settings before imports.
"""Exact public-pin extension. Only this artifact directory is writable."""

import os
import sys
from pathlib import Path

for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "2"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True
ROOT = Path("/home/researcher/dry-lint-round")
HERE = Path(__file__).resolve().parent
OLD = ROOT / "jobs/experiment-cpu-embeddings/.lab-results"
PR = ROOT / "jobs/recall-promotion"
SHARED = OLD / "full-corpus/shared-inputs/9bfa15c84eb72dd2"
sys.path.insert(0, str(HERE / "frozen-pr109/src" if (HERE / "frozen-pr109/src").exists() else PR / "src"))
import hashlib
import json

from dry_lint.bench_background import BenchBackground
from dry_lint.models import Function


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return [json.loads(s) for s in Path(path).open() if s.strip()]


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def jsonl(path, rows):
    Path(path).write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))


def folders():
    return sorted((HERE / "cohorts").glob("*/manifest.json"))


def load(folder):
    manifest = json.loads((folder / "manifest.json").read_text())
    proof = manifest["repository"]["background_proof"]
    data = Path(proof["path"]).read_bytes()
    assert sha(data) == proof["sha256"]
    bg = BenchBackground.decode(data)
    raw = read(folder / "functions.jsonl")
    policy = read(folder / "functions-policy-resolver-v1.jsonl")
    assert sha((folder / "functions.jsonl").read_bytes()) == manifest["functions_jsonl_sha256"]
    assert sha((folder / "functions-policy-resolver-v1.jsonl").read_bytes()) == manifest["policy_sha256"]
    fs = []
    native = []
    for r, p, d in zip(raw, policy, bg.documents, strict=True):
        f = Function.model_validate(p["function"] or {**r, "line": 0, "end_line": 0})
        assert f.qualname == d.id
        if p["function"]:
            assert sha(f.code.encode()) == d.source_sha256
        f.tokens = d.tokens()
        fs.append(f)
        native.append(p["function"] is not None)
    return manifest, bg, fs, native
