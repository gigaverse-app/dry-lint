"""Find repeated source fragments within Lean tactic proofs."""

import re
from collections.abc import Iterator
from pathlib import Path

from dry_lint.blocks import Block as ProofBlock
from dry_lint.blocks import check_options, find_groups, group_order, ranked_groups
from dry_lint.functions import tracked_files
from dry_lint.lean import BRACKETS, LeanExtractor, LeanSource, read_source

_STEP = re.compile(rf"\bby\b|[{re.escape(''.join(BRACKETS))}]")
_BY_ENDS_LINE = re.compile(r"\bby\s*$")


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


def proof_lines(source: str) -> Iterator[tuple[int, list[str]]]:
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
        for start, run in proof_lines(file.read_text(encoding="utf-8")):
            yield path, start, run


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
    check_options(lines, min_shared_chars, max_lines, max_gap_lines)
    try:
        LeanExtractor()  # The command is part of the Lean extra, whose absence gets the same message everywhere.
    except ImportError as error:
        raise ValueError(str(error)) from error

    runs = _source_runs(root, include, exclude)
    if max_lines is None and not max_gap_lines:
        matches = sorted(find_groups(runs, lines, min_shared_chars, allow_one_line_difference), key=group_order)
    else:
        matches = ranked_groups(
            list(runs),
            lines=lines,
            min_shared_chars=min_shared_chars,
            allow_one_line_difference=allow_one_line_difference,
            max_lines=max_lines or lines,
            max_gap_lines=max_gap_lines,
        )
    return [list(group) for group in matches]
