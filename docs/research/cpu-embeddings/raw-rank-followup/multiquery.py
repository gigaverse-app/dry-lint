# ruff: noqa: E401, E402, E741, F401, F403, F405, I001, B007
# Frozen experiment adapters intentionally preserve import order and shared wildcard exports.
"""Actual Detector.candidates route-major pools, full native shared campaigns."""

from hybrid import *
import dry_lint.detector as detector_module
from dry_lint.settings import ExplorationComparer
from types import SimpleNamespace
from collections import defaultdict
import argparse


class ReuseIndex:
    """Memoize only exact already-indexed object sequence; production ranking is unchanged."""

    def __init__(self, comparer, fs):
        self.inner = comparer
        self.fs = fs

    def __getattr__(self, key):
        return getattr(self.inner, key)

    def index(self, fs):
        assert len(fs) == len(self.fs) and all(a is b for a, b in zip(fs, self.fs, strict=True))


class RankFusion:
    name = "cpu-tail-rrf"
    version = "1-blocks2-tail2-k60-top20-origin-cosine"
    discovery_unseen = True
    similarity_reusable = False

    def __init__(self, h):
        self.h = h
        self.selected = {}

    def index(self, fs):
        assert fs is self.h.fs

    def neighbours(self, q, k, allowed):
        if k <= 0:
            return []
        rows = {}
        ranks = {}
        for route, comparer in [("blocks", self.h.blocks.comparer), ("tail", self.h.op)]:
            for rank, (f, score) in enumerate(comparer.neighbours(q, 20, allowed), 1):
                rows.setdefault(f.qualname, (f, score))
                ranks.setdefault(f.qualname, {})[route] = rank
        ordered = sorted(rows, key=lambda key: (-sum(1 / (60 + r) for r in ranks[key].values()), self.h.pos[key]))
        self.selected.update({(q.qualname, key): rows[key][1] for key in rows})
        return [rows[key] for key in ordered[: min(k, 1)]]

    def similarity(self, a, b):
        # Comparer prototype exposes only the selected-origin score already measured.
        # Production patch must specify standalone explain behavior before promotion.
        return self.selected.get((a.qualname, b.qualname), 0.0)


def actual_pool(h, changed, arm):
    choices = [
        ExplorationComparer(
            use="tfidf", neighbours=20, min_similarity=0.35, min_similarity_small=0.35, max_df=h.bg.max_df
        ),
        ExplorationComparer(use="operation-blocks", neighbours=1),
        ExplorationComparer(use="cpu-embedding", neighbours=1, model_dir=str(OLD / "model-cache")),
    ]
    if arm != "current109":
        choices.append(ExplorationComparer(use="hybrid-tail" if arm == "tail_append" else "hybrid-rrf", neighbours=1))
    s = h.s.model_copy(update={"discovery": h.s.discovery.model_copy(update={"comparers": choices})})
    comparers = {
        "tfidf": h.wide.comparer,
        "operation-blocks": h.blocks.comparer,
        "cpu-embedding": h.cpu.comparer,
        "hybrid-tail": h.op,
        "hybrid-rrf": RankFusion(h),
    }
    real = detector_module.load

    def loader(slot, choice):
        if slot == "comparers" and choice.use in comparers:
            return ReuseIndex(comparers[choice.use], h.fs)
        return real(slot, choice)

    detector_module.load = loader
    try:
        d = Detector(h.fs, s, ReuseIndex(h.base.comparer, h.fs), [PythonExtractor(), TypeScriptExtractor()])
        all_candidates = d.candidates(changed)
        return [c for c in all_candidates if c.lane != "relative"], [c for c in all_candidates if c.lane == "relative"]
    finally:
        detector_module.load = real


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", action="store_true")
    args = parser.parse_args()
    out = HERE / "multiquery"
    out.mkdir(exist_ok=True)
    if args.freeze:
        selected = read(HERE / "early-batch/selection-frozen.jsonl")
        groups = defaultdict(set)
        for r in selected:
            groups[r["background"]].add(r["query_position"])
        planned = []
        for bg, qs in sorted(groups.items()):
            qs = sorted(qs, key=lambda i: sha(("hybrid-multiquery:" + bg + ":" + str(i)).encode()))[:8]
            for i in range(0, len(qs), 4):
                if len(qs[i : i + 4]) >= 2:
                    planned.append(dict(background=bg, positions=qs[i : i + 4], group=i // 4))
        dump(
            out / "DESIGN.json",
            dict(
                groups=planned,
                source=ref(HERE / "early-batch/selection-frozen.jsonl"),
                selection="First8 selected query positions per repository by fixed SHA, groups4; minimum2. No provider/source outcomes.",
                pool="Unmodified Detector.candidates, route-major global pair dedup; conditional relatives recorded separately not primary cold admission",
                policy="Exact .04 Haiku native full-pool CampaignStore for complete multi-query pool; normal .04 shared ledger separate",
                scope="Synthetic fixed-query multi-change cold campaigns, not actual PR history; all gains/losses required",
                implementation=ref(Path(__file__)),
            ),
        )
        print("FROZEN", len(planned))
        raise SystemExit
    planned = json.loads((out / "DESIGN.json").read_text())["groups"]
    inputs = {folder.name: (folder, views) for folder, views, _ in cohorts()}
    for bg in sorted({r["background"] for r in planned}):
        folder, views = inputs[bg]
        local = out / bg
        local.mkdir(exist_ok=True)
        if (local / "COMPLETE.json").exists():
            continue
        h = Hybrid(folder, views, local)
        records = []
        for group in [r for r in planned if r["background"] == bg]:
            changed = [h.fs[i] for i in group["positions"]]
            arms = {}
            relatives = {}
            native = {}
            normal_rows = {}
            g = group["group"]
            for arm in ("current109", "tail_append", "fixed_rrf"):
                cs, rs = actual_pool(h, changed, arm)
                arms[arm] = [c.model_dump(mode="json") for c in cs]
                relatives[arm] = [c.model_dump(mode="json") for c in rs]
                normal_rows[arm] = normal(cs, h.s)
                native[arm], _ = h.native_campaign(SimpleNamespace(qualname="MULTI:" + str(g)), arm, cs, [], raw=True)
                native[arm]["database_source"] = str(local / "campaigns.sqlite")
            old = {e["key"] for e in native["current109"]["events"] if e["admitted"]}
            deltas = {
                arm: dict(
                    gains=sorted({e["key"] for e in native[arm]["events"] if e["admitted"]} - old),
                    losses=sorted(old - {e["key"] for e in native[arm]["events"] if e["admitted"]}),
                )
                for arm in ("tail_append", "fixed_rrf")
            }
            records.append(
                dict(
                    background=bg,
                    repository=h.bg.repository,
                    revision=h.bg.revision,
                    group=g,
                    query_positions=group["positions"],
                    query_ids=[q.qualname for q in changed],
                    arms=arms,
                    conditional_relatives=relatives,
                    normal=normal_rows,
                    native=native,
                    deltas=deltas,
                )
            )
            print("MULTI", bg[:8], g, deltas, flush=True)
        jsonl(local / "campaigns.jsonl.gz", records)
        dump(local / "COMPLETE.json", dict(groups=len(records), index_seconds=h.index_seconds, provider_calls=0))
        del h
