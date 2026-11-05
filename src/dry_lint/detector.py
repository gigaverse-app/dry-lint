"""
The detector: which functions changed, and which existing functions elsewhere look like they do the same job.

Stateless and model-free: it reads the working tree, has the comparer index it in memory and proposes candidate
pairs. Whether a pair really is a duplicate is the judge's question (judging.py), asked only when the verdict
store has no usable answer (store.py). The extractors and the comparer are plugins; the rules here are core.
"""

import fnmatch
import re
from pathlib import Path

from dry_lint.function_index import FunctionIndex, extraction_contract, tree_blobs
from dry_lint.functions import extractor_for, repository_functions, selected_path, validate_source
from dry_lint.git import git
from dry_lint.models import Candidate, Function, Run, module_of
from dry_lint.plugins import Comparer, Extractor, identity, load
from dry_lint.ranking import rank_candidates
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


def changed_lines(
    root: Path, base: str | None = None, staged: bool = False, *, head: str = "HEAD"
) -> dict[str, set[int]]:
    """Lines added or modified, per file: from the merge base of base/head to head, or the staged changes."""
    diff = (
        git(root, "diff", "--cached", "-U0") if staged else git(root, "diff", "-U0", f"{base_ref(root, base)}...{head}")
    )
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


def changed_functions(root: Path, settings: Settings, base: str | None) -> list[Function]:
    """The functions a change touched, as `check` finds them, reading only the changed files."""
    extractors = [load("extractors", choice) for choice in settings.extractors]
    found: list[Function] = []
    for path, lines in changed_lines(root, base).items():
        extractor = extractor_for(path, extractors)
        if extractor is None or not selected_path(path, settings.include, settings.exclude):
            continue
        try:
            found += touched(extractor.functions(path, (root / path).read_text(encoding="utf-8")), {path: lines})
        except (OSError, UnicodeDecodeError):
            continue
    return found


def calls(function: Function) -> set[str]:
    """
    The function's direct calls (`name`, or `self.name`, `cls.name`, `this.name`): from its extractor, else from
    its code after the line that defines it.
    """
    if function.calls is not None:
        return set(function.calls)
    body = function.code.partition("\n")[2]
    return {
        *re.findall(r"(?<![\w.])(\w+)\s*\(", body),
        *(f"{receiver}.{name}" for receiver, name in re.findall(r"\b(self|cls|this)\.(\w+)\s*\(", body)),
    }


def delegates(caller: Function, callee: Function) -> bool:
    """
    Whether `caller` provably calls `callee`: a call through `self`, `cls` or `this` of `callee`'s name, where
    `callee` is a method of the same class in the same file, of a class whose direct base is the caller's (a base
    method calling the subclass's override), or of the caller's class's direct base (a subclass method calling an
    inherited one; if the subclass overrides it again, the call reaches that override, which `overrides` relates to
    `callee` in turn). Names are not resolved to symbols, so nothing else proves it: a bare `normalize(value)` may
    call an imported `normalize` or a parameter of that name, and `value.trim()` calls String.trim. Those pairs go to
    the judge, which reads the code.
    """
    called = calls(caller)
    related = (
        callee.owner == caller.owner
        and callee.path == caller.path
        or inherits_from(callee, caller)
        or inherits_from(caller, callee)
    )
    return (
        callee.owner is not None
        and related
        and any(f"{receiver}.{callee.name}" in called for receiver in ("self", "cls", "this"))
    )


def inherits_from(method: Function, base: Function) -> bool:
    """
    Whether `method`'s class has `base`'s class as a direct base. The extractor resolves bases only from the class's
    own file (a class it defines, or a name its imports bind), so a grandparent, or a base the file cannot name, is
    not a match.
    """
    module = module_of(base.path)
    return base.owner is not None and any(
        name == base.owner and (module == home or module.endswith(f"/{home}"))
        for home, _, name in (reference.rpartition("::") for reference in method.bases)
    )


def overrides(method: Function, base: Function) -> bool:
    """
    Whether `method` overrides `base`: the same name, in a class whose direct base is `base`'s class (see
    `inherits_from`), so an override of a grandparent's method, or of a base the file cannot name, stays with the
    judge. An override is the class hierarchy's own variation point: its likeness to the base method is the contract,
    not a copy.
    """
    return method.name == base.name and inherits_from(method, base)


