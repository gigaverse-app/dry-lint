"""Portable table replay, mutation sensitivity and worked-source proof checks."""

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent


def main():
    validation = PACKAGE / "validation"
    validation.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=validation) as tmp:
        root = Path(tmp)
        relocated = root / "isolated-package"
        relocated.mkdir()
        for name in ["data", "expected"]:
            shutil.copytree(PACKAGE / name, relocated / name)
        shutil.copyfile(PACKAGE / "replay.py", relocated / "replay.py")
        result = subprocess.run(
            [sys.executable, "-I", str(relocated / "replay.py"), "--out", str(root / "replayed"), "--verify"],
            check=True,
            capture_output=True,
            text=True,
            cwd=root,
        )
        # The isolated subprocess has only stdlib plus the relocated recordings; no lab import.
        spec = importlib.util.spec_from_file_location("replay_under_test", relocated / "replay.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        path = relocated / "data/blocks-regression.jsonl"
        rows = module.read(path)
        # Change every lineage alias of one missed labeled pair. A real replay must change its gained count.
        target = next(
            r
            for r in rows
            if r["label"] == "duplicate" and not any(d["original"]["funded"]["paired"] for d in r["directions"])
        )
        for r in rows:
            if (r["cohort_id"], r["pair_id"]) == (target["cohort_id"], target["pair_id"]):
                for d in r["directions"]:
                    d["helper"]["funded"]["paired"] = True
        module.jsonl(path, rows)
        table, *_ = module.recompute(relocated / "data", root / "mutated")
        affected = next(
            r
            for r in table
            if r["method"] == "blocks" and r["cohort_id"] == target["cohort_id"] and r["label"] == "duplicate"
        )
        assert affected["gained_pairs"] == 1
        mismatch = subprocess.run(
            [sys.executable, "-I", str(relocated / "replay.py"), "--out", str(root / "mutated-check"), "--verify"],
            capture_output=True,
        )
        assert mismatch.returncode != 0
    files = 0
    for case in json.loads((PACKAGE / "worked-cases/manifest.json").read_text()):
        for f in case["functions"]:
            full = (PACKAGE / f["full_file"]).read_bytes()
            body = (PACKAGE / f["full_function"]).read_bytes()
            assert hashlib.sha256(full).hexdigest() == f["file_sha256"]
            assert hashlib.sha256(body).hexdigest() == f["source_sha256"]
            assert hashlib.sha1(b"blob " + str(len(full)).encode() + b"\0" + full).hexdigest() == f["git_blob_sha1"]
            assert (PACKAGE / f["license"]).is_file()
            files += 1
    for r in json.loads((PACKAGE / "licenses/provenance.json").read_text()):
        assert hashlib.sha256((PACKAGE / r["export_path"]).read_bytes()).hexdigest() == r["sha256"]
    receipt = {
        "status": "passed",
        "isolated_replay": json.loads(result.stdout),
        "mutation_changes_gained_pairs": True,
        "mutation_fails_expected_comparison": True,
        "worked_functions_verified": files,
        "dependencies": "standard library only",
        "network_or_provider_calls": 0,
    }
    (validation / "replay-tests.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
