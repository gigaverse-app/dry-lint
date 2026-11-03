"""Compare unjudged candidate sources on one clean checkout; write raw evidence outside the repository."""

import argparse
import hashlib
import json
import platform
import statistics
import time
from importlib.metadata import version
from pathlib import Path

from dryer.extract import entries_in_source

from dry_lint.detector import Candidate, Detector, changed_lines, touched
from dry_lint.dryer import DryerComparer
from dry_lint.functions import repository_functions
from dry_lint.git import git
from dry_lint.models import Function
from dry_lint.plugins import load
from dry_lint.settings import PluginChoice, Settings


def pair_keys(pairs: list[Candidate]) -> set[tuple[str, str]]:
    return {tuple(sorted((pair.new.qualname, pair.existing.qualname))) for pair in pairs}


def verify_upstream(root: Path, functions: list[Function]) -> int:
    """Whole-file upstream extraction must match the adapter, including overloads and methods."""
    source = DryerComparer()
    source.index(functions)
    full = {}
    for path in sorted({f.path for f in functions}):
        entries, warning = entries_in_source("python", (root / path).read_text(encoding="utf-8"), path, path)
        assert warning is None, warning
        full.update({(entry.file, entry.start_line): entry for entry in entries})
    eligible = 0
    for function in functions:
        location = (function.path, function.line)
        expected, actual = full[location], source.entries[location]
        keep = expected.end_line - expected.start_line + 1 >= source.min_lines and expected.nodes >= source.min_nodes
        assert actual is not None, function.qualname
        assert actual.fingerprints == expected.fingerprints and actual.nodes == expected.nodes, function.qualname
        eligible += keep
    return eligible


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--base", default="HEAD~40", help="Changed-function workload; resolved once to a SHA.")
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    root = args.root.resolve()
    if git(root, "status", "--porcelain", "--untracked-files=no"):
        parser.error("Use a clean, frozen checkout so both detectors see identical source.")
    sha, base = git(root, "rev-parse", "HEAD"), git(root, "rev-parse", args.base)
    settings = Settings.load(root)
    start = time.perf_counter()
    extractors = [load("extractors", choice) for choice in settings.extractors]
    functions = repository_functions(root, settings.include, settings.exclude, extractors)
    extraction_seconds = time.perf_counter() - start
    changed = touched(functions, changed_lines(root, base=base))
    manifest = "\n".join(f"{f.qualname}:{f.line}:{f.end_line}:{f.code}" for f in functions)
    result = {
        "repository_sha": sha,
        "base_sha": base,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "versions": {name: version(name) for name in ("dry-lint", "dryer", "tree-sitter", "tree-sitter-language-pack")},
        "settings": settings.model_dump(),
        "functions": len(functions),
        "files": len({f.path for f in functions}),
        "changed_functions": len(changed),
        "corpus_sha256": hashlib.sha256(manifest.encode()).hexdigest(),
        "extraction_seconds": extraction_seconds,
        "dryer_eligible_functions": verify_upstream(root, functions),
        "upstream_parity": "all canonical function spans match full-file upstream extraction",
        "runs": [],
    }
    populations = {}
    args.output.mkdir(parents=True, exist_ok=True)
    for repetition in range(args.runs):
        for name in ("tfidf", "dryer") if repetition % 2 == 0 else ("dryer", "tfidf"):
            config = settings.model_copy(update={"comparer": PluginChoice(use=name)})
            started = time.perf_counter()
            detector = Detector(functions, config, load("comparers", config.comparer), extractors)
            built = time.perf_counter()
            proposed = detector.candidates(changed)
            checks = [p for p in proposed if p.filtered is None]
            skipped = [p for p in proposed if p.filtered is not None]
            checked = time.perf_counter()
            scans = detector.scan()
            scanned = time.perf_counter()
            row = {
                "repetition": repetition + 1,
                "detector": name,
                "build_seconds": built - started,
                "check_seconds": checked - built,
                "scan_seconds": scanned - checked,
                "check_pairs": len(checks),
                "skipped_check_pairs": len(skipped),
                "scan_pairs": len(scans),
            }
            result["runs"].append(row)
            print(json.dumps(row), flush=True)
            for mode, pairs in (("check", checks), ("scan", scans)):
                keys = pair_keys(pairs)
                previous = populations.setdefault((name, mode), keys)
                assert previous == keys, "Repeated runs must propose identical pairs"
                if repetition == 0:
                    (args.output / f"{name}-{mode}.json").write_text(
                        json.dumps([p.model_dump() for p in pairs], indent=2), encoding="utf-8"
                    )
            (args.output / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    result["overlap"] = {}
    for mode in ("check", "scan"):
        left, right = populations[("tfidf", mode)], populations[("dryer", mode)]
        result["overlap"][mode] = {
            "shared": len(left & right),
            "tfidf_only": len(left - right),
            "dryer_only": len(right - left),
            "union": len(left | right),
        }
    result["medians"] = {
        name: {
            field: statistics.median(row[field] for row in result["runs"] if row["detector"] == name)
            for field in ("build_seconds", "check_seconds", "scan_seconds")
        }
        for name in ("tfidf", "dryer")
    }
    assert git(root, "rev-parse", "HEAD") == sha
    assert not git(root, "status", "--porcelain", "--untracked-files=no")
    (args.output / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"overlap": result["overlap"], "medians": result["medians"]}, indent=2))


if __name__ == "__main__":
    main()
