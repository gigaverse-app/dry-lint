"""Stage unchanged research harness in a new directory; require external frozen corpus.

No acquisition and no provider calls. This optional command is NOT needed for replay.py.
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
ROOT = Path("/home/researcher/dry-lint-round")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="New empty run directory; never the original lab")
    parser.add_argument(
        "--execute", action="store_true", help="After preflight, run full offline extraction and CPU inference"
    )
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists():
        parser.error("--out must not exist; existing results are immutable")
    dependencies = json.loads((PACKAGE / "provenance/dependencies.json").read_text())
    assert sys.version.split()[0] == dependencies["native_rerun_python"].split()[0], "Use the recorded Python version"
    for name, version in dependencies["native_packages"].items():
        assert importlib.metadata.version(name) == version, (name, version)
    proofs = json.loads((PACKAGE / "provenance/input-proofs.json").read_text())
    for path, digest in proofs["files"].items():
        p = Path(path)
        assert p.is_file(), "Missing external input: " + path
        if "/shared-inputs/" in path:
            assert sha(p) == digest, "Shared 617-row/79-background inventory changed: " + path
    contexts = [json.loads(line) for line in (PACKAGE / "data/contexts.jsonl").read_text().splitlines()]
    env = {
        **os.environ,
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "OMP_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "2",
        "MKL_NUM_THREADS": "2",
        "TOKENIZERS_PARALLELISM": "false",
        "ORT_DISABLE_TELEMETRY": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    }
    for c in contexts:
        p = Path(c["background_required_at_original_location"])
        assert p.is_file() and sha(p) == c["background_sha256"], "Missing/mismatched full frozen background: " + str(p)
        subprocess.run(
            [
                "git",
                "-C",
                c["git_required_at_original_location"],
                "cat-file",
                "-e",
                c["repository"]["revision"] + "^{commit}",
            ],
            check=True,
            env=env,
        )
    encoder = json.loads((PACKAGE / "provenance/policies.json").read_text())["cpu"]["encoder"]
    model = ROOT / "jobs/experiment-cpu-embeddings/.lab-results/model-cache"
    for name, digest in encoder["artifacts"].items():
        assert sha(model / name) == digest, "Existing pinned model artifact required: " + name
    if not args.execute:
        print(
            "Preflight passed: all external full-corpus inputs, exact Git pins, dependencies and cached model artifacts present. No writes or inference."
        )
        return
    shutil.copytree(PACKAGE / "harness", out)
    frozen = json.loads((PACKAGE / "provenance/frozen-source-manifest.json").read_text())
    for r in frozen["recipes"]:
        r["output"] = str(out / Path(r["output"]).name)
    (out / "frozen-source-manifest.json").write_text(json.dumps(frozen, indent=2, sort_keys=True) + "\n")
    # Only recipe output locations in the receipt change; the harness and baseline source stay byte-exact.
    for r in json.loads((PACKAGE / "provenance/export.json").read_text())["harness"]:
        assert sha(out / Path(r["path"]).name) == r["source_sha256"]
    env["PYTHONPATH"] = str(out / "frozen-pr109/src") + os.pathsep + dependencies["numeric_site_packages"]
    commands = []
    for name in [
        "materialize.py",
        "checks.py",
        "verify_contract.py",
        "blocks.py",
        "cpu.py",
        "final_check.py",
        "summarize.py",
    ]:
        command = [sys.executable, str(out / name)]
        commands.append(command)
        with (out / (name + ".log")).open("w") as log:
            subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, cwd=out)
    (out / "native-rerun-commands.json").write_text(json.dumps(commands, indent=2) + "\n")
    print("Full native rerun complete:", out)


if __name__ == "__main__":
    main()
