"""Candidate-source plugins. Repository policy and judging remain in Detector."""

from typing import Protocol

from dry_lint.functions import Function, behaviour_tokens
from dry_lint.index import TfidfIndex
from dry_lint.settings import Settings


class CandidateSource(Protocol):
    def similar(self, function: Function, limit: int, exclude: set[int]) -> list[tuple[int, float]]:
        """Rank corpus positions, applying the caller's exclusions before limiting."""
        ...


class TfidfSource:
    def __init__(self, functions: list[Function]) -> None:
        self.index = TfidfIndex([behaviour_tokens(f) for f in functions])

    def similar(self, function: Function, limit: int, exclude: set[int]) -> list[tuple[int, float]]:
        return self.index.similar(behaviour_tokens(function), limit=limit, exclude=exclude)


def make_source(functions: list[Function], settings: Settings) -> CandidateSource:
    if settings.detector == "dryer":
        # Optional dependency: a normal installation never imports tree-sitter.
        try:
            from dry_lint.sources.dryer import DryerSource
        except ImportError as error:
            raise ValueError("Dryer requires the optional dependency: install 'dry-lint[dryer]'.") from error
        return DryerSource(functions, settings)
    return TfidfSource(functions)
