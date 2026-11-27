"""Rank long Lean proofs by the order of references recorded during elaboration."""

import argparse
import json
from pathlib import Path

from dry_lint.lean import LeanExtractor
from dry_lint.lean_proof_references import align_proofs, collect_proofs, distinct_references, shared_line_count


def rank_proofs(proofs):
    matches = []
    for hit in align_proofs(proofs):
        matches.append(
            {
                "score": shared_line_count(hit.rows) * (0.5 + 0.5 * distinct_references(hit.rows) / len(hit.rows)),
                "shared_lines": shared_line_count(hit.rows),
                "left": proofs[hit.left].location(),
                "right": proofs[hit.right].location(),
                "references": [(left[0], right[0], left[2]) for left, right in hit.rows],
            }
        )
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path, help="Lean library source directory, such as src")
    parser.add_argument("artifact_root", type=Path, help="Matching .lake/build/lib/lean directory")
    args = parser.parse_args(argv)
    try:
        proofs = list(
            collect_proofs(
                args.source_root, args.artifact_root, LeanExtractor(min_lines=15), args.source_root.rglob("*.lean")
            )
        )
        if not proofs:
            raise ValueError("No eligible proofs. Check the source and build artifact directories.")
        report = {"analyzed_proofs": len(proofs), "matches": rank_proofs(proofs)}
    except (OSError, ValueError, ImportError, KeyError) as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
