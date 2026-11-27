"""Read what a unified diff removes, to leave out work an open pull request already does."""

from collections import defaultdict


def removed_lines(diffs):
    """The lines each unified diff removes, without indentation, by the path it removes them from."""
    removed = defaultdict(set)
    for diff in diffs:
        path = None
        rows = diff.read_text(encoding="utf-8", errors="replace").splitlines()
        for row, following in zip(rows, [*rows[1:], ""], strict=True):
            # A removed Lean comment also starts with `--- `; a file header is followed by `+++ `.
            if row.startswith("--- ") and following.startswith("+++ "):
                path = row[4:].split("\t")[0].removeprefix("a/")
            elif row.startswith("-") and path and row[1:].strip():
                removed[path].add(row[1:].strip())
    return removed
