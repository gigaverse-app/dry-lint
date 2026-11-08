# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: F401, F403, F405, I001
"""Matched bank/capture experiment; provider-free, frozen sources, two threads."""

from policy import *
import argparse
import collections
import time
import resource
from native_harness import (
    Function,
    Detector,
    PythonExtractor,
    TypeScriptExtractor,
    settings,
    Judging,
    VerdictStore,
    DirectoryStore,
    Report,
    Verdict,
)
from dry_lint.report import Finding
from dry_lint.store import Lookup
from dry_lint.costs import Ledger, usage_cost, price
from dry_lint.models import evidence

BANK = ROOT / "jobs/complementary-signal-learning/.lab-results/bank"


class MissingAnswer(RuntimeError):
    pass


def recordings(extra_paths=(), include_default=True):
    found = collections.defaultdict(list)
    paths = []
    for folder in ("encoder-judging", "combined-judging", "enablement-judging") if include_default else ():
        paths.extend((ROOT / ".lab-results" / folder / "physical-account/observations").glob("*.json"))
    for p in extra_paths:
        paths.extend(p.glob("*.json") if p.is_dir() else [p])
    for path in sorted(paths):
        row = json.loads(path.read_text())
        identity = row.get("identity", {})
        if identity.get("kind") == "claude":
            found[identity.get("candidate_sha256")].append((path, row))
    return found


class RecordedJudge(type(JUDGE)):
    strict_version = True
    context = True

    def __init__(self, panel, cache, settings):
        self.panel, self.cache, self.settings = panel, cache, settings
        self.tokens = {"input": 0, "output": 0}
        self.events = []

    def lookup(self, c):
        expected = dict(
            repository=self.panel["repository"],
            revision=self.panel["revision"],
            background_sha256=self.panel["background_sha256"],
            scope=self.panel["scope"],
            candidate_sha256=canonical(c.model_dump(mode="json")),
            context_hash=c.context_hash,
            model=self.model,
            judge=self.name,
            version=self.version,
            max_output_tokens=self.max_tokens,
            rendered_input=self.input_text(c),
            source_evidence=evidence(c),
            execution_profile="balanced-shadow-haiku55-v1",
            request_options={
                "effort": None,
                "max_retries": 0,
                "prompt_policy": self.prompt_policy,
                "retry_malformed": False,
                "server_side_fallbacks": "disabled",
            },
            settings={
                "report_at": self.settings.report_at,
                "drop_below": self.settings.drop_below,
                "drift_at": self.settings.drift_at,
            },
        )
        for path, row in self.cache.get(expected["candidate_sha256"], []):
            ident = row["identity"]
            if any(ident.get(k) != v for k, v in expected.items()):
                continue
            assert row["request_key"] == canonical(ident)
            u = row.get("usage")
            if not u:
                return dict(
                    path=str(path),
                    sha256=sha(path),
                    verdict=None,
                    error=row.get("error") or "recorded_usage_unknown",
                    usage=None,
                    usd=None,
                    identity=ident,
                )
            usage = dict(
                input=u.get("input_tokens", 0),
                output=u.get("output_tokens", 0),
                cache_creation_input_tokens=u.get("cache_creation_input_tokens", 0),
                cache_read_input_tokens=u.get("cache_read_input_tokens", 0),
            )
            assert abs(usage_cost(usage, price(self, self.settings)) - row["usd"]) < 1e-12
            return dict(
                path=str(path),
                sha256=sha(path),
                verdict=row.get("verdict"),
                error=row.get("error"),
                usage=usage,
                usd=row["usd"],
                identity=ident,
            )
        return None

    def judge(self, candidates, settings):
        result = []
        for c in candidates:
            row = self.lookup(c)
            self.events.append(dict(key=c.key, recording=row))
            if row is None:
                raise MissingAnswer(c.key)
            for k, v in (row["usage"] or {}).items():
                self.tokens[k] = self.tokens.get(k, 0) + v
            if row["verdict"] is None or row["error"]:
                raise MissingAnswer("known_paid_failure:" + c.key)
            result.append(Verdict.model_validate(row["verdict"]))
        return result


class EmptyExactStore(VerdictStore):
    """Single query: external recordings must flow through paid logical admission."""

    def __init__(self, path):
        super().__init__(DirectoryStore(path))


class BankComparer:
    name = "adaptive-bank"
    version = "rank-agreement-v1"
    similarity_reusable = False

    def index(self, fs):
        pass


