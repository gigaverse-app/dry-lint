"""Find rewrite rule bundles shared by several declarations in one Lean module."""

import json
import re
from bisect import bisect_left
from collections import Counter, defaultdict
from itertools import combinations

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


def declaration_calls(source, artifacts):
    if "only" not in source:
        return
    calls = list(rule_lists(source))
    rows = [row for row, _ in calls]
    lines = source.splitlines()
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
            "rules": sorted(common),
            "proof_count": len(names),
            "sites": [{"name": owners[i], "line": calls[i][0] + 1} for i in sorted(sites, key=lambda i: calls[i][0])],
        }


def built_rewrite_modules(source_root, artifact_root):
    for path in lean_sources(source_root):
        relative = path.relative_to(source_root)
        artifact = (artifact_root / relative).with_suffix(".ilean")
        if not artifact.is_file():
            yield relative.as_posix(), None, None
            continue
        data = json.loads(artifact.read_bytes())
        if data.get("version") != 6:
            raise ValueError(f"{artifact}: expected .ilean version 6")
        yield relative.as_posix(), path.read_text(encoding="utf-8"), data


def rank_families(findings, proof_counts):
    """Prioritize widely shared arguments with a locally distinctive rule and fresh evidence."""

    def priority(finding):
        frequency = min(proof_counts[rule] for rule in finding["rules"])
        specificity = finding["proof_count"] / frequency
        return (
            -finding["proof_count"] * specificity,
            -finding["proof_count"],
            -len(finding["rules"]),
            finding["path"],
            finding["rules"],
        )

    representatives = defaultdict(list)
    fresh, related = [], []
    for finding in sorted(findings, key=priority):
        sites = {(s["name"], s["line"]) for s in finding["sites"]}
        proofs = {name for name, _ in sites}
        prior = representatives[finding["path"]]
        if any(
            sites & seen_sites and 3 * len(proofs & seen) >= 2 * min(len(proofs), len(seen))
            for seen, seen_sites in prior
        ):
            related.append(finding)
        else:
            prior.append((proofs, sites))
            fresh.append(finding)
    return fresh + related


def find_rewrite_families(source_root, artifact_root, rules=(), limit=20):
    if limit < 1:
        raise ValueError("--limit must be positive")
    findings = []
    proof_counts = Counter()
    built = missing = 0
    required = set(rules)
    for path, source, data in built_rewrite_modules(source_root, artifact_root):
        if source is None:
            missing += 1
        else:
            built += 1
            declarations = list(declaration_calls(source, data))
            for _, _, calls in declarations:
                proof_counts.update({rule for _, rules_in_call in calls for rule in rules_in_call})
            findings.extend(rewrite_families(path, declarations, required))
    if not built:
        raise ValueError("No matching .ilean artifacts. Build the project and check the two roots.")
    findings = rank_families(findings, proof_counts)
    return {"built_modules": built, "unbuilt_modules": missing, "findings": findings[:limit]}
