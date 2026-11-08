"""
The detector: which functions changed, and which existing functions elsewhere look like they do the same job.

Stateless and model-free: it reads the working tree, has the comparer index it in memory and proposes candidate
pairs. Whether a pair really is a duplicate is the judge's question (judging.py), asked only when the verdict
store has no usable answer (store.py). The extractors and the comparer are plugins; the rules here are core.
"""

import fnmatch
import re
from pathlib import Path

from dry_lint.comparer_resources import ComparerResources
from dry_lint.function_index import FunctionIndex, extraction_contract, tree_blobs
from dry_lint.functions import extractor_for, repository_functions, selected_path, validate_source
from dry_lint.git import git
from dry_lint.models import Candidate, Function, Run, pair_key, qualified
from dry_lint.plugins import Comparer, Extractor, identity, load
from dry_lint.ranking import rank_candidates
from dry_lint.settings import ExplorationComparer, Settings

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


def call_relation(caller: Function, callee: Function) -> str | None:
    """
    How `caller` provably calls `callee`, from adapter-resolved facts only; call names alone are not evidence.
    A whole-body forward is a "forwarding wrapper"; any other file-local direct call is "one calls the other".
    """
    if not caller.analysis:
        return None
    target = f"{callee.path}::{qualified(callee.owner, callee.name)}"
    if caller.analysis.forward_target == target:
        return "forwarding wrapper"
    if target in caller.analysis.local_calls:
        return "one calls the other"
    return None


def why_skipped(a: Function, b: Function, settings: Settings, *, calls: bool = True) -> str | None:
    """Look-alikes that are never duplicates, by structure, by rule, or by a person's inline decision.

    `calls=False` keeps every rule except the caller/callee relation, which says two WHOLE functions are not one
    duplicate. An operation repeated inside both a caller and its callee is still repeated, so operation families
    ask with `calls=False`.
    """
    if IGNORE.search(a.code) or IGNORE.search(b.code):
        return "inline ignore"
    # INVARIANT: language syntax is interpreted by the adapter, never guessed from source or file suffix here.
    if (
        a.analysis
        and b.analysis
        and a.analysis.language == b.analysis.language
        and a.analysis.convention
        and a.analysis.convention == b.analysis.convention
    ):
        return f"language convention: {a.analysis.convention}"
    # INVARIANT: one shared rule for every route. `pair()` records it as `filtered`, and discovery routes that
    # exclude settled pairs (`discovery_unseen`) never spend their slot on it; no comparer re-implements it.
    if calls and a.origin == b.origin and (relation := call_relation(a, b) or call_relation(b, a)):
        return relation
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
        discovery_keys: set[str] | None = None,
        resources: ComparerResources | None = None,
    ) -> None:
        self.functions = functions
        self.settings = settings
        self.comparer = comparer
        self.extractors = extractors
        self.cross_repository = cross_repository
        self.same_file = same_file
        self.discovery_keys = discovery_keys
        self.repositories = sorted({f.origin.repository for f in functions if f.origin})
        self.comparer_id = identity(comparer)
        self.file_extractors = {path: extractor_for(path, extractors) for path in {f.path for f in functions}}
        self.position = {f.qualname: i for i, f in enumerate(functions)}
        if resources is None:
            comparer.index(functions)
        else:
            resources.index(comparer, functions)

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
            if self.discovery_keys is not None and (
                pair_key(function.qualname, other.qualname) in self.discovery_keys
                or why_skipped(function, other, self.settings)
                or any(
                    policy.action == "discard" and policy.apply(function, other) is not None
                    for policy in self.settings.policies
                )
            ):
                return False
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

    def pair(self, new: Function, existing: Function, similarity: float, *, calls: bool = True) -> Candidate:
        targets = [
            target
            for target in self.settings.consolidation
            if all(
                any(fnmatch.fnmatch(f.qualname.split("::")[0], pattern) for pattern in target.sources)
                for f in (new, existing)
            )
        ]
        policies = [applied for policy in self.settings.policies if (applied := policy.apply(new, existing))]
        discarded = next((p for p in policies if p.action == "discard"), None)
        return Candidate(
            new=self.hashed(new),
            existing=self.hashed(existing),
            similarity=round(similarity, 3),
            comparer=self.comparer_id,
            filtered=why_skipped(new, existing, self.settings, calls=calls)
            or (f"adopter policy {discarded.name}: {discarded.reason}" if discarded else None),
            similarity_reusable=getattr(self.comparer, "similarity_reusable", False),
            consolidation=targets,
            policies=policies,
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
        baseline = (
            rank_candidates(found)
            if self.cross_repository or self.settings.consolidation or self.settings.policies
            else found
        )
        policy = self.settings.discovery
        choices = policy.comparers
        if not choices and self.settings.comparer.use == "tfidf":
            options = self.settings.comparer.options()
            options.update(min_similarity=policy.min_similarity, min_similarity_small=policy.min_similarity)
            choices = [ExplorationComparer(use="tfidf", **options)]
        keys = {c.key for c in baseline}
        resources = ComparerResources()
        for phase_choices, residual in ((choices, False), (policy.residual_comparers, True)):
            for choice in phase_choices if policy.enabled else []:
                # Independent indexes cannot displace baseline neighbours or consume their protected budget.
                wider = self.settings.model_copy(
                    update={
                        "neighbours": choice.neighbours or policy.depth,
                        "comparer": choice,
                        "discovery": policy.model_copy(update={"enabled": False}),
                    }
                )
                comparer = resources.load(choice)
                detector = Detector(
                    self.functions,
                    wider,
                    comparer,
                    self.extractors,
                    cross_repository=self.cross_repository,
                    same_file=True,
                    discovery_keys=keys if getattr(comparer, "discovery_unseen", False) else None,
                    resources=resources,
                )
                for candidate in detector.candidates(changed):
                    if candidate.lane == "baseline" and candidate.key not in keys:
                        keys.add(candidate.key)
                        baseline.append(candidate.model_copy(update={"lane": "exploration", "residual": residual}))
            if not residual and not self.cross_repository:
                # Complete the original artifact before appending recovery, including advisory relatives.
                baseline += self.relatives(changed, baseline)
                keys.update(c.key for c in baseline)
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
