"""Rebuild and test the frozen family extraction in a new directory; no providers."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path


def main(fixture, output):
    source = fixture / "proof"
    manifest = json.loads((source / "MANIFEST.json").read_text())
    for item in manifest["files"]:
        raw = (source / item["path"]).read_bytes()
        assert len(raw) == item["bytes"] and hashlib.sha256(raw).hexdigest() == item["sha256"]
    shutil.copytree(source, output)
    subprocess.run([sys.executable, "-B", str(output / "study.py")], check=True, stdout=subprocess.DEVNULL)
    subprocess.run([sys.executable, "-B", str(output / "test_equivalence.py")], check=True)
    metrics = json.loads((output / "metrics.json").read_text())
    assert metrics == json.loads((source / "metrics.json").read_text())

    def canonical(items):
        return sorted(json.dumps(r, sort_keys=True) for r in items)

    before = json.loads((source / "model-domain-results.json").read_text())["results"]
    after = json.loads((output / "model-domain-results.json").read_text())["results"]
    assert canonical(before) == canonical(after)
    print(
        json.dumps(
            dict(
                families=1,
                sites=18,
                owners=10,
                executable_statements_saved=16,
                net_guard_extraction_lines_saved=67,
                net_patch_lines_saved=68,
                model_field_samples=len(after),
                source_revision=manifest["source_revision"],
                scope="Stable ordinary fields; not full HTTP/application equivalence",
                provider_calls=0,
            )
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    main(args.fixture.resolve(), args.out.resolve())
