"""Rank Lean declarations by rewrite rules repeated across distinct `simp only` calls."""

import argparse
import json
import re
from bisect import bisect_left
from collections import Counter
from pathlib import Path

from dry_lint.lean import BRACKETS, read_source
from dry_lint.lean_upstream import lean_sources, local_site

_SIMP_ONLY = re.compile(r"\b(?:simp|simp_all)\s+only\s*\[")


def rule_lists(source):
    """
    The row and the rules of each `simp only [...]` list, read from the text with comments and
    strings masked. The grammar loses some lists after syntax it cannot parse; the brackets are always there.
    """
    lean = read_source(source)
    text = lean.structure
    for call in _SIMP_ONLY.finditer(text):
        rules = set()
        depth, start = 1, call.end()
        for position in range(start, len(text)):
            depth += (text[position] in BRACKETS[0]) - (text[position] in BRACKETS[1])
            if depth == 0 or (depth == 1 and text[position] == ","):
                rules.add(" ".join(text[start:position].split()))
                start = position + 1
            if depth == 0:
                break
        rules.discard("")
        if rules and depth == 0:
            yield lean.line(call.end() - 1) - 1, rules


def rank_module(path, source, artifacts):
    calls = list(rule_lists(source))
    rows = [row for row, _ in calls]
    lines = source.splitlines()
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
    findings = []
    built = unbuilt = 0
    for path in lean_sources(args.source_root):
        relative = path.relative_to(args.source_root)
        artifact = (args.artifact_root / relative).with_suffix(".ilean")
        if not artifact.is_file():
            unbuilt += 1
            continue
        built += 1
        source = path.read_text(encoding="utf-8")
        if source.count("only") < 2:
            continue
        data = json.loads(artifact.read_bytes())
        if data.get("version") != 6:
            arg.error(f"{artifact}: expected .ilean version 6")
        findings.extend(rank_module(relative.as_posix(), source, data))
    if not built:
        arg.error("No matching .ilean artifacts. Build the project and check the two roots.")
    findings.sort(key=lambda row: (-row["repeat_mentions"], row["path"], row["line"]))
    print(
        json.dumps({"built_modules": built, "unbuilt_modules": unbuilt, "findings": findings[: args.limit]}, indent=2)
    )


if __name__ == "__main__":
    main()
