"""
The detector: which functions changed, and which existing functions elsewhere look like they do the same job.

Stateless and model-free: it reads the working tree, has the comparer index it in memory and proposes candidate
pairs. Whether a pair really is a duplicate is the judge's question (judging.py), asked only when the verdict
store has no usable answer (store.py). The extractors and the comparer are plugins; the rules here are core.
"""

import fnmatch
import re
from pathlib import Path

from dry_lint.functions import extractor_for, repository_functions
from dry_lint.git import git
from dry_lint.models import Candidate, Function
from dry_lint.plugins import Comparer, Extractor, identity, load
from dry_lint.settings import Settings

SUPPRESSION = re.compile(r"(?:#|//)\s*dry-lint:\s*distinct-from\s+(\S+)")
IGNORE = re.compile(r"(?:#|//)\s*dry-lint:\s*ignore\b")


def default_base(root: Path) -> str:
    """The remote's default branch (origin/HEAD), or origin/main when the clone does not record one."""
    remote_head = git(root, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", check=False)
    return remote_head.removeprefix("refs/remotes/") or "origin/main"


def given(base: str | None) -> bool:
    """A real base: not empty, and not the all-zero sha that a branch's first push reports as its `before`."""
    return bool(base and base.strip("0"))


def base_ref(root: Path, base: str | None) -> str:
    """`base` when one is given, else the default branch."""
    return base if given(base) else default_base(root)


def changed_lines(root: Path, base: str | None = None, staged: bool = False) -> dict[str, set[int]]:
    """Lines added or modified, per file: against `base` (merge base with HEAD), or the staged changes."""
    diff = git(root, "diff", "--cached", "-U0") if staged else git(root, "diff", "-U0", f"{base_ref(root, base)}...HEAD")
    changed: dict[str, set[int]] = {}
    current = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = None if line.endswith("/dev/null") else line[6:]
            if current:
                changed.setdefault(current, set())
        elif line.startswith("@@") and current:
            match = re.search(r"\+(\d+)(?:,(\d+))?", line)
            assert match is not None, line
            start, count = int(match[1]), int(match[2] or 1)
            changed[current] |= set(range(start, start + max(count, 1)))
    return changed


def touched(functions: list[Function], lines: dict[str, set[int]]) -> list[Function]:
    return [f for f in functions if lines.get(f.path, set()) & set(range(f.line, f.end_line + 1))]


def calls(function: Function) -> set[str]:
    """The names the function calls: from its extractor, else from its code after the line that defines it."""
    if function.calls is not None:
        return set(function.calls)
    return set(re.findall(r"\b(\w+)\(", function.code.partition("\n")[2]))


def why_skipped(a: Function, b: Function, settings: Settings) -> str | None:
    """Look-alikes that are never duplicates, by structure, by rule, or by a person's inline decision."""
    if IGNORE.search(a.code) or IGNORE.search(b.code):
        return "inline ignore"
    if a.name.startswith("__") and b.name.startswith("__"):
        return "constructor or dunder pattern"
    if b.name in calls(a) or a.name in calls(b):
        return "one calls the other"
    for pattern in settings.patterns:
        if fnmatch.fnmatch(a.qualname, pattern.members) and fnmatch.fnmatch(b.qualname, pattern.members):
            return f"declared pattern: {pattern.reason}"
    for x, y in ((a, b), (b, a)):
        for target in SUPPRESSION.findall(x.code):
            if y.qualname.endswith(target):
                return "inline distinct-from"
    return None


class Detector:
    def __init__(self, functions: list[Function], settings: Settings, comparer: Comparer,
                 extractors: list[Extractor]) -> None:
        self.functions = functions
        self.settings = settings
        self.comparer = comparer
        self.extractors = extractors
        self.comparer_id = identity(comparer)
        self.file_extractors = {path: extractor_for(path, extractors) for path in {f.path for f in functions}}
        self.position = {f.qualname: i for i, f in enumerate(functions)}
        comparer.index(functions)

    @classmethod
    def for_repository(cls, root: Path, settings: Settings) -> "Detector":
        extractors = [load("extractors", choice) for choice in settings.extractors]
        functions = repository_functions(root, settings.include, settings.exclude, extractors)
        return cls(functions, settings, load("comparers", settings.comparer), extractors)

    def find(self, name: str) -> Function:
        """A function by qualified name, or by a suffix of one that only it has."""
        matches = [f for f in self.functions if f.qualname == name] or \
            [f for f in self.functions if f.qualname.endswith(name)]
        if len(matches) != 1:
            raise ValueError(f"{len(matches)} functions match {name!r}; give more of the qualified name")
        return matches[0]

    def neighbours(self, function: Function) -> list[tuple[Function, float]]:
        """The closest functions in other files, above the comparer's floor, before any rule."""
        extractor = extractor_for(function.path, self.extractors)
        return self.comparer.neighbours(function, self.settings.neighbours,
                                       allowed=lambda o: o.path != function.path and self.file_extractors[o.path] is extractor)

    def hashed(self, function: Function) -> Function:
        extractor = extractor_for(function.path, self.extractors)
        assert extractor is not None, function.path  # it extracted the function
        return function.model_copy(update={"hash": extractor.structure_hash(function)})

    def pair(self, new: Function, existing: Function, similarity: float) -> Candidate:
        return Candidate(new=self.hashed(new), existing=self.hashed(existing), similarity=round(similarity, 3),
                         comparer=self.comparer_id, filtered=why_skipped(new, existing, self.settings),
                         similarity_reusable=getattr(self.comparer, "similarity_reusable", False))

    def candidates(self, changed: list[Function]) -> list[Candidate]:
        """Pairs for the changed functions; those a rule settles carry the rule in `filtered`."""
        found, seen = [], set()
        for function in changed:
            for other, similarity in self.neighbours(function):
                key = frozenset((function.qualname, other.qualname))
                if key not in seen:
                    seen.add(key)
                    found.append(self.pair(function, other, similarity))
        return found

    def scan(self) -> list[Candidate]:
        """Every pair in the repository that are each other's nearest neighbour across files: the backlog."""
        best: dict[str, tuple[str, float]] = {}
        for function in self.functions:
            near = self.neighbours(function)
            if near:
                best[function.qualname] = (near[0][0].qualname, near[0][1])
        pairs = []
        for name, (other, similarity) in best.items():
            if name < other and best.get(other, ("",))[0] == name:
                pair = self.pair(self.functions[self.position[name]], self.functions[self.position[other]], similarity)
                if pair.filtered is None:
                    pairs.append(pair)
        return sorted(pairs, key=lambda c: -c.similarity)
