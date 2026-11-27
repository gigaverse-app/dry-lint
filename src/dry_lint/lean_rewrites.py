"""Find rewrite rule bundles shared by several declarations in one Lean module."""

import json
import re
from bisect import bisect_left
from collections import defaultdict
from itertools import combinations

from tree_sitter import Query, QueryCursor

from dry_lint.lean import LeanExtractor
from dry_lint.lean_upstream import lean_sources, local_site

_SIMP_ONLY = re.compile(rb"\b(?:simp|simp_all)\s+only\s*$")


def declaration_calls(source, artifacts, parser, query):
    if b"only" not in source:
        return
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
    spans = []
    for name, coords in artifacts["decls"].items():
        site = local_site(name, coords, lines)
        if not site:
            continue
        start, length = site
        spans.append((length, start, name))
    # A nested declaration and its parent can cover the same call. Give it to the inner proof.
    claimed = set()
    for length, start, name in sorted(spans):
        indices = range(bisect_left(rows, start - 1), bisect_left(rows, start - 1 + length))
        within = [calls[i] for i in indices if i not in claimed]
        claimed.update(indices)
        if within:
            yield name, start, within


def rewrite_families(path, declarations, required_rules):
    """Find bundles that recur together in one call in at least three distinct proofs."""
    calls = []
    owners = []
    pairs = defaultdict(list)
    for name, _, within in declarations:
        for row, rules in within:
            if not required_rules <= rules:
                continue
            index = len(calls)
            calls.append((row, rules))
            owners.append(name)
            for pair in combinations(sorted(rules), 2):
                pairs[pair].append(index)

    # Several pairs can describe exactly the same sites. Report their full shared vocabulary once.
    for sites in sorted({tuple(indices) for indices in pairs.values() if len(indices) >= 3}):
        names = {owners[i] for i in sites}
        if len(names) < 3:
            continue
        common = set.intersection(*(calls[i][1] for i in sites))
        yield {
            "path": path,
            "rules": sorted(rule.decode() for rule in common),
            "proof_count": len(names),
            "sites": [{"name": owners[i], "line": calls[i][0] + 1} for i in sorted(sites, key=lambda i: calls[i][0])],
        }


def built_rewrite_modules(source_root, artifact_root):
    parser = LeanExtractor().parser
    query = Query(parser.language, "(list_lit) @rules")
    for path in lean_sources(source_root):
        relative = path.relative_to(source_root)
        artifact = (artifact_root / relative).with_suffix(".ilean")
        if not artifact.is_file():
            yield relative.as_posix(), None
            continue
        data = json.loads(artifact.read_bytes())
        if data.get("version") != 6:
            raise ValueError(f"{artifact}: expected .ilean version 6")
        yield relative.as_posix(), declaration_calls(path.read_bytes(), data, parser, query)


def find_rewrite_families(source_root, artifact_root, rules=(), limit=20):
    if limit < 1:
        raise ValueError("--limit must be positive")
    findings = []
    built = missing = 0
    required = {rule.encode() for rule in rules}
    for path, declarations in built_rewrite_modules(source_root, artifact_root):
        if declarations is None:
            missing += 1
        else:
            built += 1
            findings.extend(rewrite_families(path, declarations, required))
    if not built:
        raise ValueError("No matching .ilean artifacts. Build the project and check the two roots.")
    findings.sort(key=lambda row: (-row["proof_count"], -len(row["rules"]), row["path"], row["rules"]))
    return {"built_modules": built, "unbuilt_modules": missing, "findings": findings[:limit]}