def native_replay(cs, signals, s, run, folder, arm, panel, cache):
    judge = RecordedJudge(panel, cache, s)
    store = EmptyExactStore(folder / "verdicts")
    campaign = AllocationStore(folder / "campaign.sqlite", run, arm, signals, s, "native_settled")
    judging = Judging(s, judge, None, store)
    judging.campaign = campaign
    censored = None
    try:
        findings = judging.findings(cs, run)
    except MissingAnswer as exc:
        censored = str(exc)
        # Prior successful answers passed through real Judging.remember; build the known prefix.
        findings = [
            Finding(
                candidate=c,
                verdict=store.lookup(c, judge.name, s.reopen_margin, judge.version, exact_source=True).verdict,
            )
            for c in cs
            if not c.filtered and c.lane != "relative"
        ]
    report = Report.build(findings, s, run=run, changed=1, judge=judge.name, judging=judging.summary())
    write(folder / "report.json", report.model_dump(mode="json"))
    state = campaign.snapshot()
    assert state.usd <= 0.04 + 1e-12
    result = dict(
        events=campaign.events,
        state=state.model_dump(mode="json"),
        database=str(campaign.path),
        run=run.model_dump(mode="json"),
        settings=s.model_dump(mode="json"),
        censored=censored,
        recordings=judge.events,
        actual_settled_usd=sum(e["settled_actual_usd"] or 0 for e in campaign.events),
        unresolved_hold_usd=sum(
            state.attempts[e["attempt_index"]].usd
            for e in campaign.events
            if e["admitted"] and e["settled_actual_usd"] is None
        ),
        reports=[f.candidate.key for f in report.findings if f.reported],
    )
    write(folder / "replay.json", result)
    return result


def normal(cs, signals, s, run, folder, arm, panel, cache):
    eligible = [c for c in cs if c.lane != "relative" and not c.filtered and min(c.new.line, c.existing.line) > 0]
    state = type("State", (), {"attempts": []})()
    order = ordered(eligible, arm, signals, s, state)
    ledger = Ledger(s)
    chosen = {order[i].key for i in ledger.select(JUDGE, order)}
    ledger.charge(JUDGE, [c for c in order if c.key in chosen], len(order) - len(chosen))
    judge = RecordedJudge(panel, cache, s)
    rows = []
    total = 0.0
    for c in order:
        charge = estimate(JUDGE, [c], s) if c.key in chosen else 0.0
        total += charge
        row = judge.lookup(c) if c.key in chosen else None
        rows.append(
            dict(
                key=c.key,
                admitted=c.key in chosen,
                normal_estimate_usd=estimate(JUDGE, [c], s),
                charge_usd=charge,
                cumulative_usd=total,
                recording=row,
                reported=s.duplicate_at(Verdict.model_validate(row["verdict"]), s.report_at)
                if row and row["verdict"] and not row["error"]
                else None,
            )
        )
    assert abs(total - ledger.usd) < 1e-12 and total <= 0.04 + 1e-12
    result = dict(
        events=rows,
        estimated_usd=total,
        unknown_funded=sum(
            r["admitted"] and (not r["recording"] or r["recording"]["verdict"] is None or bool(r["recording"]["error"]))
            for r in rows
        ),
        meaning="Outcome-independent normal-estimated allocation; missing answers are unknown, not completed native campaign",
        cached_recordings=sum(r["recording"] is not None for r in rows),
    )
    write(folder / "normal.json", result)
    return result


