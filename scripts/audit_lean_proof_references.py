"""Rank long Lean proofs by the order of references recorded during elaboration."""

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path

from dry_lint.lean import LeanExtractor
from dry_lint.models import qualified

PROOF_ASSIGNMENT = re.compile(r":=\s*by[ \t]*(?:--[^\n]*)?\n")
Reference = tuple[int, int, str]


@dataclass(frozen=True)
class Proof:
    path: str
    name: str
    start: int
    end: int
    references: list[Reference]

    def location(self):
        return {"path": self.path, "name": self.name, "start": self.start, "end": self.end}


def declaration_references(artifact):
    refs = defaultdict(list)
    entries = iter(artifact["references"])
    for (kind, module, name), detail in zip(entries, entries, strict=True):
        if kind != 0 or not module or module.startswith(("Init.", "Lean.", "Batteries.", "Std.")):
            continue
        for usage in detail["usages"]:
            if len(usage) >= 5 and usage[4] is not None:
                row, column, _, _, context = usage
                refs[context].append((row + 1, column, name))
    return refs


def collect_proofs(source_root, artifacts, extractor):
    for source in sorted(source_root.rglob("*.lean")):
        relative = source.relative_to(source_root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        artifact = (artifacts / relative).with_suffix(".ilean")
        data = json.loads(artifact.read_bytes())
        if data.get("version") != 6 or data.get("module") != ".".join(relative.with_suffix("").parts):
            raise ValueError(f"{artifact}: expected version 6 .ilean data for {relative}")
        refs = declaration_references(data)
        path = relative.as_posix()
        for fn in extractor.functions(path, source.read_text(encoding="utf-8")):
            opener = PROOF_ASSIGNMENT.search(fn.code)
            if opener is None:
                continue
            start = fn.line + fn.code[: opener.end()].count("\n")
            name = qualified(fn.owner, fn.name)
            used = sorted(ref for ref in refs[name] if start <= ref[0] <= fn.end_line)
            if len(used) >= 12:
                yield Proof(path, name, start, fn.end_line, used)


def reference_candidates(names):
    """Seed comparisons with repeated triples, omitting triples that occur throughout the corpus."""
    triples = defaultdict(set)
    for index, sequence in enumerate(names):
        for triple in zip(sequence, sequence[1:], sequence[2:], strict=False):
            if len(set(triple)) > 1:
                triples[triple].add(index)
    pairs = Counter()
    for hits in triples.values():
        if 1 < len(hits) <= 16:
            pairs.update(combinations(sorted(hits), 2))
    return (pair for pair, count in pairs.items() if count >= 2)


def rank_proofs(proofs):
    names = [[name for _, _, name in proof.references] for proof in proofs]
    frequency = Counter(name for sequence in names for name in set(sequence))
    matches = []
    for i, j in reference_candidates(names):
        left, right = proofs[i], proofs[j]
        blocks = SequenceMatcher(None, names[i], names[j], autojunk=False).get_matching_blocks()
        anchors = []
        for a, b, size in blocks:
            for offset in range(size):
                line, _, name = left.references[a + offset]
                if frequency[name] < 100:
                    anchors.append((line, right.references[b + offset][0], name))
        symbols = {name for _, _, name in anchors}
        lines = min(len({a for a, _, _ in anchors}), len({b for _, b, _ in anchors}))
        if len(symbols) >= 7 and lines >= 6:
            matches.append(
                {
                    "score": lines * (0.5 + 0.5 * len(symbols) / len(anchors)),
                    "shared_lines": lines,
                    "left": left.location(),
                    "right": right.location(),
                    "references": anchors,
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
        proofs = list(collect_proofs(args.source_root, args.artifact_root, LeanExtractor(min_lines=15)))
        if not proofs:
            raise ValueError("No eligible proofs. Check the source and build artifact directories.")
        report = {"analyzed_proofs": len(proofs), "matches": rank_proofs(proofs)}
    except (OSError, ValueError, ImportError, KeyError) as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
