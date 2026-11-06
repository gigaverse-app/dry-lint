"""Portable offline entry point: python -m research_mining --help."""

import argparse
import json
from pathlib import Path

from .audit import audit_queue
from .exact_cache import ExactCache, atomic_json, sha


def read_rows(path: Path | None) -> tuple[list, str | None]:
    if path is None:
        return [], None
    raw = path.read_bytes()
    # Broken JSONL is an input error, never silently dropped evidence.
    return [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()], sha(raw)


def main():
    parser = argparse.ArgumentParser(description="Offline source audit queue; never calls a judge or accepts gold")
    parser.add_argument("--packets", required=True, type=Path)
    parser.add_argument(
        "--repositories", required=True, type=Path, help="JSON mapping repository names to local Git paths"
    )
    parser.add_argument("--requests", type=Path, help="Expected complete research request identities, JSONL")
    parser.add_argument("--observations", type=Path, help="Existing research observations, JSONL; read only")
    parser.add_argument("--reviewers", required=True, nargs="+")
    parser.add_argument("--cache", required=True, type=Path, help="Disposable trusted-local extraction directory")
    parser.add_argument("--hints", action="store_true", help="Add lexical navigation only")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    packets, packet_sha = read_rows(args.packets)
    requests, request_sha = read_rows(args.requests)
    observations, observation_sha = read_rows(args.observations)
    repository_raw = args.repositories.read_bytes()
    locations = json.loads(repository_raw)
    repositories = {
        name: (args.repositories.resolve().parent / location).resolve() for name, location in locations.items()
    }
    # Do not overwrite evidence inputs, a Git file, or any existing output accidentally.
    if args.out.exists():
        parser.error("Output already exists; choose a new path")
    result = audit_queue(
        packets, repositories, ExactCache(args.cache), requests, observations, args.reviewers, args.hints
    )
    result["inputs"] = dict(
        packets=packet_sha, requests=request_sha, observations=observation_sha, repositories=sha(repository_raw)
    )
    try:
        atomic_json(args.out, result, exclusive=True)
    except FileExistsError:
        parser.error("Output already exists; choose a new path")
    print(
        json.dumps(
            dict(
                rows=len(result["rows"]),
                provider_calls=0,
                accepted_gold=0,
                **{key: result["cache"][key] for key in ("hits", "parses", "corruptions")},
            )
        )
    )


if __name__ == "__main__":
    main()
