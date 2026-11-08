# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B905, E401, F401, F403, F405, I001
"""Pinned production candidate and campaign paths, cached vectors only; no providers."""

from common import *
from tail_cache import read_tail_cache
import argparse, collections, time
import numpy as np
from unittest.mock import patch
from dry_lint.models import Function, Run, Candidate, Verdict
from dry_lint.bench_background import BenchBackground
from dry_lint.comparers import TfidfComparer
from dry_lint.operation_blocks import OperationBlocksComparer
from dry_lint.cpu_embedding import CpuEmbeddingComparer
from dry_lint.cpu_tail import CpuTailRankFusionComparer
from dry_lint.detector import Detector
from dry_lint.comparer_resources import ComparerResources
from dry_lint.extractors import PythonExtractor
from dry_lint.typescript import TypeScriptExtractor
from dry_lint.settings import Settings, ExplorationComparer
from dry_lint.presets import PRESETS
from dry_lint.discovery import CampaignStore, reservation_cost
from dry_lint.costs import estimate, Ledger
from dry_lint.judges.command import prompt, PROMPT_POLICIES
from dry_lint.judging import Judging
from dry_lint.store import VerdictStore, DirectoryStore
from dry_lint.report import Report

MODEL = ROOT / "jobs/experiment-cpu-embeddings/.lab-results/model-cache"


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


class Reuse:
    def __init__(self, obj, fs):
        self.inner = obj
        self.fs = fs

    def __getattr__(self, k):
        return getattr(self.inner, k)

    def index(self, fs):
        assert len(fs) == len(self.fs) and all(a is b for a, b in zip(fs, self.fs))

    def index_for_run(self, fs, resources):
        self.index(fs)


class RankedVectors:
    name = "stronger-rank"
    discovery_unseen = True
    similarity_reusable = False

    def __init__(self, fs, query, doc, version):
        self.fs = fs
        self.q = query
        self.d = doc
        self.version = version
        self.pos = {f.qualname: i for i, f in enumerate(fs)}
        self.amb = {k for k, n in collections.Counter(f.qualname for f in fs).items() if n > 1}
        self.last = None
        self.ordered = []

    def index(self, fs):
        assert fs is self.fs

    def neighbours(self, q, k, allowed):
        if q.qualname in self.amb or q.line < 1:
            return []
        if self.last != q.qualname:
            scores = self.d @ self.q[self.pos[q.qualname]]
            self.ordered = sorted(
                range(len(self.fs)), key=lambda i: (-float(scores[i]), self.fs[i].qualname, digest(self.fs[i].code), i)
            )
            self.last = q.qualname
        found = [
            self.fs[i]
            for i in self.ordered
            if self.fs[i].qualname != q.qualname
            and self.fs[i].qualname not in self.amb
            and self.fs[i].line >= 1
            and allowed(self.fs[i])
        ]
        return [(f, 1 / (60 + rank)) for rank, f in enumerate(found[:k], 1)]

    def similarity(self, a, b):
        return next((s for f, s in self.neighbours(a, len(self.fs), lambda _: True) if f.qualname == b.qualname), 0.0)


def settings(p):
    pre = PRESETS["balanced"]
    return Settings(
        preset="balanced",
        judge={
            "use": "anthropic",
            "model": "claude-haiku-5-5",
            "prompt_policy": "shared-operations",
            "max_tokens": 2048,
            "max_retries": 0,
        },
        discovery=pre.discovery,
        escalate={"use": "none"},
        budget={"usd": 0.04},
        report_at=0.5,
        drop_below=0.5,
        fail_at=0.5,
        drift_at=0.8,
        include=p["scope"]["include"],
        exclude=p["scope"]["exclude"],
    )


def native(cs, s, run, out, changed=1, functions=0):
    out.mkdir(parents=True, exist_ok=False)
    store = CampaignStore(out / "campaign.sqlite", run)
    store.advance(s)
    events = []
    eligible = [c for c in cs if c.lane != "relative" and not c.filtered and min(c.new.line, c.existing.line) >= 1]
    for c in store.order(eligible):
        hold = reservation_cost(JUDGE, c, s)
        value = store.reserve(c, JUDGE, s, hold)
        events.append(
            dict(
                key=c.key,
                admitted=type(value) is int,
                reserve_result=value,
                attempt_index=value if type(value) is int else None,
                considered_reservation_usd=hold,
                native_held_usd=hold if type(value) is int else 0,
                normal_estimate_usd=estimate(JUDGE, [c], s),
                candidate_sha256=digest(json.dumps(c.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))),
            )
        )
    assert store.snapshot().usd <= 0.04 + 1e-12
    # Unknown answers remain unknown; full Judging/Report path does not synthesize verdicts.
    judging = Judging(s, None, None, VerdictStore(DirectoryStore(out / "verdicts")))
    report = Report.build(
        judging.findings(cs, run),
        s,
        [c for c in cs if c.filtered],
        run=run,
        changed=changed,
        functions=functions,
        judging=judging.summary(),
    )
    write(out / "report-unknown.json", report.model_dump(mode="json"))
    return dict(
        run=run.model_dump(mode="json"),
        events=events,
        state=store.snapshot().model_dump(mode="json"),
        database=str(out / "campaign.sqlite"),
        answers="unknown_no_provider_call",
        settings=s.model_dump(mode="json"),
        normal_admitted_keys=[eligible[i].key for i in Ledger(s).select(JUDGE, eligible)],
    )


