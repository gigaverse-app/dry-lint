"""Optional upstream Dryer comparer for the canonical Python corpus."""

from __future__ import annotations

import textwrap
from collections.abc import Callable
from importlib.metadata import version
from typing import TYPE_CHECKING, Annotated

from pydantic import Field, validate_call

from dry_lint.models import Function

if TYPE_CHECKING:
    from dryer.model import Entry


class DryerComparer:
    name = "dryer"
    similarity_reusable = False  # Normalization erases literals and fields; a flat score cannot settle changed logic.

    @validate_call
    def __init__(
        self,
        threshold: Annotated[float, Field(gt=0, le=1)] = 0.82,
        min_lines: Annotated[int, Field(ge=1)] = 4,
        min_nodes: Annotated[int, Field(ge=1)] = 20,
    ) -> None:
        try:
            from dryer.extract import entries_in_source
            from dryer.shape import jaccard
        except ImportError as error:
            raise ValueError("Dryer requires the optional dependency: install 'dry-lint[dryer]'.") from error
        self._extract, self._jaccard = entries_in_source, jaccard
        self.version = f"66ff6d2-{version('tree-sitter-language-pack')}"
        self.threshold, self.min_lines, self.min_nodes = threshold, min_lines, min_nodes
        self.entries: dict[tuple[str, int], Entry | None] = {}
        self.by_size: dict[int, list[tuple[int, Function, Entry]]] = {}

    def index(self, functions: list[Function]) -> None:
        # Overloads can share a qualified name; their source spans identify different fingerprints.
        self.entries = {(f.path, f.line): self._entry(f) for f in functions}
        self.by_size = {}
        for position, function in enumerate(functions):
            entry = self.entries[(function.path, function.line)]
            if self._eligible(entry):
                assert entry is not None
                self.by_size.setdefault(len(entry.fingerprints), []).append((position, function, entry))

    def _entry(self, function: Function) -> Entry | None:
        if not function.path.endswith(".py"):
            return None
        entries, warning = self._extract("python", textwrap.dedent(function.code), function.path, function.path)
        if warning or not entries:
            raise ValueError(f"Dryer could not extract {function.qualname}: {warning or 'no Python function'}")
        # Nested definitions remain part of the canonical outer function.
        return entries[0]

    def _eligible(self, entry: Entry | None) -> bool:
        return (
            entry is not None
            and entry.end_line - entry.start_line + 1 >= self.min_lines
            and entry.nodes >= self.min_nodes
        )

    def _get(self, function: Function) -> Entry | None:
        location = (function.path, function.line)
        return self.entries[location] if location in self.entries else self._entry(function)

    def neighbours(
        self, function: Function, k: int, allowed: Callable[[Function], bool]
    ) -> list[tuple[Function, float]]:
        entry = self._get(function)
        if not self._eligible(entry):
            return []
        assert entry is not None
        found = []
        for size, targets in self.by_size.items():
            # Set-size ratio bounds Jaccard. Exclude impossible size buckets before visiting their functions.
            smaller, larger = sorted((len(entry.fingerprints), size))
            if larger and smaller / larger < self.threshold:
                continue
            for position, other, target in targets:
                if other.qualname == function.qualname or not allowed(other):
                    continue
                score = self._jaccard(entry.fingerprints, target.fingerprints)
                if score >= self.threshold:
                    found.append((other, score, position))
        # Bucket order is unrelated to source order; retain the original tie-breaking contract explicitly.
        return [(other, score) for other, score, _ in sorted(found, key=lambda pair: (-pair[1], pair[2]))[:k]]

    def similarity(self, a: Function, b: Function) -> float:
        left, right = self._get(a), self._get(b)
        if left is None or right is None:
            return 0.0
        return self._jaccard(left.fingerprints, right.fingerprints)
