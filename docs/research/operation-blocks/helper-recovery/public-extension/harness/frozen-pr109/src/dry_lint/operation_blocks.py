"""Bounded Python operation regions, fitted to the complete function-token background.

Regions only retrieve their native parents; they are never candidates or verdict evidence.
The constants are the frozen operation-block experiment's bounds, not tunable policy floors.
"""

import ast
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

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


def _blocks(function: Function) -> list[_Block]:
    python = function.analysis.language == "python" if function.analysis else function.path.endswith(".py")
    if not python or function.declaration is not None or function.line < 1 or function.end_line < function.line:
        return []
    node = _function_node(function.code)
    if node is None:
        return []
    blocks = []
    for kind, statements in _regions(node.body):
        start, end = statements[0].lineno, statements[-1].end_lineno
        assert end is not None  # parsed source, rather than a synthesized AST
        nodes = sum(1 for statement in statements for _ in _behaviour_nodes(statement))
        if not 4 <= end - start + 1 <= 80 or not 20 <= nodes <= 400:
            continue
        wrapper = ast.FunctionDef(
            name="",
            args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
            body=statements,
            decorator_list=[],
        )
        tokens = [token for token in node_tokens(wrapper) if not token.startswith("fn:")]
        operations = frozenset(
            token
            for token in tokens
            if token.partition(":")[0] in {"call", "attr", "key"} and token.partition(":")[2].lower() not in _GENERIC
        )
        calls = frozenset(token for token in operations if token.startswith("call:"))
        if len(set(tokens)) >= 8 and len(calls) >= 2:
            blocks.append(_Block(function.line + start - 1, function.line + end - 1, kind, tokens, operations, calls))
    return sorted(blocks, key=lambda block: (block.line, block.end_line, block.kind))[:_MAX_BLOCKS]


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

    At most 12 regions × 8 anchors × 64 postings select 64 parents. Only the
    complete original function background supplies IDF and anchor frequencies.
    Standalone queries use that same fit, without becoming background documents.
    """

    name = "operation-blocks"
    version = "1"
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
        self._parents = [[self._prepare(block) for block in _blocks(function)] for function in functions]
        postings: dict[str, list[int]] = defaultdict(list)
        for parent, blocks in enumerate(self._parents):
            for block in blocks:
                for anchor in block.anchors:
                    postings[anchor].append(parent)
        self._postings = {token: parents for token, parents in postings.items() if len(parents) <= _MAX_POSTINGS}
        for blocks in self._parents:
            for block in blocks:
                block.retained = frozenset(token for token in block.anchors if token in self._postings)
        self._full_vectors: dict[int, dict[str, float]] = {}

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

    def _query_blocks(self, function: Function) -> list[_Block]:
        position = self._positions.get(id(function))
        if position is not None and _source_key(function) == self._source_keys[position]:
            return self._parents[position]
        blocks = [self._prepare(block) for block in _blocks(function)]
        for block in blocks:
            block.retained = frozenset(token for token in block.anchors if token in self._postings)
        return blocks

    def _pool(self, function: Function, blocks: list[_Block]) -> list[int]:
        mass: dict[int, float] = defaultdict(float)
        for block in blocks:
            for token in block.anchors:
                for parent in self._postings.get(token, ()):
                    if self.functions[parent].qualname != function.qualname:
                        mass[parent] += self.tfidf.idf[token]
        return sorted(mass, key=lambda i: (-mass[i], self.functions[i].qualname, i))[:_MAX_PARENTS]

    @staticmethod
    def _best(left: list[_Block], right: list[_Block]) -> tuple[float, list[str]]:
        best, shared = 0.0, []
        # Both lists are in source order, so equal scores retain the earliest regions.
        for a in left:
            for b in right:
                common = a.operations & b.operations
                if len(common) < 3 or len(a.calls & b.calls) < 2 or not a.retained & b.retained:
                    continue
                score = _cosine(a.vector, b.vector)
                if score > best:
                    best, shared = score, sorted(common)
        return best, shared

    def neighbours(
        self, function: Function, k: int, allowed: Callable[[Function], bool]
    ) -> list[tuple[Function, float]]:
        if k <= 0:
            return []
        blocks = self._query_blocks(function)
        full = self.tfidf.vector(function.tokens)
        ranked = []
        for parent in self._pool(function, blocks):
            other = self.functions[parent]
            if not allowed(other):
                continue
            if parent not in self._full_vectors:
                self._full_vectors[parent] = self.tfidf.vector(other.tokens)
            if _cosine(full, self._full_vectors[parent]) < 0.1:
                continue
            score, _ = self._best(blocks, self._parents[parent])
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

    def similarity(self, a: Function, b: Function) -> float:
        if _cosine(self.tfidf.vector(a.tokens), self.tfidf.vector(b.tokens)) < 0.1:
            return 0.0
        score, _ = self._best(self._query_blocks(a), self._query_blocks(b))
        return score if score >= 0.65 else 0.0

    def shared(self, a: Function, b: Function, limit: int = 12) -> list[str]:
        """Concrete operations in the highest-scoring guarded region pair."""
        if not self.similarity(a, b):
            return []
        return self._best(self._query_blocks(a), self._query_blocks(b))[1][:limit]
