# ruff: noqa: E401, E402, E741, F401, F403, F405, I001, B007
# Frozen experiment adapters intentionally preserve import order and shared wildcard exports.
"""Bounded combined experiment; no provider imports or execution."""

from common import *
import time
from tail_index import OperationIndex
from dry_lint.cpu_embedding import CpuEmbeddingComparer
from dry_lint.comparers import TfidfComparer
from dry_lint.operation_blocks import OperationBlocksComparer
from dry_lint.detector import Detector
from dry_lint.extractors import PythonExtractor
from dry_lint.typescript import TypeScriptExtractor
from dry_lint.settings import Settings
from dry_lint.presets import PRESETS
from dry_lint.costs import estimate, Ledger
from dry_lint.discovery import CampaignStore, reservation_cost
from dry_lint.judges.command import prompt, PROMPT_POLICIES
from dry_lint.models import Candidate, Run, pair_key


class Descriptor:
    name = "anthropic-operations"
    model = "claude-haiku-5-5"
    max_tokens = 2048
    prompt_policy = "shared-operations"
    subscription = False
    version = PROMPT_POLICIES["shared-operations"][0] + ":claude-haiku-5-5:output=2048"

    def input_text(self, c):
        return prompt(c, policy=self.prompt_policy)


JUDGE = Descriptor()


def settings():
    p = PRESETS["balanced"]
    return Settings(
        preset="balanced",
        judge=p.judge,
        discovery=p.discovery,
        escalate={"use": "none"},
        budget={"usd": 0.04},
        report_at=0.5,
        drop_below=0.5,
        fail_at=0.5,
        drift_at=0.8,
    )


def normal(candidates, s):
    total = 0.0
    rows = []
    for i, c in enumerate(candidates, 1):
        charge = estimate(JUDGE, [c], s)
        reason = (
            "filtered:" + c.filtered
            if c.filtered
            else "unknown_native_span"
            if min(c.new.line, c.existing.line) < 1
            else "budget"
            if total + charge > 0.04
            else None
        )
        if reason is None:
            total += charge
        rows.append(
            dict(
                ordinal=i,
                key=c.key,
                admitted=reason is None,
                reason=reason or "normal_estimate_within_cap",
                normal_charge_usd=charge,
                cumulative_usd=total,
            )
        )
    eligible = [c for c in candidates if not c.filtered and min(c.new.line, c.existing.line) >= 1]
    assert {eligible[i].key for i in Ledger(s).select(JUDGE, eligible)} == {r["key"] for r in rows if r["admitted"]}
    return rows


