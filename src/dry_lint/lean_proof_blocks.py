"""Find repeated source fragments within Lean tactic proofs, including recovered proof ranges."""

from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Query, QueryCursor

from dry_lint.functions import tracked_files
from dry_lint.lean import LeanExtractor


@dataclass(frozen=True)
class ProofBlock:
    path: str
    line: int
    code: tuple[str, ...]


def _proof_lines(extractor: LeanExtractor, query: Query, source: str) -> Iterator[tuple[int, list[str]]]:
    tree = extractor.parser.parse(source.encode("utf-8"))
    captures = QueryCursor(query).captures(tree.root_node)
    rows = source.split("\n")
    noncode = {
        row
        for node in captures.get("noncode", [])
        if node.start_point.row != node.end_point.row or node.type.endswith("comment")
        for row in range(node.start_point.row, node.end_point.row + 1)
    }
    # Nested by nodes can cover the same lines. Enumerate each location once.
    previous_end = 0
    for proof in sorted(captures.get("proof", []), key=lambda node: (node.start_byte, -node.end_byte)):
        start = max(previous_end, proof.start_point.row + 1)
        end = proof.end_point.row
        if end < len(rows) and proof.end_point.column >= len(rows[end].rstrip().encode("utf-8")):
            end += 1
        if start >= end:
            continue
        previous_end = end
        run = []
        for row in range(start, end):
            if row in noncode or not rows[row].strip() or rows[row].lstrip().startswith("--"):
                if run:
                    yield row - len(run) + 1, run
                run = []
            else:
                run.append(rows[row].rstrip())
        if run:
            yield end - len(run) + 1, run


def _blocks(extractor: LeanExtractor, query: Query, path: str, source: str, lines: int) -> Iterator[ProofBlock]:
    for start, run in _proof_lines(extractor, query, source):
        for offset in range(len(run) - lines + 1):
            window = run[offset : offset + lines]
            left = min(len(line) - len(line.lstrip()) for line in window)
            yield ProofBlock(path, start + offset, tuple(line[left:] for line in window))


def _group_order(group: tuple[ProofBlock, ...]) -> tuple[int, int, tuple[tuple[str, int], ...]]:
    shared_chars = sum(
        len(column[0].strip()) for column in zip(*(block.code for block in group), strict=True) if len(set(column)) == 1
    )
    return -shared_chars, -len(group), tuple((block.path, block.line) for block in group)


def find_proof_blocks(
    root: Path,
    include: list[str],
    exclude: list[str],
    *,
    lines: int,
    min_shared_chars: int,
    allow_one_line_difference: bool,
) -> list[list[ProofBlock]]:
    """Match lines verbatim up to a common indent shift, optionally varying one interior line."""
    if lines < 3 or min_shared_chars < 1:
        raise ValueError("--lines must be at least 3 and --min-shared-chars must be positive")
    try:
        extractor = LeanExtractor()
    except ImportError as error:
        raise ValueError(str(error)) from error

    query = Query(
        extractor.parser.language,
        """
        (by) @proof
        [(block_comment) (doc_comment) (module_doc_comment) (str_lit) (raw_string)] @noncode
        """,
    )
    masks = (-1, *range(1, lines - 1)) if allow_one_line_difference else (-1,)
    found: dict[tuple[str, ...], list[ProofBlock]] = defaultdict(list)
    for path in tracked_files(root, include, exclude):
        file = root / path
        if file.suffix != ".lean" or not file.is_file():
            continue
        for block in _blocks(extractor, query, path, file.read_text(encoding="utf-8"), lines):
            # Hold the shape of the layout fixed even at the differing line.
            for mask in masks:
                shared = sum(len(line.strip()) for index, line in enumerate(block.code) if index != mask)
                if shared >= min_shared_chars:
                    key = tuple(
                        line[: len(line) - len(line.lstrip())] if i == mask else line
                        for i, line in enumerate(block.code)
                    )
                    found[key].append(block)

    groups = {
        tuple(sorted(group, key=lambda block: (block.path, block.line))) for group in found.values() if len(group) > 1
    }
    return [list(group) for group in sorted(groups, key=_group_order)]
