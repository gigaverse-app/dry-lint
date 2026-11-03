"""
The built-in comparer: TF-IDF over behaviour tokens (functions.py), with cosine similarity.

No model and no GPU: on about 10,000 functions it indexes in a fraction of a second and answers a query in about
2 ms. Two functions that solve the same problem share many tokens even when names and structure differ. Tiny
helpers share few tokens, so their real twins score lower and get a lower floor.
"""

from collections.abc import Callable

from dry_lint.index import TfidfIndex
from dry_lint.models import Function


class TfidfComparer:
    name = "tfidf"
    version = "1"

    def __init__(self, min_similarity: float = 0.5, min_similarity_small: float = 0.3, small_function_lines: int = 6,
                 max_df: float = 0.3) -> None:
        self.min_similarity, self.min_similarity_small = min_similarity, min_similarity_small
        self.small_function_lines, self.max_df = small_function_lines, max_df
        self.functions: list[Function] = []
        self.tfidf = TfidfIndex([], max_df)

    def index(self, functions: list[Function]) -> None:
        self.functions = functions
        self.tfidf = TfidfIndex([f.tokens for f in functions], self.max_df)
        self.position = {f.qualname: i for i, f in enumerate(functions)}

    def floor(self, function: Function) -> float:
        return self.min_similarity_small if function.lines < self.small_function_lines else self.min_similarity

    def neighbours(self, function: Function, k: int,
                   allowed: Callable[[Function], bool]) -> list[tuple[Function, float]]:
        own = self.position.get(function.qualname)
        found = []
        for position, similarity in self.tfidf.similar(function.tokens, exclude={own} if own is not None else set()):
            if similarity < self.floor(function) or len(found) == k:
                break
            if allowed(self.functions[position]):
                found.append((self.functions[position], similarity))
        return found

    def similarity(self, a: Function, b: Function) -> float:
        left, right = self.tfidf.vector(a.tokens), self.tfidf.vector(b.tokens)
        return sum(weight * right.get(token, 0.0) for token, weight in left.items())

    def shared(self, a: Function, b: Function, limit: int = 12) -> list[str]:
        """The tokens that contribute most to the pair's similarity, for `dry-lint explain`."""
        left, right = self.tfidf.vector(a.tokens), self.tfidf.vector(b.tokens)
        common = sorted((token for token in left if token in right), key=lambda t: -left[t] * right[t])
        return common[:limit]
