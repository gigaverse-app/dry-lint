"""Bounded Python operation regions, fitted to the complete function-token background.

Regions only retrieve their native parents; they are never candidates or verdict evidence.
The constants are the frozen operation-block experiment's bounds, not tunable policy floors.
"""

import ast
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from itertools import islice

from dry_lint.functions import _behaviour_nodes, _function_node, node_tokens
from dry_lint.index import TfidfIndex
from dry_lint.models import Function

_GENERIC = frozenset(
    "get set append extend items values keys len str int float bool dict list tuple "
    "isinstance getattr setattr hasattr cast enumerate range zip sorted reversed min max sum "
    "any all print super object type exception valueerror typeerror runtimeerror "
    "info debug warning error exception critical log assert mock magicmock asyncmock "
    "raises fail patch sleep time utcnow now".split()
)
_COMPOUND = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.TryStar, ast.With, ast.AsyncWith, ast.Match)
_NESTED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_MAX_BLOCKS = 12
_MAX_ANCHORS = 8
_MAX_POSTINGS = 64
_MAX_PARENTS = 64


@dataclass
class _Block:
    line: int
    end_line: int
    kind: str
    tokens: list[str]
    operations: frozenset[str]
    calls: frozenset[str]
    vector: dict[str, float] = field(default_factory=dict)
    anchors: tuple[str, ...] = ()
    retained: frozenset[str] = frozenset()


def _regions(body: list[ast.stmt], depth: int = 0) -> Iterator[tuple[str, list[ast.stmt]]]:
    """Whole compounds and maximal straight runs; never slide or truncate a region."""
    run: list[ast.stmt] = []
    for statement in body:
        boundary = isinstance(statement, (*_NESTED, *_COMPOUND)) or (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        )
        if boundary:
            if len(run) >= 2:
                yield "straight_run", run
            run = []
            if isinstance(statement, _COMPOUND):
                if not any(isinstance(node, _NESTED) for node in ast.walk(statement)):
                    yield type(statement).__name__, [statement]
                if depth < 3:
                    for attr in ("body", "orelse", "finalbody"):
                        yield from _regions(getattr(statement, attr, []), depth + 1)
                    for handler in getattr(statement, "handlers", []):
                        yield from _regions(handler.body, depth + 1)
                    for case in getattr(statement, "cases", []):
                        yield from _regions(case.body, depth + 1)
        else:
            run.append(statement)
    if len(run) >= 2:
        yield "straight_run", run


class _Preparation:
    """Statement work shared only within one function's region construction.

    node_tokens visits each top-level statement independently, in body order.
    Concatenating those exact lists preserves token and floating-point sum order;
    concatenating tokens from nested subtrees would not preserve its breadth-first
    traversal. No AST or per-statement cache survives _representations.
    """

    def __init__(self) -> None:
        self.counts: dict[ast.stmt, int] = {}
        self.tokens: dict[ast.stmt, list[str]] = {}

    def count(self, statement: ast.stmt) -> int:
        if statement not in self.counts:
            # Only the <=400 predicate matters, never the exact oversized count.
            self.counts[statement] = sum(1 for _ in islice(_behaviour_nodes(statement), 401))
        return self.counts[statement]

    def statement_tokens(self, statement: ast.stmt) -> list[str]:
        if statement not in self.tokens:
            wrapper = ast.FunctionDef(
                name="",
                args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
                body=[statement],
                decorator_list=[],
            )
            self.tokens[statement] = [token for token in node_tokens(wrapper) if not token.startswith("fn:")]
        return self.tokens[statement]


def _block(
    function: Function, kind: str, statements: list[ast.stmt], preparation: _Preparation | None = None
) -> _Block | None:
    if not statements:
        return None
    start, end = statements[0].lineno, statements[-1].end_lineno
    assert end is not None  # parsed source, rather than a synthesized AST
    # Reject by source span before walking possibly very large syntax trees.
    if not 4 <= end - start + 1 <= 80:
        return None
    preparation = preparation if preparation is not None else _Preparation()
    nodes = sum(preparation.count(statement) for statement in statements)
    if not 20 <= nodes <= 400:
        return None
    tokens = [token for statement in statements for token in preparation.statement_tokens(statement)]
    operations = frozenset(
        token
        for token in tokens
        if token.partition(":")[0] in {"call", "attr", "key"} and token.partition(":")[2].lower() not in _GENERIC
    )
    calls = frozenset(token for token in operations if token.startswith("call:"))
    if len(set(tokens)) < 8 or len(calls) < 2:
        return None
    return _Block(function.line + start - 1, function.line + end - 1, kind, tokens, operations, calls)


