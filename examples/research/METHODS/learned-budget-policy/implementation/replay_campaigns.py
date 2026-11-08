# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B023, E401, E402, E731, F401, F403, F405, I001
"""Offline exact-observation replay; no providers and no reviewer labels."""

from policy_common import *
import argparse, collections, time

sys.path[:0] = [str(R), str(B)]
import native_harness as nh
from bank_loader import BankLoader
from transport_controls_v3 import canonical
from dry_lint.models import Candidate, Verdict, Run
from dry_lint.settings import Settings
from dry_lint.store import VerdictStore, DirectoryStore
from dry_lint.discovery import CampaignStore
from dry_lint.judging import Judging
from dry_lint.report import Report

INTAKE = ROOT / ".lab-results/encoder-judging/intakes/encoder-corpus-evaluation/r1-1e4e1e7230ab7987"


def load_answers(intakes):
    answers = {}
    receipts = []
    for intake in intakes:
        intake = pathlib.Path(intake)
        entries = {r["id"]: r for r in json.loads((intake / "entries.json").read_text())}
        requests = {r["request_key"]: r for r in json.loads((intake / "requests.json").read_text())}
        for feed in jl(intake / "method-feedback.jsonl"):
            e = entries[feed["id"]]
            if e["packet"]["repository"] == "anomalyco/opencode":
                continue
            for obs in feed["observations"]:
                if obs["kind"] != "claude" or obs["state"] != "exact_cache_hit" or obs.get("verdict") is None:
                    continue
                req = requests[obs["request_key"]]
                ident = req["identity"]
                c = Candidate.model_validate(e["packet"]["candidate"])
                proof = obs["provenance"]
                assert sha(proof["path"]) == proof["sha256"]
                raw = json.loads(pathlib.Path(proof["path"]).read_text())
                assert (
                    raw["identity"] == ident
                    and raw["request_key"] == obs["request_key"]
                    and raw["verdict"] == obs["verdict"]
                )
                assert ident["candidate_sha256"] == canonical(c) and ident["rendered_input"] == nh.JUDGE.input_text(c)
                assert (
                    ident["context_hash"] == c.context_hash
                    and ident["model"] == nh.JUDGE.model
                    and ident["max_output_tokens"] == nh.JUDGE.max_tokens
                    and ident["version"] == nh.JUDGE.version
                )
                key = (e["packet"]["repository"], e["packet"]["revision"], canonical(c))
                answers[key] = {
                    "verdict": obs["verdict"],
                    "usage": obs["usage"],
                    "actual_usd": raw["usd"],
                    "request_key": obs["request_key"],
                    "provenance": proof,
                    "rendered_input_sha256": digest(ident["rendered_input"]),
                }
        receipts.append(
            {
                "path": str(intake),
                "feedback_sha256": sha(intake / "method-feedback.jsonl"),
                "requests_sha256": sha(intake / "requests.json"),
            }
        )
    return answers, receipts


