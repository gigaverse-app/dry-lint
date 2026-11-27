"""
Find source fragments repeated inside functions, in every language an extractor reads.

The scan compares lines of source, up to indentation. It needs no judge and no model: it lists
places where the same lines were written more than once, for a person to decide whether they
are one operation. Whole-function comparers miss these when the surrounding functions differ.
"""

from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path

from dry_lint.functions import dedent_lines, extractor_for, tracked_files
from dry_lint.plugins import Extractor

#: A path, the line its first row is on, and consecutive rows of source.
Run = tuple[str, int, list[str]]

#: `blocks` stops growing a match here. A longer repetition is reported as overlapping matches.
LONGEST = 200


@dataclass(frozen=True)
class Block:
    path: str
    line: int
    code: tuple[str, ...]
    anchors: tuple[str, ...] = ()
    #: The last source line, where the rows are not consecutive lines of the file.
    end_line: int = 0

    @property
    def compared_code(self) -> tuple[str, ...]:
        return self.anchors or self.code


def find_groups(
    runs: Iterable[tuple[str, int, list[str]]],
    lines: int,
    min_shared_chars: int,
    allow_one_line_difference: bool,
) -> set[tuple[Block, ...]]:
    masks = (-1, *range(1, lines - 1)) if allow_one_line_difference else (-1,)
    found: dict[tuple[str, ...], list[Block]] = defaultdict(list)
    for path, start, run in runs:
        for offset in range(len(run) - lines + 1):
            _, code = dedent_lines(run[offset : offset + lines])
            block = Block(path, start + offset, code)
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


def find_gapped_groups(
    runs: Iterable[tuple[str, int, list[str]]], lines: int, min_shared_chars: int, max_gap_lines: int
) -> set[tuple[Block, ...]]:
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
                copies.append(Block(path, start + offset, code, anchors))
                end_by_path[path] = start + end
        if len({block.code for block in copies}) > 1:
            groups.add(tuple(copies))
    return groups


def group_order(group: tuple[Block, ...]) -> tuple[int, int, tuple[tuple[str, int, int], ...]]:
    shared_chars = sum(
        len(column[0].strip())
        for column in zip(*(block.compared_code for block in group), strict=True)
        if len(set(column)) == 1
    )
    return -shared_chars, -len(group), tuple((block.path, block.line, len(block.code)) for block in group)


def _shared_lines(group: tuple[Block, ...]) -> int:
    return sum(len(set(column)) == 1 for column in zip(*(block.compared_code for block in group), strict=True))


def _distinct_copies(group: tuple[Block, ...]) -> int:
    """Count disjoint occurrences, including repetitions within a single file."""
    path, end = "", 0
    count = 0
    for block in group:
        if block.path != path or block.line >= end:
            path, end = block.path, block.line + len(block.code)
            count += 1
    return count