class Hybrid:
    def __init__(self, folder, views, out):
        t = time.perf_counter()
        self.folder = folder
        self.out = out
        out.mkdir(parents=True, exist_ok=True)
        self.manifest, self.bg, self.fs, self.native = load(folder)
        fs = self.fs
        self.s = settings()
        self.s.include = self.bg.scope["include"]
        self.s.exclude = self.bg.scope["exclude"]
        self.pos = {f.qualname: i for i, f in enumerate(fs)}
        ex = [PythonExtractor(), TypeScriptExtractor()]
        self.base = Detector(fs, self.s, TfidfComparer(max_df=self.bg.max_df), ex)
        self.wide = Detector(
            fs,
            self.s.model_copy(update={"neighbours": 20}),
            TfidfComparer(0.35, 0.35, max_df=self.bg.max_df),
            ex,
            same_file=True,
        )
        frozen = self.bg.index()
        assert self.base.comparer.tfidf.idf == frozen.idf
        self.base.comparer.tfidf = self.wide.comparer.tfidf = frozen
        original = frozen.similar
        memo = {}

        def cached(document, limit=None, exclude=frozenset()):
            key = (tuple(document), frozenset(exclude))
            if key not in memo:
                memo.clear()
                memo[key] = original(document, exclude=exclude)
            return memo[key][:limit]

        frozen.similar = cached
        one = self.s.model_copy(update={"neighbours": 1})
        self.blocks = Detector(fs, one, OperationBlocksComparer(), ex, same_file=True, discovery_keys=set())
        assert self.blocks.comparer_id == "operation-blocks:2"
        vec = np.load(folder / "embeddings.npy", allow_pickle=False)
        cpu = CpuEmbeddingComparer(str(OLD / "model-cache"))
        cpu._bodies = {f.code: v for f, v in zip(fs, vec, strict=True)}
        self.cpu = Detector(fs, one, cpu, ex, same_file=True, discovery_keys=set())
        assert cpu.cache_misses == 0
        data = np.load(views / "view-vectors.npz", allow_pickle=False)
        self.op = OperationIndex(fs, vec, data["vectors"], data["owners"])
        self.tail = Detector(fs, one, self.op, ex, same_file=True, discovery_keys=set())
        hashed = self.base.hashed
        hashes = {}

        def cached_hash(f):
            key = (f.qualname, sha(f.code.encode()))
            if key not in hashes:
                hashes[key] = hashed(f)
            return hashes[key]

        for d in [self.base, self.wide, self.blocks, self.cpu, self.tail]:
            d.hashed = cached_hash
        self.index_seconds = time.perf_counter() - t

    def route(self, d, q, previous, k):
        d.discovery_keys = {c.key for c in previous} if d not in (self.base, self.wide) else None
        old = d.settings
        d.settings = old.model_copy(update={"neighbours": k})
        try:
            cs = [d.pair(q, g, v).model_copy(update={"lane": "exploration"}) for g, v in d.neighbours(q)]
        finally:
            d.settings = old
        keys = {c.key for c in previous}
        return [c for c in cs if c.key not in keys]

    def pool(self, q):
        base = [self.base.pair(q, g, v) for g, v in self.base.neighbours(q)]
        wide = base + self.route(self.wide, q, base, 20)
        block = wide + self.route(self.blocks, q, wide, 1)
        current = block + self.route(self.cpu, q, block, 1)
        tail = self.route(self.tail, q, current, 20)
        blocks = self.route(self.blocks, q, current, 20)
        union = {}
        ranks = {}
        for route, cs in [("operation-blocks:2", blocks), ("cpu-complete-statements:2-append", tail)]:
            for rank, c in enumerate(cs, 1):
                union.setdefault(c.key, c)
                ranks.setdefault(c.key, {})[route] = rank
        ranked = sorted(
            union.values(),
            key=lambda c: (-sum(1 / (60 + r) for r in ranks[c.key].values()), self.pos[c.existing.qualname]),
        )
        return (
            dict(baseline3=base, wide=wide, blocks=block, current109=current),
            tail,
            ranked,
            [
                dict(
                    key=c.key,
                    ranks=ranks[c.key],
                    rrf=sum(1 / (60 + r) for r in ranks[c.key].values()),
                    origin_comparer=c.comparer,
                    origin_similarity=c.similarity,
                )
                for c in ranked
            ],
        )

    def native_campaign(self, q, arm, base, extras, *, raw=False, normal_total=0.0, budget_select=False):
        run = Run(
            repository=self.bg.repository,
            revision=self.bg.revision,
            session="hybrid-v1:" + self.folder.name + ":" + q.qualname + ":" + arm,
        )
        store = CampaignStore(self.out / "campaigns.sqlite", run)
        assert not store.snapshot().attempts
        store.advance(self.s)

        def eligible(c):
            return not c.filtered and min(c.new.line, c.existing.line) >= 1

        order = store.order([c for c in base + (extras if raw else []) if eligible(c)])
        events = []
        selected = []

        def attempt(c, phase):
            hold = reservation_cost(JUDGE, c, self.s)
            index = store.reserve(c, JUDGE, self.s, hold)
            events.append(
                dict(
                    key=c.key,
                    candidate_sha256=sha(canonical(c.model_dump(mode="json"))),
                    phase=phase,
                    admitted=type(index) is int,
                    attempt_index=index if type(index) is int else None,
                    reserve_result=index,
                    normal_estimate_usd=estimate(JUDGE, [c], self.s),
                    native_held_usd=hold if type(index) is int else 0.0,
                    considered_reservation_usd=hold,
                )
            )
            return type(index) is int

        for c in order:
            attempt(c, "native_raw" if raw else "protected_baseline")
        if not raw:
            for c in extras:
                if not eligible(c):
                    continue
                if budget_select and normal_total + estimate(JUDGE, [c], self.s) > 0.04:
                    events.append(
                        dict(
                            key=c.key, phase="extra", admitted=False, reserve_result="normal_budget", attempt_index=None
                        )
                    )
                    continue
                admitted = attempt(c, "extra")
                if budget_select and not admitted:
                    continue
                selected.append(c)
                break
        state = store.snapshot()
        assert state.usd <= 0.04 + 1e-12
        return dict(run=run.model_dump(mode="json"), events=events, state=state.model_dump(mode="json")), selected

    def query(self, qi, raw=True):
        t = time.perf_counter()
        q = self.fs[qi]
        stages, tail, ranked, rrf = self.pool(q)
        base = stages["current109"]
        before = normal(base, self.s)
        native = {}
        native["current109"], _ = self.native_campaign(q, "current109", base, [], raw=True)
        native["tail_append"], _ = self.native_campaign(q, "tail_append", base + tail[:1], [], raw=True)
        base_admitted = {e["key"] for e in native["current109"]["events"] if e["admitted"]}
        selected = []
        trials = []
        for i, c in enumerate(ranked):
            normal_trial = normal(base + [c], self.s)
            if not normal_trial[-1]["admitted"]:
                trials.append(dict(key=c.key, reason="normal_budget"))
                continue
            trial, _ = self.native_campaign(q, "rrf_trial_" + str(i), base + [c], [], raw=True)
            admitted = {e["key"] for e in trial["events"] if e["admitted"]}
            eligible = c.key in admitted and base_admitted <= admitted
            trials.append(
                dict(
                    key=c.key,
                    reason="eligible" if eligible else "native_rejected_or_baseline_loss",
                    native=trial,
                    lost=sorted(base_admitted - admitted),
                )
            )
            if eligible:
                selected = [c]
                break
        native["fixed_rrf_budget"], _ = self.native_campaign(q, "fixed_rrf_budget", base + selected, [], raw=True)
        arms = dict(current109=base, tail_append=base + tail[:1], fixed_rrf_budget=base + selected)
        ledgers = {arm: normal(cs, self.s) for arm, cs in arms.items()}
        losses = {
            arm: sorted(base_admitted - {e["key"] for e in native[arm]["events"] if e["admitted"]})
            for arm in ("tail_append", "fixed_rrf_budget")
        }
        for arm in ("tail_append", "fixed_rrf_budget"):
            assert arms[arm][: len(base)] == base
            assert ledgers[arm][: len(before)] == before
        assert not losses["fixed_rrf_budget"]
        return dict(
            query_position=qi,
            query=q.qualname,
            background=self.folder.name,
            repository=self.bg.repository,
            revision=self.bg.revision,
            stage_keys={k: [c.key for c in v] for k, v in stages.items()},
            arms={arm: [c.model_dump(mode="json") for c in cs] for arm, cs in arms.items()},
            normal=ledgers,
            native=native,
            native_losses=losses,
            rrf_trials=trials,
            bounded_union=[c.model_dump(mode="json") for c in ranked],
            rrf=rrf,
            seconds=time.perf_counter() - t,
        )
