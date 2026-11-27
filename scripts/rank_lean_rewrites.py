"""Rank Lean declarations by rewrite rules repeated across distinct `simp only` calls."""

import argparse
import json
from collections import Counter
from pathlib import Path

from dry_lint.lean_rewrites import built_rewrite_modules, declaration_calls


def rank_module(path, source, artifacts):
    for name, start, within in declaration_calls(source, artifacts):
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
    try:
        for path, source, data in built_rewrite_modules(args.source_root, args.artifact_root):
            if source is None:
                unbuilt += 1
            else:
                built += 1
                findings.extend(rank_module(path, source, data))
    except ValueError as exc:
        arg.error(str(exc))
    if not built:
        arg.error("No matching .ilean artifacts. Build the project and check the two roots.")
    findings.sort(key=lambda row: (-row["repeat_mentions"], row["path"], row["line"]))
    print(
        json.dumps({"built_modules": built, "unbuilt_modules": unbuilt, "findings": findings[: args.limit]}, indent=2)
    )


if __name__ == "__main__":
    main()
