"""Generate a complete tiny request/observation fixture and run the offline CLI twice."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from dry_lint.models import Candidate

from .audit import source_binding
from .exact_cache import ExactCache, atomic_json, canonical, sha
from .source import git, validate_sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True, type=Path, help="New empty directory for synthetic files only")
    args = parser.parse_args()
    directory = args.out_dir.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    root = directory / "source"
    root.mkdir()
    git(root, "init", "-q")
    raw = b"def adjust(value):\n    incremented = value + 1\n    scaled = incremented * 2\n    return scaled\n"
    for path in ("left.py", "right.py"):
        (root / path).write_bytes(raw)
    git(root, "add", ".")
    git(
        root,
        "-c",
        "user.name=Synthetic demo",
        "-c",
        "user.email=demo@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        "synthetic offline fixture",
    )
    revision = git(root, "rev-parse", "HEAD").decode().strip()
    cache = ExactCache(directory / "fixture-cache")
    functions = [cache.extract("example/synthetic", revision, path, raw)[0] for path in ("left.py", "right.py")]
    candidate = Candidate(new=functions[0], existing=functions[1], similarity=0.1, comparer="synthetic:1")
    packet = dict(
        id="synthetic-demo",
        repository="example/synthetic",
        revision=revision,
        status="disputed",
        candidate=candidate.model_dump(mode="json"),
        source_proofs=[dict(source_id=f.qualname, file_sha256=sha(raw)) for f in functions],
    )
    binding = source_binding(packet, candidate, validate_sources(packet, candidate, root, cache))
    requests, observations = [], []
    for reviewer, label in (("alpha", "separate"), ("beta", "duplicate")):
        identity = dict(
            binding,
            schema=1,
            kind=reviewer,
            judge="synthetic",
            version="v1",
            model="offline-fixture",
            prompt_version="p1",
            rendered_input="Synthetic fixture only: compare adjust implementations.",
            max_output_tokens=128,
            request_options={"temperature": 0},
        )
        key = sha(canonical(identity))
        requests.append(dict(id=packet["id"], identity=identity, request_key=key))
        observations.append(
            dict(
                identity=identity,
                request_key=key,
                verdict=dict(label=label, why="Invented fixture observation; no model executed"),
            )
        )
    for filename, rows in (
        ("packets.jsonl", [packet]),
        ("requests.jsonl", requests),
        ("observations.jsonl", observations),
    ):
        (directory / filename).write_bytes(b"".join(canonical(row) + b"\n" for row in rows))
    atomic_json(directory / "repositories.json", {"example/synthetic": "source"})
    for name in ("cold", "warm"):
        subprocess.run(
            [
                sys.executable,
                "-m",
                "research_mining",
                "--packets",
                str(directory / "packets.jsonl"),
                "--repositories",
                str(directory / "repositories.json"),
                "--requests",
                str(directory / "requests.jsonl"),
                "--observations",
                str(directory / "observations.jsonl"),
                "--reviewers",
                "alpha",
                "beta",
                "--cache",
                str(directory / "cache"),
                "--hints",
                "--out",
                str(directory / f"{name}.json"),
            ],
            check=True,
        )
    cold, warm = [json.loads((directory / f"{name}.json").read_bytes()) for name in ("cold", "warm")]
    if cold["rows"] != warm["rows"] or not cold["rows"][0]["observations_complete"]:
        raise ValueError("Demo cold/warm observation equality failed")
    print(f"Complete synthetic inputs and equal cold/warm audit rows: {directory}")


if __name__ == "__main__":
    main()