class Recorded(nh.Descriptor):
    def __init__(self, answers, run, native):
        self.answers = answers
        self.run = run
        self.native = native
        self.tokens = {"input": 0, "output": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}

    def lookup(self, c):
        return self.answers.get((self.run.repository, self.run.revision, canonical(c)))

    def judge(self, cs, settings):
        result = []
        for c in cs:
            row = self.lookup(c)
            if row is None:
                if self.native:
                    raise ValueError("Unrecorded exact answer; remains unknown, no provider call")
                result.append(None)
                continue
            assert row["rendered_input_sha256"] == digest(self.input_text(c))
            u = row["usage"]
            self.tokens["input"] += u["input_tokens"]
            self.tokens["output"] += u["output_tokens"]
            for k in ["cache_creation_input_tokens", "cache_read_input_tokens"]:
                self.tokens[k] += u.get(k, 0) or 0
            result.append(Verdict.model_validate(row["verdict"]))
        return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="replay-v1")
    ap.add_argument("--intake", action="append")
    a = ap.parse_args()
    out = H / a.out
    assert not out.exists()
    out.mkdir()
    answers, receipts = load_answers(a.intake or [INTAKE])
    write(out / "OBSERVATIONS.json", {"intakes": receipts, "exact_claude_answers": len(answers), "provider_calls": 0})
    normals = jl(H / "normal-campaigns.jsonl")
    guards = {(r["cohort_id"], r["query"]): r for r in jl(H / "guard-selections.jsonl")}
    normal_by = collections.defaultdict(dict)
    for r in normals:
        normal_by[r["cohort_id"], r["query_positions"][0]][r["arm"]] = r
    campaigns = {}
    panels = {}
    bank = {}
    loader = {}
    metas = {}
    plans = []
    for exp in json.loads((H / "HANDOFF.json").read_text())["exports"]:
        folder = pathlib.Path(exp["handoff"]).parent.parent
        panel = json.loads((folder / "RUN.json").read_text())["panel"]
        cid = panel["cohort_id"]
        panels[cid] = panel
        loader[cid] = BankLoader(cid)
        metas[cid] = jl(H / "arrays" / cid / "rows.jsonl")
        bank[cid] = {r["candidate_id"]: r for r in jl(D / "bank" / cid / "candidates.jsonl")}
        for cap in jl(folder / "campaigns.jsonl"):
            campaigns[cid, cap["query_positions"][0]] = cap
    summaries = []
    all_missing = {}
    gain_rows = []
    for (cid, q), cap in campaigns.items():
        panel = panels[cid]
        s = Settings.model_validate(cap["native"]["fusion_combined"]["settings"])
        armplans = {arm: r["candidates"] for arm, r in normal_by[cid, q].items()}
        armplans["raw_native"] = cap["arms"]["minilm_stack"]
        armplans["combined_native"] = cap["arms"]["fusion_combined"]
        for arm in ["guarded", "guarded_native", "guard_raw_count", "guard_raw_source"]:
            armplans[arm] = [
                loader[cid].candidate(bank[cid][metas[cid][i]["candidate_id"]]).model_dump(mode="json")
                for i in guards[cid, q]["indices"][arm]
            ]
        reports = {}
        for arm, rawcs in armplans.items():
            cs = [Candidate.model_validate(c) for c in rawcs]
            native = "_native" in arm
            folder = out / cid / str(q) / arm
            folder.mkdir(parents=True)
            run = Run(
                repository=panel["repository"],
                revision=panel["revision"],
                session=f"learned-policy-replay:{cid}:{q}:{arm}",
            )
            judge = Recorded(answers, run, native)
            j = Judging(s, judge, None, VerdictStore(DirectoryStore(folder / "verdicts")))
            if native:
                j.campaign = CampaignStore(folder / "campaign.sqlite", run)
            findings = j.findings(cs, run)
            report = Report.build(
                findings,
                s,
                run=run,
                changed=1,
                functions=len(loader[cid].functions),
                judge=judge.name,
                judging=j.summary(),
            )
            write(folder / "report.json", report.model_dump(mode="json"))
            reports[arm] = report
            normal_charge = sum(nh.estimate(nh.JUDGE, [c], s) for c in cs)
            assert normal_charge <= 0.04 + 1e-10
            unknown = [c for c in cs if judge.lookup(c) is None]
            known = [f for f in report.findings if f.verdict is not None]
            reported = [f for f in report.findings if f.reported]
            summary = {
                "cohort_id": cid,
                "query": q,
                "repository": panel["repository"],
                "revision": panel["revision"],
                "arm": arm,
                "candidates": len(cs),
                "exact_known_answers": len(known),
                "unknown_answers": len(unknown),
                "emitted_reports": len(reported),
                "reported_keys": [f.candidate.key for f in reported],
                "normal_logical_charge_usd": normal_charge,
                "actual_native_settled_or_reserved_usd": j.campaign.snapshot().usd if native else None,
                "complete": not unknown,
                "report": str(folder / "report.json"),
                "all_native_attempts": j.campaign.snapshot().model_dump(mode="json") if native else None,
            }
            summaries.append(summary)
            plans.append(
                {"cohort_id": cid, "query": q, "arm": arm, "settings": s.model_dump(mode="json"), "candidates": rawcs}
            )
            for ordinal, c in enumerate(cs):
                if judge.lookup(c) is not None:
                    continue
                ck = canonical(c)
                key = (cid, ck)
                entry = all_missing.setdefault(
                    key,
                    {
                        "id": "ENC-" + ck[:20],
                        "cohort_id": cid,
                        "repository": panel["repository"],
                        "revision": panel["revision"],
                        "candidate": c.model_dump(mode="json"),
                        "occurrences": [],
                        "normal_estimate_usd": nh.estimate(nh.JUDGE, [c], s),
                        "reservation_usd": nh.reservation_cost(nh.JUDGE, c, s),
                        "settings": s.model_dump(mode="json"),
                    },
                )
                entry["occurrences"].append(
                    {
                        "query": q,
                        "arm": arm,
                        "ordinal": ordinal + 1,
                        "original_normal_funded": True,
                        "original_native_funded": native,
                    }
                )
        # Exact provider reports are tracked independently from future source assessment.
        for method, base in [
            ("combined", "raw_dollar"),
            ("combined_native", "raw_native"),
            ("guarded", "raw_dollar"),
            ("guarded_native", "raw_native"),
        ]:
            shown = lambda arm: {f.candidate.key for f in reports[arm].findings if f.reported}
            gain_rows.append(
                {
                    "cohort_id": cid,
                    "query": q,
                    "method": method,
                    "baseline": base,
                    "reported_additions_so_far": sorted(shown(method) - shown(base)),
                    "reported_displacements_so_far": sorted(shown(base) - shown(method)),
                    "complete": all(x["complete"] for x in summaries[-len(armplans) :] if x["arm"] in [method, base]),
                    "source_assessment": "unread_pending_root",
                    "claim": "provisional observed reports only; unknown baseline/addition answers can change comparison",
                }
            )
    write(out / "campaign-results.jsonl", summaries)
    write(out / "paired-deltas.jsonl", gain_rows)
    write(out / "plans.jsonl", plans)
    write(out / "missing.jsonl", list(all_missing.values()))
    write(
        out / "RESULTS.json",
        {
            "original_changed_groups": len(campaigns),
            "arm_runs": len(summaries),
            "complete_arm_runs": sum(r["complete"] for r in summaries),
            "known_exact_answers": len(answers),
            "missing_distinct_source_candidates": len(all_missing),
            "reported_additions_not_source_truth": gain_rows,
            "provider_calls": 0,
            "normal_logical_charge_each_arm": True,
            "normal_adapter": "Recorded adapter returns None for missing answers; unmodified Judging/Ledger/Report retains unknown and charges logical selected prompts. No provider invocation.",
            "native_adapter": "Pinned CampaignStore with recorded usage and conservative holds for missing answers; every replay DB isolated.",
            "priority_note": "Candidate.priority is a computed property; earlier model_copy priority extras are not serialized. Frozen preselected sets all fit native holds, so membership is unchanged; native order follows the pinned scheduler.",
        },
    )
    print("REPLAY", len(summaries), "arms", len(all_missing), "missing")


if __name__ == "__main__":
    main()
