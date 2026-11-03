"""Offline channel trial: reserved candidate slots, hub correction and plural folding. Not a production plugin.

Each channel is an ordinary comparer under a `trial-*` identity, so its similarities can never enter a verdict cache
as production `tfidf:2` scores. The trial runner merges channels; nothing here changes the detector.
"""

from collections.abc import Callable

import numpy as np

from dry_lint.comparers import TfidfComparer
from dry_lint.detector import Detector, why_skipped
from dry_lint.index import TfidfIndex
from dry_lint.models import Function

WORD_FAMILIES = ("w:", "fn:")
BEHAVIOUR_FAMILIES = ("call:", "attr:", "key:", "ctl:")


def singular(word: str) -> str:
    """A conservative English singular: regular plurals only, leaving words that merely end in s alone."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("sses", "xes", "ches", "shes", "zes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is", "ous")):
        return word[:-1]
    return word


def fold_plurals(tokens: list[str]) -> list[str]:
    """Identifier words in their singular form; calls, attributes and keys keep their exact identity."""
    folded = []
    for token in tokens:
        family, _, word = token.partition(":")
        folded.append(f"{family}:{singular(word)}" if f"{family}:" in WORD_FAMILIES else token)
    return folded


def behaviour_only(tokens: list[str]) -> list[str]:
    """What the function does, without the words it is written in."""
    return [token for token in tokens if token.startswith(BEHAVIOUR_FAMILIES)]


def experimental(comparer: TfidfComparer, name: str) -> TfidfComparer:
    comparer.name, comparer.version, comparer.similarity_reusable = f"trial-{name}-tfidf", "1", False
    return comparer


class CslsComparer:
    """
    TF-IDF neighbours re-ranked by cross-domain similarity local scaling: 2 cos(a, b) - r(a) - r(b), where r is a
    function's mean similarity to its `pool` nearest functions in other files. Members of a dense family (one
    serializer per resource) have a high r, so a pair that stands out from both neighbourhoods wins the slot.
    The floor and reported similarity stay raw cosine; only the order changes.
    """

    similarity_reusable = False

    def __init__(self, inner: TfidfComparer, pool: int = 10) -> None:
        self.inner, self.pool = inner, pool
        self.name, self.version = f"trial-csls-{inner.name}", "1"
        self.radii: dict[str, float] = {}

    def index(self, functions: list[Function]) -> None:
        self.inner.index(functions)
        self.radii = {}

    def radius(self, function: Function) -> float:
        if function.qualname not in self.radii:
            own = self.inner.position.get(function.qualname)
            ranked = self.inner.tfidf.similar(function.tokens, exclude={own} if own is not None else set())
            near = [score for position, score in ranked if self.inner.functions[position].path != function.path][: self.pool]
            self.radii[function.qualname] = sum(near) / len(near) if near else 0.0
        return self.radii[function.qualname]

    def neighbours(self, function: Function, k: int,
                   allowed: Callable[[Function], bool]) -> list[tuple[Function, float]]:
        near = self.inner.neighbours(function, max(k, self.pool), allowed)
        return sorted(near, key=lambda pair: self.radius(pair[0]) - 2 * pair[1])[:k]

    def similarity(self, a: Function, b: Function) -> float:
        return self.inner.similarity(a, b)


class Floored:
    """A comparer with one floor of its own, for channels whose similarity scale differs from production TF-IDF."""

    similarity_reusable = False

    def __init__(self, inner, floor: float = float("-inf")) -> None:
        self.inner, self.floor = inner, floor
        self.name, self.version = inner.name, inner.version

    def index(self, functions: list[Function]) -> None:
        self.inner.index(functions)

    def neighbours(self, function: Function, k: int,
                   allowed: Callable[[Function], bool]) -> list[tuple[Function, float]]:
        return [(other, score) for other, score in self.inner.neighbours(function, k, allowed) if score >= self.floor]

    def similarity(self, a: Function, b: Function) -> float:
        return self.inner.similarity(a, b)


class LsiComparer:
    """
    Latent semantic indexing: a rank-`rank` truncated SVD of the TF-IDF matrix, by randomized range finding, and
    cosine nearest neighbours in that space. It learns which tokens this repository uses together, so functions
    can be close without sharing a token. It has no floor; wrap it in `Floored`.
    """

    name, version, similarity_reusable = "trial-lsi", "1", False

    def __init__(self, rank: int = 128, max_df: float = 0.3, seed: int = 0, power: int = 2) -> None:
        self.rank, self.max_df, self.seed, self.power = rank, max_df, seed, power
        self.functions: list[Function] = []

    def index(self, functions: list[Function]) -> None:
        self.functions = functions
        self.position = {f.qualname: i for i, f in enumerate(functions)}
        self.tfidf = TfidfIndex([f.tokens for f in functions], self.max_df)
        self.vocabulary = {token: i for i, token in enumerate(sorted(self.tfidf.idf))}
        rows, columns, weights = [], [], []
        for row, function in enumerate(functions):
            for token, weight in self.tfidf.vector(function.tokens).items():
                rows.append(row)
                columns.append(self.vocabulary[token])
                weights.append(weight)
        rows, columns, values = np.array(rows, dtype=np.int64), np.array(columns, dtype=np.int64), np.array(weights)
        rank = min(self.rank, len(functions), len(self.vocabulary))
        self.basis = np.zeros((len(self.vocabulary), rank))
        if rank:
            def times(x: np.ndarray) -> np.ndarray:  # A x
                out = np.zeros((len(functions), x.shape[1]))
                np.add.at(out, rows, values[:, None] * x[columns])
                return out

            def transposed_times(y: np.ndarray) -> np.ndarray:  # A^T y
                out = np.zeros((len(self.vocabulary), y.shape[1]))
                np.add.at(out, columns, values[:, None] * y[rows])
                return out

            sketch = min(rank + 10, len(functions), len(self.vocabulary))
            q = np.linalg.qr(times(np.random.default_rng(self.seed).standard_normal((len(self.vocabulary), sketch))))[0]
            for _ in range(self.power):
                q = np.linalg.qr(times(np.linalg.qr(transposed_times(q))[0]))[0]
            self.basis = np.linalg.svd(transposed_times(q).T, full_matrices=False)[2][:rank].T
        self.embedding = np.array([self.embed(f) for f in functions]).reshape(len(functions), rank)

    def embed(self, function: Function) -> np.ndarray:
        vector = np.zeros(self.basis.shape[1])
        for token, weight in self.tfidf.vector(function.tokens).items():
            vector += weight * self.basis[self.vocabulary[token]]
        norm = np.linalg.norm(vector)
        return vector / norm if norm else vector

    def ranked(self, function: Function) -> list[tuple[int, float]]:
        own = self.position.get(function.qualname)
        scores = self.embedding @ self.embed(function)
        return [(int(i), float(scores[i])) for i in np.argsort(-scores, kind="stable") if i != own]

    def neighbours(self, function: Function, k: int,
                   allowed: Callable[[Function], bool]) -> list[tuple[Function, float]]:
        found = []
        for position, similarity in self.ranked(function):
            if len(found) == k:
                break
            if allowed(self.functions[position]):
                found.append((self.functions[position], similarity))
        return found

    def similarity(self, a: Function, b: Function) -> float:
        return float(self.embed(a) @ self.embed(b))


def nearest(detector: Detector) -> dict[str, list[tuple[str, float]]]:
    """Every function's proposed neighbours under the detector's own budget, before any rule."""
    return {f.qualname: [(o.qualname, s) for o, s in detector.neighbours(f)] for f in detector.functions}


def mutual_nearest(detector: Detector, near: dict[str, list[tuple[str, float]]]) -> set[frozenset[str]]:
    """`Detector.scan`'s backlog from precomputed neighbours: mutual first neighbours that no rule settles."""
    best = {name: found[0] for name, found in near.items() if found}
    by_name = {f.qualname: f for f in detector.functions}
    return {frozenset((name, other)) for name, (other, _) in best.items()
            if name < other and best.get(other, ("",))[0] == name
            and why_skipped(by_name[name], by_name[other], detector.settings) is None}


def share_with_neighbour(near: dict[str, list[tuple[str, float]]]) -> float:
    return sum(bool(found) for found in near.values()) / len(near) if near else 0.0


def calibrated_floor(top: dict[str, list[tuple[str, float]]], share: float) -> float:
    """The floor at which `share` of functions keep a neighbour, from each function's best unfloored neighbour."""
    best = sorted((found[0][1] for found in top.values() if found), reverse=True)
    wanted = round(share * len(top))
    return best[min(wanted, len(best)) - 1] if wanted and best else float("inf")