def why_skipped(a: Function, b: Function, settings: Settings) -> str | None:
    """Look-alikes that are never duplicates, by structure, by rule, or by a person's inline decision."""
    if IGNORE.search(a.code) or IGNORE.search(b.code):
        return "inline ignore"
    if a.name.startswith("__") and b.name.startswith("__"):
        return "constructor or dunder pattern"
    if a.origin == b.origin and (delegates(a, b) or delegates(b, a)):
        return "one calls the other"
    if a.origin == b.origin and (overrides(a, b) or overrides(b, a)):
        return "subclass override"
    for pattern in settings.patterns:
        if fnmatch.fnmatch(a.qualname, pattern.members) and fnmatch.fnmatch(b.qualname, pattern.members):
            return f"declared pattern: {pattern.reason}"
    for x, y in ((a, b), (b, a)):
        for target in SUPPRESSION.findall(x.code):
            if y.qualname.endswith(target):
                return "inline distinct-from"
    return None


class Detector:
    def __init__(
        self,
        functions: list[Function],
        settings: Settings,
        comparer: Comparer,
        extractors: list[Extractor],
        *,
        cross_repository: bool = False,
        same_file: bool = False,
    ) -> None:
        self.functions = functions
        self.settings = settings
        self.comparer = comparer
        self.extractors = extractors
        self.cross_repository = cross_repository
        self.same_file = same_file
        self.repositories = sorted({f.origin.repository for f in functions if f.origin})
        self.comparer_id = identity(comparer)
        self.file_extractors = {path: extractor_for(path, extractors) for path in {f.path for f in functions}}
        self.position = {f.qualname: i for i, f in enumerate(functions)}
        comparer.index(functions)

    @classmethod
    def for_repository(cls, root: Path, settings: Settings, *, strict: bool = False) -> "Detector":
        extractors = [load("extractors", choice) for choice in settings.extractors]
        functions = repository_functions(root, settings.include, settings.exclude, extractors, strict=strict)
        return cls(functions, settings, load("comparers", settings.comparer), extractors)

    @classmethod
    def for_tree(cls, root: Path, revision: str, settings: Settings, *, strict: bool = False) -> "Detector":
        extractors = [load("extractors", choice) for choice in settings.extractors]
        functions = []
        for path, source in tree_blobs(root, revision, settings).items():
            extractor = extractor_for(path, extractors)
            if extractor and selected_path(path, settings.include, settings.exclude):
                text = source.decode("utf-8")
                if strict:
                    validate_source(extractor, path, text)
                functions.extend(extractor.functions(path, text))
        return cls(functions, settings, load("comparers", settings.comparer), extractors)

    @classmethod
    def for_workspace(cls, roots: dict[str, Path], settings: Settings, indexes: list[FunctionIndex] = ()) -> "Detector":
        """One index of committed checkouts; only neighbours in another repository are proposed."""
        if len(roots) + len(indexes) < 2:
            raise ValueError("A workspace needs at least two repositories")
        extractors = [load("extractors", choice) for choice in settings.extractors]
        functions: list[Function] = []
        seen: set[Path] = set()
        for name, path in roots.items():
            if not re.fullmatch(r"[\w-][\w.-]*/[\w-][\w.-]*", name):
                raise ValueError(f"Invalid repository name: {name!r}; use OWNER/NAME")
            root = Path(git(path, "rev-parse", "--show-toplevel")).resolve()
            if root in seen:
                raise ValueError(f"Duplicate workspace checkout: {root}")
            seen.add(root)
            if git(root, "status", "--porcelain", "--untracked-files=no"):
                raise ValueError(f"Commit tracked changes before scanning workspace repository {name}")
            origin = Run(repository=name, head=git(root, "rev-parse", "HEAD"))
            source = Settings.load(root)
            functions.extend(
                f.model_copy(update={"origin": origin})
                for f in repository_functions(root, source.include, source.exclude, extractors)
            )
        names = set(roots)
        for index in indexes:
            if index.repository in names:
                raise ValueError(f"Duplicate repository: {index.repository}")
            names.add(index.repository)
            if index.contract != extraction_contract(settings):
                raise ValueError(f"Function index contract mismatch for {index.repository}")
            functions.extend(index.extracted())
        return cls(functions, settings, load("comparers", settings.comparer), extractors, cross_repository=True)

    def find(self, name: str) -> Function:
        """A function by qualified name, or by a suffix of one that only it has."""
        matches = [f for f in self.functions if f.qualname == name] or [
            f for f in self.functions if f.qualname.endswith(name)
        ]
        if len(matches) != 1:
            raise ValueError(f"{len(matches)} functions match {name!r}; give more of the qualified name")
        return matches[0]

    def neighbours(self, function: Function) -> list[tuple[Function, float]]:
        """The closest functions in other files, above the comparer's floor, before any rule."""
        extractor = extractor_for(function.path, self.extractors)

        def allowed(other: Function) -> bool:
            different_repository = other.origin != function.origin
            return (
                different_repository
                if self.cross_repository
                else different_repository
                or other.path != function.path
                or (self.same_file or function.declaration is not None and other.declaration is not None)
                and other.qualname != function.qualname
            ) and self.file_extractors[other.path] is extractor

        if self.cross_repository:
            return [
                pair
                for repository in self.repositories
                if not function.origin or repository != function.origin.repository
                for pair in self.comparer.neighbours(
                    function,
                    self.settings.neighbours,
                    allowed=lambda other, repository=repository: (
                        allowed(other) and other.origin is not None and other.origin.repository == repository
                    ),
                )
            ]
        return self.comparer.neighbours(function, self.settings.neighbours, allowed=allowed)

    def hashed(self, function: Function) -> Function:
        extractor = extractor_for(function.path, self.extractors)
        assert extractor is not None, function.path  # it extracted the function
        return function.model_copy(update={"hash": extractor.structure_hash(function)})

    def pair(self, new: Function, existing: Function, similarity: float) -> Candidate:
        targets = [
            target
            for target in self.settings.consolidation
            if all(
                any(fnmatch.fnmatch(f.qualname.split("::")[0], pattern) for pattern in target.sources)
                for f in (new, existing)
            )
        ]
        return Candidate(
            new=self.hashed(new),
            existing=self.hashed(existing),
            similarity=round(similarity, 3),
            comparer=self.comparer_id,
            filtered=why_skipped(new, existing, self.settings),
            similarity_reusable=getattr(self.comparer, "similarity_reusable", False),
            consolidation=targets,
        )

    def candidates(self, changed: list[Function]) -> list[Candidate]:
        """Pairs for the changed functions; those a rule settles carry the rule in `filtered`."""
        found, seen = [], set()
        for function in changed:
            for other, similarity in self.neighbours(function):
                key = frozenset((function.qualname, other.qualname))
                if key not in seen:
                    seen.add(key)
                    found.append(self.pair(function, other, similarity))
        baseline = rank_candidates(found) if self.cross_repository or self.settings.consolidation else found
        if self.settings.discovery.enabled and self.settings.comparer.use == "tfidf":
            # A separate index leaves the baseline's floor, ranks and k unchanged.
            from dry_lint.comparers import TfidfComparer

            policy = self.settings.discovery
            options = self.settings.comparer.options()
            options.update(min_similarity=policy.min_similarity, min_similarity_small=policy.min_similarity)
            wider = self.settings.model_copy(
                update={"neighbours": policy.depth, "discovery": policy.model_copy(update={"enabled": False})}
            )
            detector = Detector(
                self.functions,
                wider,
                TfidfComparer(**options),
                self.extractors,
                cross_repository=self.cross_repository,
                same_file=True,
            )
            keys = {c.key for c in baseline}
            baseline += [
                c.model_copy(update={"lane": "exploration"}) for c in detector.candidates(changed) if c.key not in keys
            ]
        if not self.cross_repository:
            baseline += self.relatives(changed, baseline)
        return baseline

    def relatives(self, changed: list[Function], primaries: list[Candidate]) -> list[Candidate]:
        """
        The existing side's own look-alikes, one hop away: fixing a duplicate touches the existing function, and
        without these its other copies surface one push at a time. Each names its `parent` pair; the judge asks
        about it only once that pair is reported, and it never blocks (judging.py, report.py).
        """
        touched = {f.qualname for f in changed}
        seen = {c.key for c in primaries}
        found = []
        for parent in primaries:
            existing = parent.existing
            if parent.filtered or parent.lane != "baseline" or existing.qualname in touched:
                continue  # a changed function's look-alikes are proposed already
            for other, similarity in self.neighbours(existing):
                relative = self.pair(existing, other, similarity)
                if relative.key in seen or relative.filtered or other.qualname in touched:
                    continue
                seen.add(relative.key)
                found.append(relative.model_copy(update={"lane": "relative", "parent": parent.key}))
        return found

    def scan(self) -> list[Candidate]:
        """Every pair in the repository that are each other's nearest neighbour across files: the backlog."""
        if self.cross_repository:
            best = {}
            for function in self.functions:
                for other, similarity in self.neighbours(function):
                    key = (function.qualname, other.origin.repository)
                    if key not in best:
                        best[key] = (other, similarity)
            pairs = []
            for (name, _), (other, similarity) in best.items():
                if name >= other.qualname:
                    continue
                function = self.functions[self.position[name]]
                reverse = best.get((other.qualname, function.origin.repository))
                if reverse and reverse[0].qualname == name:
                    pair = self.pair(function, other, similarity)
                    if pair.filtered is None:
                        pairs.append(pair)
            return rank_candidates(pairs)
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
        return rank_candidates(pairs) if self.settings.consolidation else sorted(pairs, key=lambda c: -c.similarity)
