# ruff: noqa: E401, E402, E741, F401, F403, F405, I001, B007
# Frozen experiment adapters intentionally preserve import order and shared wildcard exports.
from common import *
from collections import Counter


class OperationIndex:
    name = "cpu-complete-statements"
    version = "2-append"
    similarity_reusable = False
    discovery_unseen = True

    def __init__(self, fs, prefix, views, owners):
        self.functions = fs
        self.prefix = prefix
        self.views = views
        self.owners = owners
        self.position = {f.qualname: i for i, f in enumerate(fs)}
        self.ambiguous = {k for k, v in Counter(f.qualname for f in fs).items() if v > 1}
        self.cached_query = None
        self.cached_scores = None

    def index(self, fs):
        assert fs is self.functions

    def scores(self, f):
        i = self.position[f.qualname]
        if self.cached_query == i:
            return self.cached_scores
        # Only operation-bearing comparisons: prefix-prefix belongs to original route.
        scores = np.full(len(self.functions), -1.0, dtype=np.float32)
        own = self.views[self.owners == i]
        if len(own):
            scores = np.maximum(scores, (self.prefix @ own.T).max(axis=1))
        if len(self.views):
            queries = np.vstack([self.prefix[i : i + 1], own])
            v = (self.views @ queries.T).max(axis=1)
            np.maximum.at(scores, self.owners, v)
        self.cached_query = i
        self.cached_scores = scores
        return scores

    def neighbours(self, f, k, allowed):
        if k <= 0 or f.qualname in self.ambiguous or f.line < 1:
            return []
        result = []
        for j in np.argsort(-self.scores(f), kind="stable"):
            g = self.functions[j]
            score = float(self.cached_scores[j])
            if score < 0.8:
                break
            if g.qualname != f.qualname and g.qualname not in self.ambiguous and g.line >= 1 and allowed(g):
                result.append((g, min(1.0, score)))
                if len(result) == k:
                    break
        return result

    def similarity(self, a, b):
        return max(0.0, min(1.0, float(self.scores(a)[self.position[b.qualname]])))