def _representations(function: Function) -> tuple[list[_Block], _Block | None]:
    """The original first 12 complete regions and at most one complete helper body."""
    python = function.analysis.language == "python" if function.analysis else function.path.endswith(".py")
    if not python or function.declaration is not None or function.line < 1 or function.end_line < function.line:
        return [], None
    node = _function_node(function.code)
    if node is None:
        return [], None
    preparation = _Preparation()
    blocks = [
        block
        for kind, statements in _regions(node.body)
        if (block := _block(function, kind, statements, preparation)) is not None
    ]
    original = sorted(blocks, key=lambda block: (block.line, block.end_line, block.kind))[:_MAX_BLOCKS]
    body = node.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    helper = None
    if body:
        start, end = body[0].lineno, body[-1].end_lineno
        assert end is not None
        # A duplicate or out-of-span helper cannot survive the original rules;
        # avoid its second node walk and tokenization without changing any region.
        duplicate = any(
            (block.line, block.end_line) == (function.line + start - 1, function.line + end - 1) for block in original
        )
        if (
            not duplicate
            and 4 <= end - start + 1 <= 80
            and not any(isinstance(nested, _NESTED) for statement in body for nested in ast.walk(statement))
        ):
            helper = _block(function, "whole_helper", body, preparation)
    return original, helper


def _blocks(function: Function) -> list[_Block]:
    """Original region vocabulary; useful for inspecting the protected first route."""
    return _representations(function)[0]


def _postings(parents: list[list[_Block]]) -> dict[str, list[int]]:
    postings: dict[str, list[int]] = defaultdict(list)
    for parent, blocks in enumerate(parents):
        for block in blocks:
            for anchor in block.anchors:
                postings[anchor].append(parent)
    kept = {token: indexes for token, indexes in postings.items() if len(indexes) <= _MAX_POSTINGS}
    for blocks in parents:
        for block in blocks:
            block.retained = frozenset(token for token in block.anchors if token in kept)
    return kept


def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
    return sum(weight * right.get(token, 0.0) for token, weight in left.items())


def _source_key(function: Function) -> tuple:
    return (
        function.code,
        function.line,
        function.end_line,
        function.analysis.language if function.analysis else function.path.endswith(".py"),
        function.declaration is not None,
    )


