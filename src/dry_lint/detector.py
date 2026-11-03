"""
The detector: which functions changed, and which existing functions elsewhere look like they do the same job.

Stateless and model-free: it reads the working tree, builds the index in memory and proposes candidate pairs.
Whether a pair really is a duplicate is the judge's question (judges/), asked only when the verdict store has
no usable answer (store.py).
"""

import fnmatch
import re
import subprocess
from pathlib import Path

from pydantic import BaseModel

from dry_lint.functions import Function, repository_functions
from dry_lint.settings import Settings
from dry_lint.sources import make_source

SUPPRESSION = re.compile(r"#\s*dry-lint:\s*distinct-from\s+(\S+)")


class Candidate(BaseModel):
    """A changed function and an existing one elsewhere that looks like it does the same job."""

    new: Function
    existing: Function
    similarity: float
    detector: str = "tfidf"


def changed_lines(root: Path, base: str | None = None, staged: bool = False) -> dict[str, set[int]]:
    """Lines added or modified, per file: against `base` (merge base with HEAD), or the staged changes."""
    if staged:
        command = ["git", "diff", "--cached", "-U0", "--", "*.py"]
    else:
        command = ["git", "diff", "-U0", f"{base or 'origin/main'}...HEAD", "--", "*.py"]
    diff = subprocess.run(command, cwd=root, capture_output=True, text=True, check=True).stdout
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
    return set(re.findall(r"\b(\w+)\(", function.code))


def why_skipped(a: Function, b: Function, settings: Settings) -> str | None:
    """Look-alikes that are never duplicates, by structure, by rule, or by a person's inline decision."""
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
    def __init__(self, functions: list[Function], settings: Settings) -> None:
        self.functions = functions
        self.settings = settings
        self.source = make_source(functions, settings)
        self.position = {f.qualname: i for i, f in enumerate(functions)}

    @classmethod
    def for_repository(cls, root: Path, settings: Settings) -> "Detector":
        return cls(repository_functions(root, settings.include, settings.exclude), settings)

    def floor(self, function: Function) -> float:
        if self.settings.detector == "dryer":
            return self.settings.dryer_threshold
        small = function.lines < self.settings.small_function_lines
        return self.settings.min_similarity_small if small else self.settings.min_similarity

    def neighbours(self, function: Function) -> list[tuple[Function, float]]:
        """The closest functions in other files, above the detector floor, before any filtering."""
        found = self.source.similar(function, limit=self.settings.neighbours + 8)
        result = []
        for position, similarity in found:
            other = self.functions[position]
            if other.path == function.path or similarity < self.floor(function):
                continue
            result.append((other, similarity))
            if len(result) == self.settings.neighbours:
                break
        return result

    def candidates(self, changed: list[Function]) -> tuple[list[Candidate], list[str]]:
        """Candidate pairs for the changed functions, and a line per pair skipped with its reason."""
        found, skipped, seen = [], [], set()
        for function in changed:
            for other, similarity in self.neighbours(function):
                pair = frozenset((function.qualname, other.qualname))
                if pair in seen:
                    continue
                seen.add(pair)
                if reason := why_skipped(function, other, self.settings):
                    skipped.append(f"{function.qualname} ~ {other.qualname}: {reason}")
                    continue
                found.append(self._candidate(function, other, similarity))
        return found, skipped

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
                a, b = self.functions[self.position[name]], self.functions[self.position[other]]
                if not why_skipped(a, b, self.settings):
                    pairs.append(self._candidate(a, b, similarity))
        return sorted(pairs, key=lambda c: -c.similarity)

    def _candidate(self, new: Function, existing: Function, similarity: float) -> Candidate:
        return Candidate(new=new, existing=existing, similarity=round(similarity, 3), detector=self.settings.detector)
