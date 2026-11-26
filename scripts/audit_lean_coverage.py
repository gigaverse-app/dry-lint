"""Compare dry-lint's Lean extractor with declaration locations from a freshly built Lake project."""

import argparse
import json
import os
import re
from collections import defaultdict
from pathlib import Path

from dry_lint.lean import LeanExtractor

DECLARATION = re.compile(r"\b(?:def|abbrev|lemma|theorem|instance|opaque)\s+$")


def selections(data):
    # Some definitions appear only in the reference table. Ignore uses in imported modules.
    for name, coords in data["decls"].items():
        yield name, coords[4:]
    refs = data["references"]
    for ident, info in zip(refs[::2], refs[1::2], strict=True):
        if ident[:2] == [0, data["module"]] and info["definition"] is not None:
            yield ident[2], info["definition"][:4]


def compare_module(extractor, path, source, data):
    """Count distinct named source sites, including one-line proofs. Report unmatched compiler names."""
    source_lines = source.splitlines()
    by_name = defaultdict(list)
    for fn in extractor.functions(path, source):
        by_name[fn.name].append((fn.line, fn.end_line))

    sites = {}
    for name, (row, start, end_row, end) in selections(data):
        if row != end_row:
            continue
        line = source_lines[row].encode("utf-16-le")
        before = line[: 2 * start].decode("utf-16-le")
        if DECLARATION.search(before):
            spelling = line[2 * start : 2 * end].decode("utf-16-le").removeprefix("_root_.")
            sites[row + 1, spelling] = name

    missed = [
        (line, name)
        for (line, spelling), name in sites.items()
        if not any(first <= line <= last for first, last in by_name[spelling])
    ]
    return len(sites), sorted(missed)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path, help="Lake library source directory, such as src")
    parser.add_argument("artifact_root", type=Path, help="Matching .lake/build/lib/lean directory")
    parser.add_argument("--show-missed", action="store_true", help="Include each unmatched source location in the JSON")
    args = parser.parse_args(argv)
    extractor = LeanExtractor(min_lines=1)
    built = unbuilt = eligible = missed = 0
    locations = []
    for directory, subdirs, files in os.walk(args.source_root):
        subdirs[:] = sorted(d for d in subdirs if not d.startswith("."))
        for filename in sorted(files):
            if not filename.endswith(".lean"):
                continue
            path = Path(directory, filename)
            relative = path.relative_to(args.source_root)
            artifact = (args.artifact_root / relative).with_suffix(".ilean")
            if not artifact.is_file():
                unbuilt += 1
                continue
            data = json.loads(artifact.read_bytes())
            if data["version"] != 6:
                parser.error(f"{artifact}: expected Lean .ilean version 6, got {data['version']!r}")
            built += 1
            count, missing = compare_module(extractor, relative.as_posix(), path.read_text(encoding="utf-8"), data)
            eligible += count
            missed += len(missing)
            if args.show_missed:
                locations.extend({"path": relative.as_posix(), "line": line, "name": name} for line, name in missing)
    if not eligible:
        parser.error("No eligible declaration sites. Check the two directory roots and build the project first.")
    report = {
        "built_modules": built,
        "unbuilt_modules": unbuilt,
        "eligible_sites": eligible,
        "matched": eligible - missed,
    }
    if args.show_missed:
        report["missed"] = locations
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
