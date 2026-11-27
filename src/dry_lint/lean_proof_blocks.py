"""Find repeated source fragments within Lean tactic proofs."""

import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from dry_lint.functions import dedent_lines, tracked_files
from dry_lint.lean import BRACKETS, LeanExtractor, LeanSource, read_source

_STEP = re.compile(rf"\bby\b|[{re.escape(''.join(BRACKETS))}]")
_BY_ENDS_LINE = re.compile(r"\bby\s*$")


@dataclass(frozen=True)
class ProofBlock:
    path: str
    line: int
    code: tuple[str, ...]
    anchors: tuple[str, ...] = ()

    @property
    def compared_code(self) -> tuple[str, ...]:
        return self.anchors or self.code


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _opens_proof(line: str) -> bool:
    """Whether a `by` is still open where the line ends, rather than closed by a bracket around it."""
    depth = 0
    opened = None
    for step in _STEP.finditer(line):
        if step.group() == "by":
            opened = depth if opened is None else opened
        elif step.group() in BRACKETS[0]:
            depth += 1
        else:
            depth -= 1
            if opened is not None and depth < opened:
                opened = None
    return opened is not None


def _proof_rows(lean: LeanSource, code: list[str]) -> Iterator[int]:
    """Rows of tactic blocks, by Lean's layout rule, within the command that opens each block."""
    for command in lean.commands:
        first, last = lean.line(command.start) - 1, lean.line(command.end) - 1
        row = first
        while row <= last:
            opening = code[row]
            row += 1
            if "by" not in opening or not _opens_proof(opening):
                continue
            block = next((r for r in range(row, last + 1) if code[r].strip()), None)
            if block is None:
                break
            # The steps after a line that ends with `by` share a column. After `by step`, deeper lines continue it.
            column = _indent(code[block]) if _BY_ENDS_LINE.search(opening) else _indent(opening) + 1
            if column <= _indent(code[first]):
                continue
            while row <= last and (not code[row].strip() or _indent(code[row]) >= column):
                if code[row].strip():
                    yield row
                row += 1


def _proof_lines(source: str) -> Iterator[tuple[int, list[str]]]:
    lean = read_source(source)
    rows = source.split("\n")
    # A row that only holds a comment is blank in the structural copy and ends a run, as a blank line does.
    proof = set(_proof_rows(lean, lean.structure.split("\n")))
    for start, end in lean.literals:
        if "\n" in source[start:end]:
            proof.difference_update(range(lean.line(start) - 1, lean.line(end - 1)))
    first = 0
    run: list[str] = []
    for row in sorted(proof):
        if run and row - 1 not in proof:
            yield first + 1, run
            run = []
        if not run:
            first = row
        run.append(rows[row].rstrip())
    if run:
        yield first + 1, run


def _source_runs(root: Path, include: list[str], exclude: list[str]) -> Iterator[tuple[str, int, list[str]]]:
    for path in tracked_files(root, include, exclude):
        file = root / path
        if file.suffix != ".lean" or not file.is_file():
            continue
        for start, run in _proof_lines(file.read_text(encoding="utf-8")):
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
            _, code = dedent_lines(run[offset : offset + lines])
            block = ProofBlock(path, start + offset, code)
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


def _find_gapped_groups(
    runs: Iterable[tuple[str, int, list[str]]], lines: int, min_shared_chars: int, max_gap_lines: int
) -> set[tuple[ProofBlock, ...]]:
    """Match two exact anchors with an independently sized gap at each occurrence."""
    prefix = lines // 2
    found: dict[tuple[str, ...], list[tuple[str, int, list[str], int, int]]] = defaultdict(list)
    for path, start, run in runs:
        for offset in range(len(run) - lines + 1):
            first = run[offset : offset + prefix]
            last_gap = min(max_gap_lines, len(run) - offset - lines)
            for gap in range(last_gap + 1):
                end = offset + lines + gap
                anchors = first + run[offset + prefix + gap : end]
                if sum(len(line.strip()) for line in anchors) >= min_shared_chars:
                    _, key = dedent_lines(anchors)
                    found[key].append((path, start, run, offset, end))

    groups = set()
    for anchors, occurrences in found.items():
        if len(occurrences) < 2:
            continue
        # Prefer the earliest finishing interval in each file, so a match needs
        # two distinct copies even when a window can align with itself twice.
        end_by_path: dict[str, int] = {}
        copies = []
        for path, start, run, offset, end in sorted(occurrences, key=lambda row: (row[0], row[1] + row[4])):
            if start + offset >= end_by_path.get(path, 0):
                _, code = dedent_lines(run[offset:end])
                copies.append(ProofBlock(path, start + offset, code, anchors))
                end_by_path[path] = start + end
        if len({block.code for block in copies}) > 1:
            groups.add(tuple(copies))
    return groups


def _group_order(group: tuple[ProofBlock, ...]) -> tuple[int, int, tuple[tuple[str, int, int], ...]]:
    shared_chars = sum(
        len(column[0].strip())
        for column in zip(*(block.compared_code for block in group), strict=True)
        if len(set(column)) == 1
    )
    return -shared_chars, -len(group), tuple((block.path, block.line, len(block.code)) for block in group)


def _shared_lines(group: tuple[ProofBlock, ...]) -> int:
    return sum(len(set(column)) == 1 for column in zip(*(block.compared_code for block in group), strict=True))


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
            -len(group[0].compared_code),
            sum(len(block.code) for block in group),
            _group_order(group),
        ),
    )
    kept = []
    covering: dict[tuple[str, int], list[tuple[int, int]]] = defaultdict(list)
    locations: list[dict[tuple[str, int], int]] = []
    for group in ranked:
        if _distinct_copies(group) < 2:
            continue
        first = group[0]
        if any(
            len(first.compared_code) <= len(kept[index][0].compared_code)
            and all(
                len(block.code) + offset <= locations[index].get((block.path, block.line - offset), 0)
                for block in group
            )
            for index, offset in covering[first.path, first.line]
        ):
            continue
        for block in group:
            for offset in range(len(block.code)):
                covering[block.path, block.line + offset].append((len(kept), offset))
        locations.append({(block.path, block.line): len(block.code) for block in group})
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
    max_gap_lines: int = 0,
) -> list[list[ProofBlock]]:
    """Match proof fragments up to indentation, with optional interior differences or gaps."""
    if lines < 3 or min_shared_chars < 1:
        raise ValueError("--lines must be at least 3 and --min-shared-chars must be positive")
    if max_lines is not None and max_lines < lines:
        raise ValueError("--max-lines must be at least --lines")
    if max_gap_lines < 0:
        raise ValueError("--max-gap-lines must be nonnegative")
    try:
        LeanExtractor()  # The command is part of the Lean extra, whose absence gets the same message everywhere.
    except ImportError as error:
        raise ValueError(str(error)) from error

    runs = _source_runs(root, include, exclude)
    if max_lines is None and not max_gap_lines:
        matches = sorted(_find_groups(runs, lines, min_shared_chars, allow_one_line_difference), key=_group_order)
    else:
        # Parse each file once, then free each length's index before comparing the next.
        cached_runs = list(runs)
        max_length = min(max_lines or lines, max((len(run) for _, _, run in cached_runs), default=0))
        groups = set()
        for length in range(lines, max_length + 1):
            if max_gap_lines:
                groups.update(_find_gapped_groups(cached_runs, length, min_shared_chars, max_gap_lines))
            if not max_gap_lines or allow_one_line_difference:
                groups.update(_find_groups(cached_runs, length, min_shared_chars, allow_one_line_difference))
        matches = _prioritize_reuse(groups)
    return [list(group) for group in matches]