class OperationBlocksComparer:
    """Opt-in retrieval, not a duplication decision; scores are region cosines.

    The protected first route keeps its 12 regions × 8 anchors × 64 postings,
    selecting at most 64 parents. Only when it has no allowed winner, a second
    route adds one complete helper body per function: at most 13 regions,
    6,656 posting visits and 64 × 13 × 13 region comparisons. No score floor,
    original winner or original winner's score changes. Regions retrieve native
    functions; they never replace candidate source or erase error/cleanup scopes.

    Both routes share the complete function-token IDF and anchor frequencies.
    Standalone queries use that same fit, without becoming background documents.
    """

    name = "operation-blocks"
    version = "2"
    similarity_reusable = False
    # Discovery asks for k unseen, unsettled pairs after preceding routes. Other
    # comparers keep their existing raw-neighbour caps and first-route ownership.
    discovery_unseen = True

    def __init__(self) -> None:
        self.index([])

    def index(self, functions: list[Function]) -> None:
        self.functions = list(functions)
        self.tfidf = TfidfIndex([function.tokens for function in functions])
        self._frequency = Counter(token for function in functions for token in set(function.tokens))
        self._anchor_df = min(128, max(2, int(0.01 * len(functions))))
        self._positions = {id(function): i for i, function in enumerate(functions)}
        self._source_keys = [_source_key(function) for function in functions]
        representations = [_representations(function) for function in functions]
        self._parents = [[self._prepare(block) for block in blocks] for blocks, _ in representations]
        self._postings = _postings(self._parents)
        # Independent retained-anchor state protects the first route from extra postings.
        self._fallback_parents = [
            [*(replace(block) for block in blocks), *([self._prepare(helper)] if helper else [])]
            for blocks, (_, helper) in zip(self._parents, representations, strict=True)
        ]
        self._fallback_postings = _postings(self._fallback_parents)
        self._full_vectors: dict[int, dict[str, float]] = {}
        # One standalone source, independent of object identity and discarded on
        # reindex. Never retain a query AST or an unbounded history of source edits.
        self._query_key: tuple | None = None
        self._query_original: list[_Block] = []
        self._query_fallback: list[_Block] = []

    def _prepare(self, block: _Block) -> _Block:
        block.vector = self.tfidf.vector(block.tokens)
        block.anchors = tuple(
            sorted(
                (
                    token
                    for token in block.operations
                    if token in self.tfidf.idf and self._frequency[token] <= self._anchor_df
                ),
                key=lambda token: (self._frequency[token], token),
            )[:_MAX_ANCHORS]
        )
        return block

    def _query_blocks(self, function: Function, *, fallback: bool = False) -> list[_Block]:
        position = self._positions.get(id(function))
        if position is not None and _source_key(function) == self._source_keys[position]:
            return (self._fallback_parents if fallback else self._parents)[position]
        key = _source_key(function)
        if key != self._query_key:
            original, helper = _representations(function)
            blocks = [self._prepare(block) for block in original]
            extended = [*(replace(block) for block in blocks), *([self._prepare(helper)] if helper else [])]
            # Retained anchors are route-specific even though immutable preparation
            # is shared. Extra helper postings must never alter the first route.
            for route, postings in ((blocks, self._postings), (extended, self._fallback_postings)):
                for block in route:
                    block.retained = frozenset(token for token in block.anchors if token in postings)
            self._query_key, self._query_original, self._query_fallback = key, blocks, extended
        return self._query_fallback if fallback else self._query_original

    def _pool(self, function: Function, blocks: list[_Block], *, fallback: bool = False) -> list[int]:
        mass: dict[int, float] = defaultdict(float)
        postings = self._fallback_postings if fallback else self._postings
        for block in blocks:
            for token in block.anchors:
                for parent in postings.get(token, ()):
                    if self.functions[parent].qualname != function.qualname:
                        mass[parent] += self.tfidf.idf[token]
        return sorted(mass, key=lambda i: (-mass[i], self.functions[i].qualname, i))[:_MAX_PARENTS]

    @staticmethod
    def _best(left: list[_Block], right: list[_Block]) -> tuple[float, list[str]]:
        best, shared = 0.0, frozenset()
        # Both lists are in source order, so equal scores retain the earliest regions.
        for a in left:
            for b in right:
                # Most region pairs have no retained anchor in common. Check
                # that necessary guard before allocating the larger intersections.
                if not a.retained & b.retained or len(a.calls & b.calls) < 2:
                    continue
                common = a.operations & b.operations
                if len(common) < 3:
                    continue
                score = _cosine(a.vector, b.vector)
                if score > best:
                    best, shared = score, common
        return best, sorted(shared)

    def neighbours(
        self, function: Function, k: int, allowed: Callable[[Function], bool]
    ) -> list[tuple[Function, float]]:
        if k <= 0:
            return []
        original = self._neighbours(function, k, allowed, fallback=False)
        return original or self._neighbours(function, k, allowed, fallback=True)

    def _neighbours(
        self, function: Function, k: int, allowed: Callable[[Function], bool], *, fallback: bool
    ) -> list[tuple[Function, float]]:
        blocks = self._query_blocks(function, fallback=fallback)
        parents = self._fallback_parents if fallback else self._parents
        full = self.tfidf.vector(function.tokens)
        ranked = []
        for parent in self._pool(function, blocks, fallback=fallback):
            other = self.functions[parent]
            if not allowed(other):
                continue
            if parent not in self._full_vectors:
                self._full_vectors[parent] = self.tfidf.vector(other.tokens)
            if _cosine(full, self._full_vectors[parent]) < 0.1:
                continue
            score, _ = self._best(blocks, parents[parent])
            if score >= 0.65:
                ranked.append((parent, score))
        ranked.sort(key=lambda pair: (-pair[1], self.functions[pair[0]].qualname, pair[0]))
        found, seen = [], set()
        for parent, score in ranked:
            other = self.functions[parent]
            if other.qualname not in seen:
                seen.add(other.qualname)
                found.append((other, score))
                if len(found) == k:
                    break
        return found

    def _pair_evidence(self, a: Function, b: Function) -> tuple[float, list[str]]:
        if _cosine(self.tfidf.vector(a.tokens), self.tfidf.vector(b.tokens)) < 0.1:
            return 0.0, []
        # Retain original pair evidence whenever it qualifies; otherwise inspect
        # the extra complete-body representation with the same guards and floor.
        for fallback in (False, True):
            score, shared = self._best(
                self._query_blocks(a, fallback=fallback), self._query_blocks(b, fallback=fallback)
            )
            if score >= 0.65:
                return score, shared
        return 0.0, []

    def similarity(self, a: Function, b: Function) -> float:
        return self._pair_evidence(a, b)[0]

    def shared(self, a: Function, b: Function, limit: int = 12) -> list[str]:
        """Concrete operations in the first qualifying guarded representation."""
        return self._pair_evidence(a, b)[1][:limit]
