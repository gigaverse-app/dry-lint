"""Find repeated source fragments within Lean tactic proofs, including recovered proof ranges."""

import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Query, QueryCursor

from dry_lint.functions import tracked_files
from dry_lint.lean import LeanExtractor

_COMMAND_START = re.compile(
    r"^\s*(?:(?:@\[[^\n]*?\]|private|protected|public|noncomputable|local|scoped|unsafe|partial)\s+)*"
    r"(?:lemma|theorem|def|abbrev|opaque|instance|example|section|namespace|end)\b"
)


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
        if proof.has_error:
            # Recovery can swallow the signature of a later declaration into this by node.
            end = next(
                (row for row in range(start, end) if row not in noncode and _COMMAND_START.match(rows[row])), end
            )
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


def _source_runs(
    root: Path, include: list[str], exclude: list[str], extractor: LeanExtractor, query: Query
) -> Iterator[tuple[str, int, list[str]]]:
    for path in tracked_files(root, include, exclude):
        file = root / path
        if file.suffix != ".lean" or not file.is_file():
            continue
        for start, run in _proof_lines(extractor, query, file.read_text(encoding="utf-8")):
            yield path, start, run


def _find_groups(
    runs: Iterable[tuple[str, int, list[str]]],
    lines: int,
    min_shared_chars: int,
    allow_one_line_difference: bool,
) -> set[tuple[ProofBlock, ...]]:
    masks = (-1, *range(1, lines - 1)) if allow_one_line_difference else (-1,)
    found: dict[tuple[str, ...], list[ProofBlock]] = defaultdict(list)
    for path, start, run in runs:
        for offset in range(len(run) - lines + 1):
            window = run[offset : offset + lines]
            left = min(len(line) - len(line.lstrip()) for line in window)
            block = ProofBlock(path, start + offset, tuple(line[left:] for line in window))
            # Hold the shape of the layout fixed even at the differing line.
            sizes = [len(line.strip()) for line in block.code]
            total = sum(sizes)
            for mask in masks:
                shared = total - sizes[mask] if mask >= 0 else total
                if shared < min_shared_chars:
                    continue
                key = tuple(
                    line[: len(line) - len(line.lstrip())] if i == mask else line for i, line in enumerate(block.code)
                )
                found[key].append(block)
    return {
        tuple(sorted(group, key=lambda block: (block.path, block.line))) for group in found.values() if len(group) > 1
    }


def _group_order(group: tuple[ProofBlock, ...]) -> tuple[int, int, tuple[tuple[str, int], ...]]:
    shared_chars = sum(
        len(column[0].strip()) for column in zip(*(block.code for block in group), strict=True) if len(set(column)) == 1
    )
    return -shared_chars, -len(group), tuple((block.path, block.line) for block in group)


def _shared_lines(group: tuple[ProofBlock, ...]) -> int:
    return sum(len(set(column)) == 1 for column in zip(*(block.code for block in group), strict=True))


def _distinct_copies(group: tuple[ProofBlock, ...]) -> int:
    """Count disjoint occurrences, including repetitions within a single file."""
    path, end = "", 0
    count = 0
    for block in group:
        if block.path != path or block.line >= end:
            path, end = block.path, block.line + len(block.code)
            count += 1
    return count


def _prioritize_reuse(groups: set[tuple[ProofBlock, ...]]) -> list[tuple[ProofBlock, ...]]:
    ranked = sorted(
        groups,
        key=lambda group: (
            -_shared_lines(group) * (_distinct_copies(group) - 1),
            -len(group[0].code),
            _group_order(group),
        ),
    )
    kept = []
    covering: dict[tuple[str, int], list[tuple[int, int]]] = defaultdict(list)
    locations = []
    for group in ranked:
        if _distinct_copies(group) < 2:
            continue
        first = group[0]
        length = len(first.code)
        if any(
            length + offset <= len(kept[index][0].code)
            and all((block.path, block.line - offset) in locations[index] for block in group)
            for index, offset in covering[first.path, first.line]
        ):
            continue
        for block in group:
            for offset in range(length):
                covering[block.path, block.line + offset].append((len(kept), offset))
        locations.append({(block.path, block.line) for block in group})
        kept.append(group)
    return kept


def find_proof_blocks(
    root: Path,
    include: list[str],
    exclude: list[str],
    *,
    lines: int,
    min_shared_chars: int,
    allow_one_line_difference: bool,
    max_lines: int | None = None,
) -> list[list[ProofBlock]]:
    """Match lines verbatim up to a common indent shift, optionally varying one interior line."""
    if lines < 3 or min_shared_chars < 1:
        raise ValueError("--lines must be at least 3 and --min-shared-chars must be positive")
    if max_lines is not None and max_lines < lines:
        raise ValueError("--max-lines must be at least --lines")
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
    runs = _source_runs(root, include, exclude, extractor, query)
    if max_lines is None:
        matches = sorted(_find_groups(runs, lines, min_shared_chars, allow_one_line_difference), key=_group_order)
    else:
        # Parse each file once, then free each length's index before comparing the next.
        cached_runs = list(runs)
        max_length = min(max_lines, max((len(run) for _, _, run in cached_runs), default=0))
        groups = set()
        for length in range(lines, max_length + 1):
            groups.update(_find_groups(cached_runs, length, min_shared_chars, allow_one_line_difference))
        matches = _prioritize_reuse(groups)
    return [list(group) for group in matches]
