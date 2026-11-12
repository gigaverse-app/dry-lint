# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B007, B023, F401, F403, F405, I001
"""One novelty lever on three authenticated historical allocation regressions.

Reuse completed fair controls and exact recordings. No historical rediscovery,
no provider calls and no retry of paid malformed answers.
"""

from policy import *
import importlib.util
import subprocess
import time
from collections import Counter
from native_harness import Judging, Report, Verdict
from dry_lint.costs import Ledger
from dry_lint.report import Finding

PRIOR = ROOT / "jobs/experiment-budget-ranking/.lab-results"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    # Prior harnesses prepend their source path: pin imports again immediately.
    sys.path.insert(0, str(BASE / "runtime/src"))
    return m


def fair_novelty(cs, original, attempts, fs, penalize=True):
    baseline = [c for c in original if c.lane == "baseline"]
    counts = Counter((a.lane, a.query) for a in attempts)
    families = Counter(c.existing.hash or digest(c.existing.code) for c in baseline)
    result = list(baseline)
    pending = [c for c in cs if c.lane != "baseline"]
    while pending:

        def key(c):
            family = c.existing.hash or digest(c.existing.code)
            penalty = 1 + families[family] if penalize else 1
            return (
                -c.priority,
                counts[c.lane, c.new.qualname],
                -fs[c.key]["utility"] / penalty,
                c.existing.qualname,
                c.existing.line,
                c.new.qualname,
                c.key,
            )

        c = min(pending, key=key)
        pending.remove(c)
        result.append(c)
        counts[c.lane, c.new.qualname] += 1
        families[c.existing.hash or digest(c.existing.code)] += 1
    return result


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    out = args.out.resolve()
    assert not out.exists()
    out.mkdir()
    started = time.perf_counter()
    h = load("historical_original", ROOT / "retrieval/.lab-results/historical-pr-replay/replay.py")
    e = load("prior_order_features", PRIOR / "run_experiment.py")
    w = load("prior_observation_merge", PRIOR / "continue_replay_normal_only_v2.py")
    h.OUT = out
    histories, inventory = h.load_histories()
    chosen = {"gigaverse-ai-3202", "gigaverse-backend-5633", "gigaverse-ai-3294"}
    histories = [x for x in histories if x["name"] in chosen]
    merged = []
    for folder in (
        ROOT / "retrieval/.lab-results/historical-pr-replay/provider/accepted-observations",
        PRIOR / "provider-observations",
    ):
        for path in sorted(folder.glob("*.json")):
            if path.name.endswith(".response.json"):
                continue
            obs = json.loads(path.read_text())
            for history in histories:
                if obs["key"] in history["bindings"]:
                    w.merge_observation(history, obs, h, merged)
    prior = json.loads((PRIOR / "funded-rounds/round2/replay-v1/results.json").read_text())
    controls = {(r["cohort"], r["history"]): r for r in prior}
    original = h.AuditCampaignStore
    results = []
    normal_results = []
    authentication = []
    for history in histories:
        s = history["settings"]
        judge = h.OfflineJudge(s, history["answers"])
        judge.bindings = history["bindings"]
        gitroot = (
            ROOT / "research-corpus/history-inputs/git" / (history["history"]["repository"].split("/")[-1] + ".git")
        )
        # Real merge-base/head diffs, not synthetic unions of labeled function queries.
        for snap, path in history["steps"]:
            run = snap.run
            tree = subprocess.check_output(
                ["git", "-C", str(gitroot), "rev-parse", run.head + "^{tree}"], text=True
            ).strip()
            assert tree == run.revision
            ancestry = subprocess.run(
                ["git", "-C", str(gitroot), "merge-base", run.base, run.head], capture_output=True, text=True
            )
            # Partial Git packs contain trees but may lack ancestors. Preserve that limitation.
            base = ancestry.stdout.strip() if ancestry.returncode == 0 else run.base
            diff_result = subprocess.run(
                ["git", "-C", str(gitroot), "diff", "-U0", base, run.head], capture_output=True
            )
            dest = out / "diffs" / history["name"] / (path.stem + ".diff")
            if diff_result.returncode == 0:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(diff_result.stdout)
            proof_path = (
                PRIOR
                / "continuation-v23/historical-source-verification"
                / f"{history['cohort']}-{history['name']}.json"
            )
            prior_proof = json.loads(proof_path.read_text())
            bodies = {(r.get("head"), r.get("id"), r.get("body_sha256")) for r in prior_proof}
            for c in snap.candidates:
                for f in (c.new, c.existing):
                    assert (run.head, f.qualname, digest(f.code)) in bodies
            authentication.append(
                dict(
                    history=history["name"],
                    head=run.head,
                    base=run.base,
                    tree=tree,
                    changed=snap.changed,
                    capture=str(path),
                    capture_sha256=sha(path),
                    diff=str(dest) if dest.exists() else None,
                    diff_sha256=sha(dest) if dest.exists() else None,
                    original_source_authentication=str(proof_path),
                    original_source_authentication_sha256=sha(proof_path),
                    computed_merge_base=base if ancestry.returncode == 0 else None,
                    diff_kind=(
                        "verified-merge-base-to-head"
                        if ancestry.returncode == 0
                        else "recorded-base-tree-to-head; ancestry unavailable"
                    )
                    if dest.exists()
                    else "actual historical diff-selected capture; diff reacquisition unavailable",
                    ancestry_error=ancestry.stderr[:300] if ancestry.returncode else None,
                    diff_error=diff_result.stderr.decode()[:300] if diff_result.returncode else None,
                )
            )

        class NoveltyCampaign(original):
            def reserve(self, candidate, judge, settings, usd):
                token = super().reserve(candidate, judge, settings, usd)
                # Legacy audit wrapper predates the native string "budget" sentinel.
                # Correct evidence flags, without changing a reservation decision.
                event = self.reservation_events[-1]
                event["admitted"] = type(token) is int
                event["decline"] = (
                    None
                    if type(token) is int
                    else "money_or_credit_bound"
                    if token == "budget"
                    else "call_limit_or_duplicate_attempt"
                )
                return token

            def order(self, cs):
                current = super().order(cs)
                fs = {c.key: e.features(c, judge, s) for c in cs}
                return fair_novelty(cs, current, self.snapshot().attempts, fs)

        h.AuditCampaignStore = NoveltyCampaign
        result = h.evaluate(history, "balanced")
        result["ordering_arm"] = "fair_family_novelty"
        control = controls[(history["cohort"], history["name"])]
        old, new = control["reported_questions"], result["reported_questions"]
        result["comparison_to_frozen_prior_fair"] = dict(
            control=str(PRIOR / "funded-rounds/round2/replay-v1/results.json"),
            current_reports=len(old),
            new_reports=len(new),
            gains=sorted(new.keys() - old.keys()),
            losses=sorted(old.keys() - new.keys()),
            complete=not result["censored"],
        )
        results.append(result)
        for arm in ("prior_fair", "fair_family_novelty"):
            attempted = set()
            counts = Counter()
            spent = 0.0
            rows = []
            reports = {}
            censored = None
            for ordinal, (snap, path) in enumerate(history["steps"]):
                if censored:
                    break
                cs = [c for c in snap.candidates if c.lane != "relative" and not c.filtered]
                # Exact captured baseline order from native store, without opening a control ledger.
                empty = type("State", (), {"attempts": []})()
                baseorder = ordered(cs, "fixed", features(cs), s, empty)
                attempts = [
                    type("Attempt", (), {"lane": lane, "query": query})()
                    for (lane, query), n in counts.items()
                    for _ in range(n)
                ]
                fs = {c.key: e.features(c, judge, s) for c in cs}
                order = fair_novelty(cs, baseorder, attempts, fs, arm != "prior_fair")
                ledger = Ledger(s, spent=spent)
                pending = [c for c in order if judge.key(c) not in attempted]
                selected = {pending[i].key for i in ledger.select(judge, pending)}
                findings = []
                for c in order:
                    key = judge.key(c)
                    cached = key in attempted
                    funded = c.key in selected or cached
                    if not funded:
                        continue
                    if not cached:
                        spent += estimate(judge, [c], s)
                        attempted.add(key)
                        counts[c.lane, c.new.qualname] += 1
                    obs, reason = judge.lookup(c)
                    v = Verdict.model_validate(obs["verdict"]) if obs and obs.get("verdict") else None
                    rows.append(
                        dict(
                            ordinal=ordinal,
                            key=key,
                            pair=c.key,
                            cached=cached,
                            normal_charge_usd=0 if cached else estimate(judge, [c], s),
                            cumulative_usd=spent,
                            recorded_actual_usd=obs["usd"] if obs else None,
                            verdict=v.model_dump(mode="json") if v else None,
                            reason=reason,
                        )
                    )
                    if obs is None or v is None:
                        censored = dict(
                            ordinal=ordinal, key=key, reason=reason, known_paid_failure=obs is not None, retry=False
                        )
                        break
                    findings.append(Finding(candidate=c, verdict=v, cached=cached))
                report = Report.build(findings, s, run=snap.run, changed=snap.changed, judge=judge.name)
                for f in report.findings:
                    if f.reported:
                        reports[judge.key(f.candidate)] = f.candidate.key
                write(out / "normal" / history["name"] / arm / (str(ordinal) + ".json"), report.model_dump(mode="json"))
                assert spent <= 0.04 + 1e-12
            write(out / "normal" / history["name"] / arm / "rows.jsonl", rows)
            normal_results.append(
                dict(
                    history=history["name"],
                    arm=arm,
                    estimated_usd=spent,
                    reported_questions=reports,
                    censored=censored,
                    exact_recordings=sum(not r["cached"] and r["verdict"] is not None for r in rows),
                    chronological_cache_hits=sum(r["cached"] for r in rows),
                )
            )
        print(history["name"], result["comparison_to_frozen_prior_fair"], flush=True)
    h.AuditCampaignStore = original
    write(out / "native-results.json", results)
    write(out / "normal-results.json", normal_results)
    write(out / "authenticated-diffs.json", authentication)
    write(out / "recording-merge-provenance.json", merged)
    write(
        out / "SUMMARY.json",
        dict(
            histories=len(histories),
            revisions=len(authentication),
            new_native_arms=len(results),
            frozen_native_control_arms_reexecuted=0,
            provider_calls=0,
            seconds=time.perf_counter() - started,
            policy="Only existing-side exact structure-family novelty added to prior priority/query-fair utility; same candidate pools and settings",
            primary_normal_comparison="prior_fair vs fair_family_novelty; actual cached settlement separately native",
            excluded_paid_failure="AI3296 not rerun or retried; prior normal suffix remains censored",
            sources={
                "prior_final_evidence": sha(PRIOR / "FINAL-EVIDENCE.json"),
                "prior_fair_results": sha(PRIOR / "funded-rounds/round2/replay-v1/results.json"),
            },
        ),
    )


if __name__ == "__main__":
    main()
