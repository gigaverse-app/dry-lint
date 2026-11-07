# ruff: noqa: E401, E402, E741, F401, F403, F405, I001, B007
# Frozen experiment adapters intentionally preserve import order and shared wildcard exports.
"""Full-background selected-case retrieval from frozen vectors; no encoder/model acquisition."""

from common import *
import hybrid, multiquery
from hybrid import Hybrid
from dry_lint.cpu_embedding import CpuEmbeddingComparer
from dry_lint.models import Candidate
from multiquery import RankFusion
from collections import Counter


class CachedCpu(CpuEmbeddingComparer):
    version_contract = None

    def __init__(self, *args, **kwargs):
        self.np = np
        self.min_similarity = 0.65
        self.version = self.version_contract
        self.cache_dir = None
        self.cache_hits = self.cache_misses = self.memory_hits = 0
        self._bodies = {}
        self._ambiguous = set()
        self.functions = []

    def _vectors(self, codes):
        assert all(code in self._bodies for code in codes), "Frozen vector missing; no inference permitted"
        return np.stack([self._bodies[c] for c in codes])


class RawRankFusion(RankFusion):
    version = "2-raw-rank-k60-top20"

    def neighbours(self, q, k, allowed):
        if k <= 0:
            return []
        rows = {}
        ranks = {}
        for route, comparer in [("blocks", self.h.blocks.comparer), ("tail", self.h.op)]:
            for rank, (f, score) in enumerate(comparer.neighbours(q, 20, allowed), 1):
                rows.setdefault(f.qualname, f)
                ranks.setdefault(f.qualname, {})[route] = rank
        scores = {name: sum(1 / (60 + r) for r in rr.values()) for name, rr in ranks.items()}
        ordered = sorted(rows, key=lambda name: (-scores[name], self.h.pos[name]))
        self.selected.update({(q.qualname, name): score for name, score in scores.items()})
        return [(rows[name], scores[name]) for name in ordered[: min(k, 1)]]


def replay_retrieval(records, data, out):
    versions = {
        c["comparer"].split(":", 1)[1]
        for r in records
        for cs in r["arms"].values()
        for c in cs
        if c["comparer"].startswith("cpu-embedding:")
    }
    assert len(versions) == 1
    CachedCpu.version_contract = next(iter(versions))
    hybrid.CpuEmbeddingComparer = CachedCpu
    counts = Counter()
    for bg in sorted({r["background"] for r in records}):
        folder = data / "cohorts" / bg
        h = Hybrid(folder, folder, out / "retrieval" / bg)
        cache = {}
        for r in [x for x in records if x["background"] == bg]:
            if r["query_positions"]:
                for arm, expected in r["arms"].items():
                    key = (tuple(r["query_positions"]), arm)
                    if key not in cache:
                        multiquery.RankFusion = RawRankFusion if arm == "fixed_rrf_raw" else RankFusion
                        cs, _ = multiquery.actual_pool(h, [h.fs[i] for i in r["query_positions"]], arm)
                        cache[key] = [c.model_dump(mode="json") for c in cs]
                    assert cache[key] == expected, (bg, r["id"], arm, "shared retrieval")
                    counts["retrieval_arm_pools"] += 1
            else:
                qi = r["query_position"]
                if qi not in cache:
                    stages, tail, ranked, rrf = h.pool(h.fs[qi])
                    base = stages["current109"]
                    fusion = [
                        c.model_copy(
                            update={
                                "comparer": "cpu-tail-rrf:1-blocks2-tail2-k60-top20-origin-cosine",
                                "similarity_reusable": False,
                            }
                        )
                        for c in ranked[:1]
                    ]
                    raw = [
                        c.model_copy(
                            update={
                                "comparer": "cpu-tail-rrf:2-raw-rank-k60-top20",
                                "similarity": round(rrf[0]["rrf"], 3),
                                "similarity_reusable": False,
                            }
                        )
                        for c in ranked[:1]
                    ]
                    cache[qi] = {
                        a: [c.model_dump(mode="json") for c in cs]
                        for a, cs in dict(
                            current109=base,
                            tail_append=base + tail[:1],
                            fixed_rrf=base + fusion,
                            fixed_rrf_raw=base + raw,
                        ).items()
                    }
                for arm, expected in r["arms"].items():
                    assert cache[qi][arm] == expected, (bg, qi, arm, "retrieval")
                    counts["retrieval_arm_pools"] += 1
        counts["full_background_documents"] += len(h.fs)
        counts["retrieval_backgrounds"] += 1
        print("retrieval passed", bg[:8], len(h.fs), flush=True)
    return counts
