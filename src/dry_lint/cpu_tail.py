"""Opt-in complete-statement retrieval and bounded raw reciprocal-rank fusion."""

import hashlib
import json
from collections import Counter

from dry_lint.cpu_embedding import DIMENSIONS, CpuEmbeddingComparer
from dry_lint.operation_blocks import OperationBlocksComparer
from dry_lint.statement_views import StatementViews

TAIL_FLOOR = 0.80
ROUTE_LIMIT = 20
RANK_CONSTANT = 60
MAX_EXTRA = 1


class CompleteStatementComparer(CpuEmbeddingComparer):
    """Reuse the original validated encoder/cache for both full code and view strings."""

    name = "cpu-complete-statements"

    def __init__(self, model_dir, threads=2, cache_dir=None):
        super().__init__(model_dir, min_similarity=TAIL_FLOOR, threads=threads, cache_dir=cache_dir)
        self.recipe = StatementViews(self.encoder)
        self.version = (
            "1-"
            + hashlib.sha256(
                json.dumps(
                    {
                        "prefix": self.version,
                        "views": self.recipe.version,
                        "scoring": "max-prefix-tail-tail-prefix-tail-tail-float32-stable-source-order",
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest()
        )
        self.view_vectors = self.np.empty((0, DIMENSIONS), dtype=self.np.float32)
        self.owners = self.np.empty(0, dtype=self.np.int64)
        self._query = None
        self._scores = None

    def index(self, functions):
        # Keep every document in the competitor corpus; ambiguity affects eligibility only.
        recipes = [self.recipe.views(f)[0] if self._source_known(f) else [] for f in functions]
        codes = [f.code for f in functions] + [v["text"] for rows in recipes for v in rows]
        vectors = self._vectors(codes) if codes else self.np.empty((0, DIMENSIONS), dtype=self.np.float32)
        owners = self.np.asarray([i for i, rows in enumerate(recipes) for _ in rows], dtype=self.np.int64)
        ambiguous = {name for name, n in Counter(f.qualname for f in functions).items() if n > 1}
        # Publish only after all source parsing, cache reads/writes and encodes succeed.
        self.functions = list(functions)
        self.vectors, self.view_vectors = vectors[: len(functions)], vectors[len(functions) :]
        self.owners, self._ambiguous = owners, ambiguous
        self._query = self._scores = None

    def scores(self, function):
        key = (function.code, function.name, function.path.rsplit(".", 1)[-1])
        if key != self._query:
            texts = [v["text"] for v in self.recipe.views(function)[0]]
            query = self._vectors([function.code, *texts])
            scores = self.np.full(len(self.functions), -1.0, dtype=self.np.float32)
            # Prefix-prefix is exclusively owned by the existing CPU route.
            if len(query) > 1:
                scores = self.np.maximum(scores, (self.vectors @ query[1:].T).max(axis=1))
            if len(self.view_vectors):
                values = (self.view_vectors @ query.T).max(axis=1)
                self.np.maximum.at(scores, self.owners, values)
            self._query, self._scores = key, scores
        return self._scores

    def neighbours(self, function, k, allowed):
        if k <= 0 or not self.functions or function.qualname in self._ambiguous or not self._source_known(function):
            return []
        scores = self.scores(function)
        found = []
        for i in self.np.argsort(-scores, kind="stable"):
            other, score = self.functions[i], float(scores[i])
            if score < TAIL_FLOOR:
                break
            if (
                other.qualname != function.qualname
                and other.qualname not in self._ambiguous
                and self._source_known(other)
                and allowed(other)
            ):
                found.append((other, min(1.0, score)))
                if len(found) == k:
                    break
        return found

    def similarity(self, a, b):
        # Standalone source edits are evaluated against current text, never a stale qualname.
        left = self._vectors([a.code, *[v["text"] for v in self.recipe.views(a)[0]]])
        right = self._vectors([b.code, *[v["text"] for v in self.recipe.views(b)[0]]])
        values = []
        if len(left) > 1:
            values.append(float((left[1:] @ right.T).max()))
        if len(right) > 1:
            values.append(float((left[:1] @ right[1:].T).max()))
        return max(0.0, min(1.0, max(values, default=0.0)))


class CpuTailRankFusionComparer:
    """One extra native function from equal top20 blocks/tail RRF, never a cosine.

    similarity(a,b) is directional: rank b in the indexed corpus with all known,
    unambiguous non-self sources eligible. Discovery neighbours instead uses the
    actual core predicate before each route cap; that context may change ranks.
    """

    name = "cpu-tail-rrf"
    discovery_unseen = True
    similarity_reusable = False

    def __init__(self, model_dir, threads=2, cache_dir=None):
        self.tail = CompleteStatementComparer(model_dir, threads=threads, cache_dir=cache_dir)
        self.blocks = OperationBlocksComparer()
        self.functions = []
        self.position = {}
        self.contract = {
            "tail": self.tail.version,
            "encoder": self.tail.encoder.contract,
            "views": StatementViews.version,
            "blocks": "operation-blocks:" + self.blocks.version,
            "route_limit": ROUTE_LIMIT,
            "rrf_k": RANK_CONSTANT,
            "max_extra": MAX_EXTRA,
            "tail_floor": TAIL_FLOOR,
            "ranking": "equal-raw-rrf-absent0-stable-source-order-v1",
        }
        self.version = "1-" + hashlib.sha256(json.dumps(self.contract, sort_keys=True).encode()).hexdigest()

    def index(self, functions):
        # Fresh block state protects the old full index if either route fails.
        blocks = OperationBlocksComparer()
        blocks.index(functions)
        self.tail.index(functions)
        self.blocks = blocks
        self.functions = list(functions)
        self.position = {f.qualname: i for i, f in enumerate(functions)}

    def ranked(self, function, allowed):
        if function.qualname in self.tail._ambiguous or not self.tail._source_known(function):
            return []

        def eligible(other):
            return (
                other.qualname != function.qualname
                and other.qualname not in self.tail._ambiguous
                and self.tail._source_known(other)
                and allowed(other)
            )

        rows, scores = {}, {}
        for comparer in (self.blocks, self.tail):
            for rank, (other, _) in enumerate(comparer.neighbours(function, ROUTE_LIMIT, eligible), 1):
                rows.setdefault(other.qualname, other)
                scores[other.qualname] = scores.get(other.qualname, 0.0) + 1 / (RANK_CONSTANT + rank)
        ordered = sorted(rows, key=lambda name: (-scores[name], self.position[name]))
        return [(rows[name], scores[name]) for name in ordered]

    def neighbours(self, function, k, allowed):
        return self.ranked(function, allowed)[: min(k, MAX_EXTRA)] if k > 0 else []

    def similarity(self, a, b):
        return next(
            (score for f, score in self.ranked(a, lambda _: True) if f.qualname == b.qualname and f.code == b.code), 0.0
        )
