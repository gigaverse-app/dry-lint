"""Compare named Lean bodies using references recorded during elaboration."""

import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path

from dry_lint.models import qualified

PROOF_ASSIGNMENT = re.compile(r":=\s*by[ \t]*(?:--[^\n]*)?\n")
# Lean records a private declaration as `_private.<Module>.0.<Name>`.
_PRIVATE = re.compile(r"^_private\..+?\.0\.")
#: A reference used by this many proofs says nothing about which of them share an argument.
COMMON = 100
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
                refs[_PRIVATE.sub("", context)].append((row + 1, column, name))
    return refs


def collect_proofs(
    source_root, artifacts, extractor, sources: Iterable[Path], unbuilt: list[Path] | None = None
) -> Iterator[Proof]:
    """Proofs of the built modules. A source without an artifact is an error, unless `unbuilt` collects them."""
    for source in sorted(sources):
        relative = source.relative_to(source_root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        artifact = (artifacts / relative).with_suffix(".ilean")
        if unbuilt is not None and not artifact.is_file():
            unbuilt.append(source)
            continue
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
        if 1 < len(hits) < COMMON:
            pairs.update(combinations(sorted(hits), 2))
    return (pair for pair, count in pairs.items() if count >= 2)


@dataclass(frozen=True)
class Alignment:
    left: int
    right: int
    rows: tuple[tuple[Reference, Reference], ...]


def shared_line_count(rows: Iterable[tuple[Reference, ...]]) -> int:
    return min(len({ref[0] for ref in column}) for column in zip(*rows, strict=True))


def distinct_references(rows: Iterable[tuple[Reference, ...]]) -> int:
    return len({row[0][2] for row in rows})


def align_references(left, right, left_names, right_names):
    blocks = SequenceMatcher(None, left_names, right_names, autojunk=False).get_matching_blocks()
    return tuple((left[a + offset], right[b + offset]) for a, b, size in blocks for offset in range(size))


def align_proofs(proofs: list[Proof]) -> Iterator[Alignment]:
    names = [[name for _, _, name in proof.references] for proof in proofs]
    frequency = Counter(name for sequence in names for name in set(sequence))
    for i, j in reference_candidates(names):
        left, right = proofs[i], proofs[j]
        rows = tuple(
            (a, b)
            for a, b in align_references(left.references, right.references, names[i], names[j])
            if frequency[a[2]] < COMMON
        )
        if distinct_references(rows) >= 7 and shared_line_count(rows) >= 6:
            yield Alignment(i, j, rows)


@dataclass(frozen=True)
class ProofFamily:
    members: tuple[int, ...]
    rows: tuple[tuple[Reference, ...], ...]
    shared_lines: int

    @property
    def score(self) -> int:
        return (len(self.members) - 1) * self.shared_lines


def rank_families(alignments: Iterable[Alignment]) -> list[ProofFamily]:
    # For a shared proof, use its exact occurrence as the join key. Pair hits
    # on unrelated sections of that proof never enter one family.
    by_pivot: dict[int, dict[int, dict[Reference, Reference]]] = defaultdict(dict)
    for hit in alignments:
        by_pivot[hit.left][hit.right] = dict(hit.rows)
        by_pivot[hit.right][hit.left] = {right: left for left, right in hit.rows}
    families: dict[tuple[int, ...], ProofFamily] = {}
    for pivot, peers in by_pivot.items():
        cores = {frozenset(left.keys() & right.keys()) for left, right in combinations(peers.values(), 2)}
        for core in sorted(cores, key=lambda refs: sorted(refs)):
            if len({ref[2] for ref in core}) < 7 or len({ref[0] for ref in core}) < 6:
                continue
            supporting = [index for index, sites in peers.items() if core <= sites.keys()]
            members = tuple(sorted([pivot, *supporting]))
            rows = tuple(
                tuple(site if index == pivot else peers[index][site] for index in members) for site in sorted(core)
            )
            lines = shared_line_count(rows)
            if lines < 6:
                continue
            family = ProofFamily(members, rows, lines)
            prior = families.get(members)
            if prior is None or (lines, len(rows), rows) > (prior.shared_lines, len(prior.rows), prior.rows):
                families[members] = family
    return sorted(families.values(), key=lambda family: (-family.score, -len(family.members), family.members))
