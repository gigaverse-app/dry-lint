"""Rank Lean declarations by rewrite rules repeated across distinct `simp only` calls."""

import argparse
import json
import re
from bisect import bisect_left
from collections import Counter
from pathlib import Path

from tree_sitter import Query, QueryCursor

from dry_lint.lean import LeanExtractor
from dry_lint.lean_upstream import lean_sources, local_site

_SIMP_ONLY = re.compile(rb"\b(?:simp|simp_all)\s+only\s*$")


def rank_module(path, source, artifacts, parser, query):
    tree = parser.parse(source)
    calls = []
    for node in QueryCursor(query).captures(tree.root_node).get("rules", []):
        if node.has_error or not _SIMP_ONLY.search(source[max(0, node.start_byte - 64) : node.start_byte]):
            continue
        rules = {child.text.strip() for child in node.named_children if not child.type.endswith("comment")}
        if rules:
            calls.append((node.start_point.row, rules))
    calls.sort(key=lambda item: item[0])
    rows = [row for row, _ in calls]
    lines = source.decode().splitlines()
    for name, coords in artifacts["decls"].items():
        site = local_site(name, coords, lines)
        if not site:
            continue
        start, length = site
        within = calls[bisect_left(rows, start - 1) : bisect_left(rows, start - 1 + length)]
        counts = Counter(rule for _, rules in within for rule in rules)
        repeated = sum(count - 1 for count in counts.values())
        if repeated:
            yield {
                "path": path,
                "line": start,
                "name": name,
                "repeat_mentions": repeated,
                "call_lines": [row + 1 for row, rules in within if any(counts[r] > 1 for r in rules)],
            }


def main(argv=None):
    arg = argparse.ArgumentParser(description=__doc__)
    arg.add_argument("source_root", type=Path)
    arg.add_argument("artifact_root", type=Path)
    arg.add_argument("--limit", type=int, default=20)
    args = arg.parse_args(argv)
    if args.limit < 1:
        arg.error("--limit must be positive")
    parser = LeanExtractor().parser
    query = Query(parser.language, "(list_lit) @rules")
    findings = []
    built = unbuilt = 0
    for path in lean_sources(args.source_root):
        relative = path.relative_to(args.source_root)
        artifact = (args.artifact_root / relative).with_suffix(".ilean")
        if not artifact.is_file():
            unbuilt += 1
            continue
        built += 1
        source = path.read_bytes()
        if source.count(b"only") < 2:
            continue
        data = json.loads(artifact.read_bytes())
        if data.get("version") != 6:
            arg.error(f"{artifact}: expected .ilean version 6")
        findings.extend(rank_module(relative.as_posix(), source, data, parser, query))
    if not built:
        arg.error("No matching .ilean artifacts. Build the project and check the two roots.")
    findings.sort(key=lambda row: (-row["repeat_mentions"], row["path"], row["line"]))
    print(
        json.dumps({"built_modules": built, "unbuilt_modules": unbuilt, "findings": findings[: args.limit]}, indent=2)
    )


if __name__ == "__main__":
    main()