def prioritize_reuse(groups: set[tuple[Block, ...]]) -> list[tuple[Block, ...]]:
    ranked = sorted(
        groups,
        key=lambda group: (
            -_shared_lines(group) * (_distinct_copies(group) - 1),
            -len(group[0].compared_code),
            sum(len(block.code) for block in group),
            group_order(group),
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


def check_options(lines: int, min_shared_chars: int, max_lines: int | None, max_gap_lines: int) -> None:
    if lines < 3 or min_shared_chars < 1:
        raise ValueError("--lines must be at least 3 and --min-shared-chars must be positive")
    if max_lines is not None and max_lines < lines:
        raise ValueError("--max-lines must be at least --lines")
    if max_gap_lines < 0:
        raise ValueError("--max-gap-lines must be nonnegative")


def _longest_groups(
    runs: list[Run], lines: int, min_shared_chars: int, allow_one_line_difference: bool, max_lines: int
) -> set[tuple[Block, ...]]:
    """
    Matches of every length from `lines` up. A run whose rows match nothing at one length matches nothing
    at a longer one, so it is dropped. That holds for matches of any size in characters, which is why
    `min_shared_chars` is applied to what is kept and not to what keeps a run in play.
    """
    groups: set[tuple[Block, ...]] = set()
    for length in range(lines, max_lines + 1):
        found = find_groups(runs, length, 1, allow_one_line_difference)
        if not found:
            break
        groups.update(group for group in found if -group_order(group)[0] >= min_shared_chars)
        matched = {(block.path, block.line) for group in found for block in group}
        runs = [
            (path, start, run)
            for path, start, run in runs
            if any((path, start + offset) in matched for offset in range(len(run) - length + 1))
        ]
    return groups


def ranked_groups(
    runs: list[Run],
    *,
    lines: int,
    min_shared_chars: int,
    allow_one_line_difference: bool,
    max_lines: int,
    max_gap_lines: int,
) -> list[tuple[Block, ...]]:
    """Matches of `lines` to `max_lines` rows, the most reusable first, without those a longer match covers."""
    if max_gap_lines:
        groups = set()
        for length in range(lines, min(max_lines, max((len(run) for _, _, run in runs), default=0)) + 1):
            groups.update(find_gapped_groups(runs, length, min_shared_chars, max_gap_lines))
            if allow_one_line_difference:
                groups.update(find_groups(runs, length, min_shared_chars, allow_one_line_difference))
    else:
        groups = _longest_groups(runs, lines, min_shared_chars, allow_one_line_difference, max_lines)
    return prioritize_reuse(groups)


def function_lines(extractor: Extractor, path: str, source: str) -> Iterator[list[tuple[int, str]]]:
    """Each outermost function as numbered lines, without blank lines and lines that hold only a comment."""
    comment = getattr(extractor, "line_comment", None)
    rows = source.split("\n")
    end = 0
    for function in sorted(extractor.functions(path, source), key=lambda f: (f.line, -f.end_line)):
        if function.line <= end:
            continue  # Nested in the function before it, whose lines already include these.
        end = function.end_line
        yield [
            (number, rows[number - 1].rstrip())
            for number in range(function.line, min(end, len(rows)) + 1)
            if rows[number - 1].strip() and not (comment and rows[number - 1].lstrip().startswith(comment))
        ]


def find_blocks(
    root: Path,
    include: list[str],
    exclude: list[str],
    extractors: list[Extractor],
    *,
    lines: int,
    min_shared_chars: int,
    allow_one_line_difference: bool = False,
    max_lines: int | None = None,
    max_gap_lines: int = 0,
) -> list[list[Block]]:
    """
    Repeated fragments in the tracked files, the most reusable first: by lines shared across disjoint
    copies, with a match hidden when a longer match covers every copy of it.

    An extractor may define `block_runs(path, source)` to choose the lines that are compared, as numbered
    lines per run; a match never crosses from one run to the next. The default is `function_lines`.
    """
    check_options(lines, min_shared_chars, max_lines, max_gap_lines)
    runs: list[Run] = []
    # Blank and comment lines are left out of a run, so a match is found in rows and reported in source lines.
    numbers: dict[str, list[int]] = defaultdict(list)
    for path in tracked_files(root, include, exclude):
        extractor = extractor_for(path, extractors)
        if extractor is None:
            continue
        try:
            source = (root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        block_runs = getattr(extractor, "block_runs", None)
        for run in block_runs(path, source) if block_runs else function_lines(extractor, path, source):
            if len(run) >= lines:
                runs.append((path, len(numbers[path]), [text for _, text in run]))
                numbers[path].extend(number for number, _ in run)
    groups = ranked_groups(
        runs,
        lines=lines,
        min_shared_chars=min_shared_chars,
        allow_one_line_difference=allow_one_line_difference,
        max_lines=max_lines or (lines if max_gap_lines else LONGEST),
        max_gap_lines=max_gap_lines,
    )
    return [
        [
            replace(
                block,
                line=numbers[block.path][block.line],
                end_line=numbers[block.path][block.line + len(block.code) - 1],
            )
            for block in group
        ]
        for group in groups
    ]
