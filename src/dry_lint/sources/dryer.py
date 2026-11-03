"""Use upstream Dryer's Python normalization and Jaccard score on dry-lint's corpus."""

import textwrap

from dryer.extract import entries_in_source
from dryer.model import Entry
from dryer.shape import jaccard

from dry_lint.functions import Function
from dry_lint.settings import Settings


class DryerSource:
    def __init__(self, functions: list[Function], settings: Settings) -> None:
        self.functions = functions
        self.settings = settings
        # Overloads share a qualified name but have different source spans and fingerprints.
        self.entries = {(f.path, f.line): self._entry(f) for f in functions}

    def _entry(self, function: Function) -> Entry | None:
        entries, warning = entries_in_source("python", textwrap.dedent(function.code), function.path, function.path)
        if warning or not entries:
            raise ValueError(f"Dryer could not extract {function.qualname}: {warning or 'no Python function'}")
        # Nested definitions remain part of the canonical outer Function; they are not extra corpus members.
        entry = entries[0]
        if entry.end_line - entry.start_line + 1 < self.settings.dryer_min_lines:
            return None
        return entry if entry.nodes >= self.settings.dryer_min_nodes else None

    def similar(self, function: Function, limit: int) -> list[tuple[int, float]]:
        location = (function.path, function.line)
        entry = self.entries[location] if location in self.entries else self._entry(function)
        if entry is None:
            return []
        found = []
        for position, other in enumerate(self.functions):
            target = self.entries[(other.path, other.line)]
            if target is None or other.qualname == function.qualname:
                continue
            # Set-size ratio is an upper bound on Jaccard; skip only provably impossible matches.
            smaller, larger = sorted((len(entry.fingerprints), len(target.fingerprints)))
            if larger and smaller / larger < self.settings.dryer_threshold:
                continue
            score = jaccard(entry.fingerprints, target.fingerprints)
            if score >= self.settings.dryer_threshold:
                found.append((position, score))
        return sorted(found, key=lambda pair: (-pair[1], pair[0]))[:limit]
