"""Rank long Lean proofs by the order of references recorded during elaboration."""

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import replace
from itertools import combinations
from pathlib import Path

from dry_lint.lean import LeanExtractor
from dry_lint.lean_proof_references import (
    align_proofs,
    align_references,
    collect_proofs,
    distinct_references,
    shared_line_count,
)


def report_match(left, right, rows):
    lines = shared_line_count(rows)
    return {
        "score": lines * (0.5 + 0.5 * distinct_references(rows) / len(rows)),
        "shared_lines": lines,
        "left": left.location(),
        "right": right.location(),
        "references": [(a[0], b[0], a[2]) for a, b in rows],
    }


def rank_proofs(proofs):
    matches = [report_match(proofs[hit.left], proofs[hit.right], hit.rows) for hit in align_proofs(proofs)]
    return sorted(
        matches,
        key=lambda match: (
            -match["score"],
            match["left"]["path"],
            match["left"]["start"],
            match["right"]["path"],
            match["right"]["start"],
        ),
    )


def fragment_match(proof, rows):
    if distinct_references(rows) < 7 or (lines := shared_line_count(rows)) < 7:
        return None
    (left_start, _, _), (right_start, _, _) = rows[0]
    (left_end, _, _), (right_end, _, _) = rows[-1]
    if left_end >= right_start or max(left_end - left_start, right_end - right_start) >= 2 * lines:
        return None
    left = replace(proof, start=left_start, end=left_end)
    right = replace(proof, start=right_start, end=right_end)
    return report_match(left, right, rows)


def reference_windows(refs, names):
    """Use repeated triples to locate nearby, disjoint stretches worth aligning."""
    positions = defaultdict(list)
    for index, triple in enumerate(zip(names, names[1:], names[2:], strict=False)):
        if len(set(triple)) > 1:
            positions[triple].append(index)
    windows = set()
    for hits in positions.values():
        if not 2 <= len(hits) <= 7:
            continue
        for first, second in combinations(hits, 2):
            if refs[second][0] - refs[first][0] < 5:
                continue
            # Retain context on both sides of each seed while bounding the alignment cost.
            half_gap = (second - first) // 2
            right = max(first + half_gap, second - 12)
            stop = min(right, first + 45)
            end = min(len(refs), second + half_gap + 20)
            windows.add((max(0, first - 12), stop, right, end))
    return sorted(windows)


def overlaps(first, second):
    shared = min(first["end"], second["end"]) - max(first["start"], second["start"]) + 1
    shorter = min(first["end"] - first["start"], second["end"] - second["start"]) + 1
    return shared * 2 >= shorter


def rank_fragments(proofs):
    frequency = Counter(name for proof in proofs for name in {name for _, _, name in proof.references})
    # Scale the frequency cutoff with the corpus so a larger scan retains the same variety of anchors.
    common = max(150, len(proofs) // 20)
    ranked = []
    for proof in proofs:
        refs = [ref for ref in proof.references if frequency[ref[2]] < common]
        names = [name for _, _, name in refs]
        candidates = []
        for start, stop, right, end in reference_windows(refs, names):
            rows = align_references(refs[start:stop], refs[right:end], names[start:stop], names[right:end])
            if match := fragment_match(proof, rows):
                candidates.append(match)
        accepted = []
        for match in sorted(candidates, key=lambda item: (-item["shared_lines"], -item["score"])):
            if not any(
                overlaps(match["left"], prev["left"]) and overlaps(match["right"], prev["right"]) for prev in accepted
            ):
                accepted.append(match)
        ranked.extend(accepted)
    return sorted(ranked, key=lambda item: (-item["shared_lines"], -item["score"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path, help="Lean library source directory, such as src")
    parser.add_argument("artifact_root", type=Path, help="Matching .lake/build/lib/lean directory")
    parser.add_argument("--within-proof", action="store_true", help="Compare fragments within each proof")
    args = parser.parse_args(argv)
    try:
        proofs = list(
            collect_proofs(
                args.source_root, args.artifact_root, LeanExtractor(min_lines=15), args.source_root.rglob("*.lean")
            )
        )
        if not proofs:
            raise ValueError("No eligible proofs. Check the source and build artifact directories.")
        rank = rank_fragments if args.within_proof else rank_proofs
        report = {"analyzed_proofs": len(proofs), "matches": rank(proofs)}
    except (OSError, ValueError, ImportError, KeyError) as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
