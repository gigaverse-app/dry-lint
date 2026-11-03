"""
The four plugin slots. Everything else (the pipeline, the file formats, the reuse rules, the reports) is core.

- An **extractor** splits a source file into functions and gives each a structure hash: one per language.
- A **comparer** indexes all functions and proposes each changed one's nearest look-alikes, with a 0-1 similarity.
- A **judge** decides whether a candidate pair is one concept implemented twice.
- A **store backend** keeps verdict records by key.

A plugin is any class that implements its protocol. dry-lint finds it by name among its built-ins, or under the
entry-point group `dry_lint.<slot>s` of any installed package:

    [project.entry-points."dry_lint.comparers"]
    embedding = "my_package.comparer:EmbeddingComparer"

and constructs it with the options from its settings table.
"""

from collections.abc import Callable, Iterator
from importlib import import_module
from importlib.metadata import entry_points
from typing import Any, Protocol

from dry_lint.models import Candidate, Function, Verdict
from dry_lint.settings import PluginChoice, Settings


class Extractor(Protocol):
    name: str
    version: str
    files: tuple[str, ...]  # fnmatch globs over paths it reads, e.g. ("*.py",)

    def functions(self, path: str, source: str) -> list[Function]:
        """Every function in the file, without `hash`: core asks for that only for the functions in a pair."""
        ...

    def structure_hash(self, function: Function) -> str:
        """Changes when the function's logic changes; not for comments, formatting or renames."""
        ...


class Comparer(Protocol):
    name: str
    version: str  # bump when similarities change meaning: stored ones are only compared within a version

    def index(self, functions: list[Function]) -> None: ...

    def neighbours(self, function: Function, k: int,
                   allowed: Callable[[Function], bool]) -> list[tuple[Function, float]]:
        """Up to `k` indexed functions for which `allowed` holds, most similar first, above the comparer's floor."""
        ...

    def similarity(self, a: Function, b: Function) -> float: ...


class Judge(Protocol):
    name: str
    version: str  # model and prompt version: part of every verdict

    def judge(self, candidates: list[Candidate], settings: Settings) -> list[Verdict]:
        """One verdict per candidate, in order. Use `judges.label_for` so labels follow the thresholds."""
        ...


class StoreBackend(Protocol):
    def get(self, key: str) -> bytes | None: ...

    def put(self, key: str, data: bytes) -> None: ...

    def keys(self) -> Iterator[str]: ...


BUILT_IN = {
    "extractors": {"python": "dry_lint.extractors:PythonExtractor"},
    "comparers": {"tfidf": "dry_lint.comparers:TfidfComparer"},
    "judges": {"jev": "dry_lint.judges.jev:JevJudge", "command": "dry_lint.judges.command:CommandJudge"},
    "stores": {"dir": "dry_lint.store:DirectoryStore", "s3": "dry_lint.store:S3Store"},
}


def plugin_class(slot: str, name: str) -> type:
    if name in BUILT_IN[slot]:
        module, _, attribute = BUILT_IN[slot][name].partition(":")
        return getattr(import_module(module), attribute)
    installed = {point.name: point for point in entry_points(group=f"dry_lint.{slot}")}
    if name in installed:
        return installed[name].load()
    known = ", ".join(sorted({*BUILT_IN[slot], *installed}))
    raise ValueError(f"Unknown {slot.removesuffix('s')} {name!r}; available: {known}")


def load(slot: str, choice: PluginChoice, **defaults: Any) -> Any:
    """The plugin `choice` names, built with its options; `defaults` fill options the settings leave out."""
    return plugin_class(slot, choice.use)(**{**defaults, **choice.options()})


def identity(plugin: Any) -> str:
    return f"{plugin.name}:{plugin.version}"