def answer_binding(c, run, judge):
    return dict(
        repository=run.repository,
        revision=run.revision,
        candidate_sha256=digest(json.dumps(c.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))),
        context_hash=c.context_hash,
        source_bodies=[digest(c.new.code), digest(c.existing.code)],
        judge=judge.name,
        model=judge.model,
        version=judge.version,
        prompt_policy=judge.prompt_policy,
        max_output_tokens=judge.max_tokens,
        options={"max_retries": 0},
        rendered_input_sha256=digest(judge.input_text(c)),
    )


def replay_recorded(cs, s, run, out, answers):
    """After root supplies exact prompt-bound recordings, execute unmodified Judging scheduler/report."""

    class Recorded(Descriptor):
        def judge(self, candidates, settings):
            result = []
            for c in candidates:
                binding = answer_binding(c, run, self)
                key = digest(json.dumps(binding, sort_keys=True, separators=(",", ":")))
                r = answers.get(key)
                if r is None or r.get("binding") != binding:
                    raise ValueError("No exact source/model/options-bound recorded answer; unknown")
                result.append(Verdict.model_validate(r["verdict"]))
            return result

    judge = Recorded()
    j = Judging(s, judge, None, VerdictStore(DirectoryStore(out / "verdicts")))
    j.campaign = CampaignStore(out / "campaign.sqlite", run)
    return Report.build(
        j.findings(cs, run), s, [c for c in cs if c.filtered], run=run, judge=j.name, judging=j.summary()
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", required=True)
    ap.add_argument("--matrix-receipt")
    ap.add_argument("--out", required=True)
    ap.add_argument("--query-limit", type=int)
    a = ap.parse_args()
    p = next(p for p in jl(HERE / "panels.jsonl") if p["cohort_id"] == a.panel)
    out = Path(a.out)
    assert not out.exists()
    out.mkdir(parents=True)
    overrides = (
        json.loads((HERE / "baseline-matrices.json").read_text()) if (HERE / "baseline-matrices.json").exists() else {}
    )
    p = {**p, **overrides.get(p["cohort_id"], {})}
    assert p["native_context_available"] and sha(p["functions_path"]) == p["functions_sha256"]
    bg = BenchBackground.decode(Path(p["background_path"]).read_bytes())
    raw = jl(p["functions_path"])
    fs = []
    for f, d in zip(raw, bg.documents, strict=True):
        if f.get("line") is None:
            f = {**f, "line": 0, "end_line": -1}
        unit = Function.model_validate(f)
        assert unit.qualname == d.id and digest(unit.code) == d.source_sha256
        unit.tokens = d.tokens()
        fs.append(unit)
    s = settings(p)
    base = TfidfComparer(max_df=bg.max_df)
    base.index(fs)
    base.tfidf = bg.index()
    wide = TfidfComparer(0.35, 0.35, max_df=bg.max_df)
    wide.index(fs)
    wide.tfidf = base.tfidf
    blocks = OperationBlocksComparer()
    blocks.index(fs)
    comparers = {"tfidf": wide, "operation-blocks": blocks}
    arms = ["tfidf_blocks"]
    matrix_receipt = None
    if p["minilm_matrix_path"]:
        vec = np.load(p["minilm_matrix_path"], allow_pickle=False)
        assert sha(p["minilm_matrix_path"]) == p["minilm_matrix_sha256"]
        cpu = CpuEmbeddingComparer(MODEL)
        cpu._bodies = {f.code: v for f, v in zip(fs, vec, strict=True)}

        def fail_encode(codes):
            raise RuntimeError("Encoding prohibited in native replay; cached input missing")

        cpu.encoder.encode = fail_encode
        cpu.index(fs)
        comparers["cpu-embedding"] = cpu
        arms.append("minilm_prefix")
        if p.get("minilm_tail_matrix_path"):
            fusion = CpuTailRankFusionComparer(MODEL)
            fusion.tail.encoder.encode = fail_encode
            fusion.tail._bodies = dict(cpu._bodies)
            texts, tail_vectors = read_tail_cache(p)
            fusion.tail._bodies.update(zip(texts, tail_vectors, strict=True))
            fusion.index(fs)
            comparers["cpu-tail-rrf"] = fusion
            arms.append("minilm_stack")
    if a.matrix_receipt:
        matrix_receipt = json.loads(Path(a.matrix_receipt).read_text())
        r = matrix_receipt
        assert r["functions_sha256"] == p["functions_sha256"] and r["background_sha256"] == p["background_sha256"]
        assert sha(r["document_matrix_path"]) == r["document_matrix_sha256"]
        doc = np.load(r["document_matrix_path"], allow_pickle=False)
        q = np.load(r.get("query_matrix_path", r["document_matrix_path"]), allow_pickle=False)
        assert len(doc) == len(fs) and q.shape == doc.shape and np.isfinite(doc).all() and np.isfinite(q).all()
        comparers["stronger-rank"] = RankedVectors(
            fs, q, doc, r["method"] + "-" + digest(json.dumps(r, sort_keys=True))[:16]
        )
        arms += ["stronger_top1", "stronger_top2"]
    changed = sorted(
        {
            i
            for m in jl(HERE / "mapped-gold.jsonl")
            if m["cohort_id"] == a.panel and m["record_kind"] == "function"
            for i in m["query_positions"]
        }
    )
    if a.query_limit:
        changed = changed[: a.query_limit]
    groups = [[i] for i in changed]
    kit = ROOT / "jobs/hybrid-recall-research/.lab-results/combined-recall-data-v1/campaigns.jsonl.gz"
    shared = set()
    if not a.query_limit:
        for campaign in jl(kit):
            group = tuple(campaign.get("query_positions") or [])
            if campaign.get("background") == p["background_sha256"] and len(group) > 1:
                shared.add(group)
        groups += [list(g) for g in sorted(shared)]
    records = []
    native_load = ComparerResources.load

    def loader(resources, choice):
        return Reuse(comparers[choice.use], fs) if choice.use in comparers else native_load(resources, choice)

    for group in groups:
        if any(fs[i].line < 1 for i in group):
            continue
        qi = group[0] if len(group) == 1 else "shared-" + digest(json.dumps(group))[:12]
        record = dict(
            cohort_id=a.panel,
            repository=p["repository"],
            revision=p["revision"],
            query_positions=group,
            arms={},
            native={},
        )
        for arm in arms:
            choices = [
                ExplorationComparer(use="tfidf", neighbours=20),
                ExplorationComparer(use="operation-blocks", neighbours=1),
            ]
            if arm.startswith("minilm"):
                choices.append(ExplorationComparer(use="cpu-embedding", neighbours=1))
            if arm == "minilm_stack":
                choices.append(ExplorationComparer(use="cpu-tail-rrf", neighbours=1))
            if arm.startswith("stronger"):
                choices.append(ExplorationComparer(use="stronger-rank", neighbours=int(arm[-1])))
            ss = s.model_copy(update={"discovery": s.discovery.model_copy(update={"comparers": choices})})
            with patch.object(ComparerResources, "load", loader):
                cs = Detector(fs, ss, Reuse(base, fs), [PythonExtractor(), TypeScriptExtractor()]).candidates(
                    [fs[i] for i in group]
                )
            run = Run(
                repository=p["repository"],
                revision=p["revision"],
                session="encoder-v1:" + a.panel + ":" + str(qi) + ":" + arm,
            )
            record["arms"][arm] = [c.model_dump(mode="json") for c in cs]
            record["native"][arm] = native(
                cs, ss, run, out / "native" / str(qi) / arm, changed=len(group), functions=len(fs)
            )
        records.append(record)
        write(out / "campaigns.jsonl", records)
        print(a.panel, qi, [(arm, len(record["arms"][arm])) for arm in arms], flush=True)
    write(
        out / "RUN.json",
        dict(
            schema=1,
            panel=p,
            arms=arms,
            queries=len(records),
            provider_calls=0,
            encoding_calls=0,
            product_commit=REF,
            matrix_receipt=matrix_receipt,
            status="native_admissions_unknown_answers"
            if "minilm_stack" in arms
            else "current_stack_unavailable_missing_tail_cache",
        ),
    )


if __name__ == "__main__":
    main()
