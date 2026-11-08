# ruff: noqa: E401, E402, E741, F401, F403, F405, I001, B007
# Frozen experiment adapters intentionally preserve import order and shared wildcard exports.
"""Portable cached-input replay support. DATA_DIR is supplied by replay.py."""

import os, sys, json, gzip, hashlib
from pathlib import Path

for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[k] = "2"
import numpy as np
from dry_lint.bench_background import BenchBackground
from dry_lint.models import Function

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ["RECALL_REPLAY_DATA"])
OLD = DATA / "no-model-required"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def canonical(x):
    return json.dumps(x, sort_keys=True, separators=(",", ":")).encode()


def read(p):
    p = Path(p)
    with gzip.open(p, "rt") if p.suffix == ".gz" else p.open() as f:
        return [json.loads(s) for s in f if s.strip()]


def dump(p, x):
    Path(p).write_text(json.dumps(x, sort_keys=True, indent=2) + "\n")


def ref(p):
    return {"sha256": sha(Path(p).read_bytes())}


def load(folder):
    m = json.loads((folder / "manifest.json").read_text())
    bg = BenchBackground.decode((folder / "background.json.gz").read_bytes())
    fs = []
    native = []
    raw = read(folder / "functions.jsonl.gz")
    policy = read(folder / "policy.jsonl.gz")
    for r, p, d in zip(raw, policy, bg.documents, strict=True):
        f = Function.model_validate(p["function"] or {**r, "line": 0, "end_line": -1})
        assert f.qualname == d.id and sha(f.code.encode()) == d.source_sha256
        f.tokens = d.tokens()
        fs.append(f)
        native.append(p["function"] is not None)
    return m, bg, fs, native


def pair_id(repo, c):
    return sha(
        canonical(
            [
                repo,
                sorted(
                    (f["path"], f.get("owner") or "", f["name"], sha(f["code"].encode()))
                    for f in (c["new"], c["existing"])
                ),
            ]
        )
    )
