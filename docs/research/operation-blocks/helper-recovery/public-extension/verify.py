"""Artifact integrity and optional original-output immutability, separate from table replay."""

import argparse
import hashlib
import json
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent


def check(path, record):
    assert path.is_file(), str(path)
    assert path.stat().st_size == record["bytes"], str(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"], str(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--historical-lab", type=Path, help="Optional original lab directory; must match pre-package snapshot"
    )
    args = parser.parse_args()
    manifest = json.loads((PACKAGE / "MANIFEST.json").read_text())
    for r in manifest["files"]:
        check(PACKAGE / r["path"], r)
    historical = 0
    if args.historical_lab:
        snap = json.loads((PACKAGE / "historical-output-snapshot.json").read_text())
        for r in snap["files"]:
            check(args.historical_lab / r["path"], r)
        historical = len(snap["files"])
    print(
        json.dumps(
            {
                "status": "passed",
                "package_files": len(manifest["files"]),
                "unchanged_historical_files": historical,
                "table_replay": "Use replay.py --out replayed --verify; this command only verifies integrity.",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