def export_frontiers(out, packets):
    """Bounded source-complete first missing questions, plus changed/displaced controls."""
    selected, seen, repos = [], set(), collections.Counter()
    for p in sorted(packets, key=lambda p: (not p["novel_vs_current"], p["id"])):
        if p["id"] in seen or repos[p["repository"]] >= 3 or len(selected) >= 12:
            continue
        if sum(len(p["candidate"][k]["code"]) for k in ("new", "existing")) > 16000:
            continue
        seen.add(p["id"])
        repos[p["repository"]] += 1
        selected.append(p)
    write(out / "frontier.jsonl", selected)
    write(
        out / "HANDOFF.json",
        dict(
            schema=1,
            status="READY" if selected else "no_first_missing_question",
            title="Bounded actual native missing-answer frontier",
            queue=str(out / "frontier.jsonl"),
            queue_sha256=sha(out / "frontier.jsonl"),
            questions=len(selected),
            new_discovery_questions=sum(p["novel_vs_current"] for p in selected),
            provider_calls=0,
            budget_usd=0.04,
            required="Coordinator source review and exact request execution; do not retry known paid failures",
            next="Replay from fresh ledgers with additional exact recordings to expose the next actually funded unknown; no speculative suffix funding",
        ),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--limit-panels", type=int)
    ap.add_argument("--inputs", type=Path)
    ap.add_argument("--observations", type=Path, action="append", default=[])
    ap.add_argument("--recordings-snapshot", type=Path)
    args = ap.parse_args()
    out = args.out.resolve()
    assert not out.exists()
    out.mkdir(parents=True)
    start = time.perf_counter()
    cpu = time.process_time()
    if args.recordings_snapshot:
        snapshot = json.loads(args.recordings_snapshot.read_text())["observations"]
        for r in snapshot:
            assert sha(r["path"]) == r["sha256"]
        cache = recordings([Path(r["path"]) for r in snapshot], include_default=False)
    else:
        cache = recordings(args.observations)
    available = {}
    for f in sorted((BASE / "native-runs").glob("*/RUN.json")):
        meta = json.loads(f.read_text())
        cid = meta["panel"]["cohort_id"]
        if "minilm_stack" in meta["arms"] and (BANK / cid / "RECEIPT.json").exists():
            available[cid] = f.parent
    split = json.loads((ROOT / "reports/complementary-recovery-team/SPLIT-CONTRACT.json").read_text())
    excluded = set(split["holdout"]["cohorts"])
    available = {cid: p for cid, p in available.items() if cid not in excluded}
    plan = json.loads((BASE / "ordered-full-background-plan.json").read_text())["plan"]
    cids = [p["cohort_id"] for p in plan if p["cohort_id"] in available][: args.limit_panels]
    if args.inputs:
        frozen = json.loads(args.inputs.read_text())
        available = {cid: Path(p) for cid, p in frozen["captures"].items()}
        cids = [p["cohort_id"] for p in plan if p["cohort_id"] in available][: args.limit_panels]
        for cid in cids:
            assert sha(BANK / cid / "candidates.jsonl") == frozen["banks"][cid]["bank_sha256"]
            if "capture_hashes" in frozen:
                assert sha(available[cid] / "campaigns.jsonl") == frozen["capture_hashes"][cid]
    write(
        out / "INPUTS.json",
        dict(
            design_sha256=sha(HERE / "DESIGN.json"),
            product_commit=REF,
            captures={cid: str(available[cid]) for cid in cids},
            capture_hashes={cid: sha(available[cid] / "campaigns.jsonl") for cid in cids},
            banks={cid: json.loads((BANK / cid / "RECEIPT.json").read_text()) for cid in cids},
            split_sha256=sha(ROOT / "reports/complementary-recovery-team/SPLIT-CONTRACT.json"),
        ),
    )
    results = []
    frontiers = []
    gold_rows = []
    all_deltas = []
    gold = jl(BASE / "mapped-gold.jsonl")
    for cid in cids:
        src = available[cid]
        receipt = json.loads((BANK / cid / "RECEIPT.json").read_text())
        p = receipt["source"]
        assert sha(BANK / cid / "candidates.jsonl") == receipt["bank_sha256"]
        assert sha(p["functions_path"]) == p["functions_sha256"]
        native_meta = json.loads((src / "RUN.json").read_text())
        assert (
            native_meta["product_commit"] == REF and native_meta["panel"]["background_sha256"] == p["background_sha256"]
        )
        assert native_meta["panel"]["functions_sha256"] == p["functions_sha256"]
        fs = [
            Function.model_validate(f if f.get("line") is not None else f | {"line": 0, "end_line": -1})
            for f in jl(p["functions_path"])
        ]
        pos = {f.qualname: i for i, f in enumerate(fs)}
        s = settings(p)
        detector = Detector(fs, s, BankComparer(), [PythonExtractor(), TypeScriptExtractor()], same_file=True)
        bank = collections.defaultdict(list)
        for r in jl(BANK / cid / "candidates.jsonl"):
            bank[r["query_position"]].append(r)
        proof = {(r["id"], r["source_sha256"]): r for r in jl(p["source_proof_path"])}
        for capture in jl(src / "campaigns.jsonl"):
            if len(capture["query_positions"]) != 1 or "minilm_stack" not in capture["arms"]:
                continue
            q = capture["query_positions"][0]
            old = [Candidate.model_validate(c) for c in capture["arms"]["minilm_stack"]]
            known = {c.key for c in old}
            extra = []
            signals = {}
            stages = collections.Counter()
            for c in old:
                assert digest(c.new.code) == digest(fs[pos[c.new.qualname]].code) and digest(c.existing.code) == digest(
                    fs[pos[c.existing.qualname]].code
                )
            for r in bank[q]:
                f = r["features"]
                stages["bank_rows"] += 1
                a, b = fs[q], fs[r["target_position"]]
                assert (
                    digest(a.code) == r["source"]["query"]["source_sha256"]
                    and digest(b.code) == r["source"]["target"]["source_sha256"]
                )
                if not r["native_eligible"]:
                    stages["structural_ineligible"] += 1
                    continue
                c = detector.pair(a, b, r["scores"]["fixed_fusion"]).model_copy(update={"lane": "exploration"})
                signals[c.key] = {
                    "tfidf_rank": f["tfidf_rank"],
                    "minilm_rank": f["minilm_rank"] if f["minilm_available"] else None,
                    "same_file": f["same_file"],
                    "bank_id": r["candidate_id"],
                    "routes": r["routes"],
                }
                if c.key in known:
                    continue
                if c.filtered:
                    stages["native_filtered:" + c.filtered] += 1
                    continue
                if min(sum(bool(x.strip()) for x in z.code.splitlines()) for z in (a, b)) < 8:
                    stages["new_size_guard"] += 1
                    continue
                if not f["minilm_available"] or f["tfidf_rank"] > 50 or f["minilm_rank"] > 10:
                    stages["new_agreement_gate"] += 1
                    continue
                assert a.qualname != b.qualname
                extra.append(c)
                known.add(c.key)
                stages["new_same_file" if a.path == b.path else "new_cross_file"] += 1
            pool = old + extra
            sig = features(pool, signals)
            record = dict(cohort_id=cid, query=q, stages=dict(stages), new_candidates=len(extra), arms={})
            for arm in ("fixed", "uniform", "cost", "adaptive"):
                cs = old if arm == "fixed" else pool
                folder = out / cid / str(q) / arm
                run = Run(repository=p["repository"], revision=p["revision"], session=f"adaptive-v1:{cid}:{q}:{arm}")
                # cost control and adaptive differ only by family penalty below.
                arm_sig = sig if arm != "cost" else {k: v | {"family_proxy": k} for k, v in sig.items()}
                actual_arm = "adaptive" if arm == "cost" else arm
                nr = normal(cs, arm_sig, s, run, folder, actual_arm, p, cache)
                native = native_replay(cs, arm_sig, s, run, folder, actual_arm, p, cache)
                record["arms"][arm] = dict(normal=nr, native=native)
                if native["censored"] and not native["censored"].startswith("known_paid_failure:"):
                    key = native["censored"]
                    c = next(c for c in cs if c.key == key)
                    event = next(e for e in native["events"] if e["key"] == key and e["admitted"])
                    proofs = []
                    for f in (c.new, c.existing):
                        pr = proof[(f.qualname, digest(f.code))]
                        assert pr["matching_native_symbols"] == 1
                        assert (f.line, f.end_line) == (pr["line"], pr["end_line"]) and sha(pr["source_file"]) == pr[
                            "file_sha256"
                        ]
                        proofs.append(pr)
                    frontiers.append(
                        dict(
                            id="AB-" + canonical(c.model_dump(mode="json"))[:20],
                            cohort_id=cid,
                            query=q,
                            arm=arm,
                            repository=p["repository"],
                            revision=p["revision"],
                            candidate=c.model_dump(mode="json"),
                            source_proofs=proofs,
                            background_proof={"path": p["background_path"], "sha256": p["background_sha256"]},
                            settings=s.model_dump(mode="json"),
                            run=run.model_dump(mode="json"),
                            judge=dict(
                                name=JUDGE.name,
                                version=JUDGE.version,
                                model=JUDGE.model,
                                max_tokens=JUDGE.max_tokens,
                                prompt_policy=JUDGE.prompt_policy,
                                max_retries=0,
                            ),
                            rendered_prompt=JUDGE.input_text(c),
                            prompt_sha256=digest(JUDGE.input_text(c)),
                            funding=dict(
                                ledger_kind="native_reserve_settle",
                                actually_reserved=True,
                                cap_usd=0.04,
                                event=event,
                                accounted_usd=native["state"]["prior_usd"]
                                + sum(a["usd"] for a in native["state"]["attempts"]),
                                actual_settled_usd=native["actual_settled_usd"],
                                unresolved_hold_usd=native["unresolved_hold_usd"],
                                database=native["database"],
                                database_sha256=sha(native["database"]),
                            ),
                            normal_estimated_funded=any(e["key"] == key and e["admitted"] for e in nr["events"]),
                            novel_vs_current=key not in {c.key for c in old},
                            role="new_question" if key not in {c.key for c in old} else "changed_or_retained_control",
                        )
                    )
            baseline = {e["key"] for e in record["arms"]["fixed"]["normal"]["events"] if e["admitted"]}
            baseline_lane = {c.key for c in old if c.lane == "baseline"} & baseline
            for arm in ("uniform", "cost", "adaptive"):
                funded = {e["key"] for e in record["arms"][arm]["normal"]["events"] if e["admitted"]}
                assert baseline_lane <= funded
                all_deltas.append(
                    dict(
                        cohort_id=cid,
                        query=q,
                        arm=arm,
                        added=sorted(funded - baseline),
                        displaced=sorted(baseline - funded),
                        baseline_lane_lost=[],
                    )
                )
            for g in gold:
                if g["cohort_id"] != cid or q not in g["query_positions"] or len(g["query_positions"]) != 2:
                    continue
                target = (
                    next(i for i in g["query_positions"] if i != q) if len(set(g["query_positions"])) == 2 else None
                )
                if target is None:
                    continue
                from dry_lint.models import pair_key

                key = pair_key(fs[q].qualname, fs[target].qualname)
                gold_rows.append(
                    dict(
                        row_id=g["row_id"],
                        pair_identity=g["pair_identity"],
                        cohort_id=cid,
                        query=q,
                        label=g["label"],
                        accepted_gold=g["accepted_gold"],
                        family_component=g["family_component"],
                        arms={
                            arm: dict(
                                retrieved=key in {c.key for c in (old if arm == "fixed" else pool)},
                                funded=any(e["key"] == key and e["admitted"] for e in v["normal"]["events"]),
                                native_known_report=key in v["native"]["reports"],
                            )
                            for arm, v in record["arms"].items()
                        },
                    )
                )
            # Full candidates once per query, source/provenance kept, no label mutation.
            write(
                out / cid / str(q) / "candidates.json",
                dict(
                    current=[c.model_dump(mode="json") for c in old],
                    extra=[c.model_dump(mode="json") for c in extra],
                    signals=sig,
                ),
            )
            results.append(record)
        export_frontiers(out, frontiers)
        write(
            HERE / "STATUS.json",
            dict(
                title="Bounded adaptive discovery under unchanged $0.04",
                stage="Executing matched source-bank allocation and settled native frontiers",
                measured_coverage={
                    "backgrounds": len({r["cohort_id"] for r in results}),
                    "queries": len(results),
                    "provider_calls": 0,
                },
                next_artifact=str(out / "HANDOFF.json"),
            ),
        )
        print(cid, len(results), "cumulative queries", round(time.perf_counter() - start, 2), "seconds", flush=True)
        write(out / "results.jsonl", results)
        write(out / "gold-stages.jsonl", gold_rows)
        write(out / "deltas.jsonl", all_deltas)
    summary = {
        arm: dict(
            campaigns=len(results),
            normal_funded=sum(sum(e["admitted"] for e in r["arms"][arm]["normal"]["events"]) for r in results),
            normal_estimated_usd=sum(r["arms"][arm]["normal"]["estimated_usd"] for r in results),
            native_settled_answers=sum(
                sum(e["settled_actual_usd"] is not None for e in r["arms"][arm]["native"]["events"]) for r in results
            ),
            native_censored=sum(r["arms"][arm]["native"]["censored"] is not None for r in results),
            normal_recording_hits=sum(r["arms"][arm]["normal"]["cached_recordings"] for r in results),
        )
        for arm in ("fixed", "uniform", "cost", "adaptive")
    }
    write(
        out / "SUMMARY.json",
        dict(
            arms=summary,
            backgrounds=len(cids),
            provider_calls=0,
            wall_seconds=time.perf_counter() - start,
            cpu_seconds=time.process_time() - cpu,
            peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            coverage="Completed matched capture/bank intersection; not full 826-row inventory and not PR-diff replay",
        ),
    )
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
