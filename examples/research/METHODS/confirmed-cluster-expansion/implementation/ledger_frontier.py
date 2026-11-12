# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B007, E401, E402, E741, F401, I001
"""Exact native-ledger linkage and concrete incremental leads; never funds requests."""

import sys

sys.dont_write_bytecode = True
import pathlib, json, collections
from extended_run import LAB, atomic, sha, canonical, stream
import run_cluster as base


def main():
    seeds = {s["seed_id"]: s for s in stream(LAB / "seed-exposures.jsonl")}
    prior = {k: s for k, s in seeds.items() if s["seed_mode"] == "real_prior_judge_confirmed"}
    by_cohort = collections.defaultdict(list)
    for s in prior.values():
        by_cohort[s["cohort_id"]].append(s)
    ledger_root = base.ROOT / "jobs/adaptive-judge-budget/.lab-results/matched-captures"
    matches = collections.defaultdict(list)
    checked = 0
    for cid, ss in sorted(by_cohort.items()):
        expected = {canonical(s["seed_candidate"]): s for s in ss}
        for path in sorted((ledger_root / cid).glob("*/*/report.json")):
            report = json.loads(path.read_text())
            rp = path.with_name("replay.json")
            if not rp.exists():
                continue
            replay = json.loads(rp.read_text())
            settings = replay.get("settings", {})
            run = replay.get("run", {})
            if settings.get("budget", {}).get("usd") != 0.04:
                continue
            checked += 1
            for f in report.get("findings", []):
                if not f.get("reported") or not f.get("verdict"):
                    continue
                candidate = base.Candidate.model_validate(f["candidate"]).model_dump(mode="json")
                s = expected.get(canonical(candidate))
                if s is None:
                    continue
                source = s["source"]
                if run.get("repository") != source["repository"] or run.get("revision") != source["revision"]:
                    continue
                if (
                    settings.get("include") != source["scope"]["include"]
                    or settings.get("exclude") != source["scope"]["exclude"]
                ):
                    continue
                if f["verdict"] != s["verdict"]:
                    continue
                physical = [e.get("recording") for e in replay.get("recordings", []) if e.get("recording")]
                exact = [x for x in physical if x.get("identity") and canonical(x["identity"]) == s["request_key"]]
                if not exact:
                    continue
                matches[s["seed_id"]].append(
                    {
                        "report": str(path),
                        "report_sha256": sha(path),
                        "replay": str(rp),
                        "replay_sha256": sha(rp),
                        "budget_usd": 0.04,
                        "actual_settled_usd": replay.get("actual_settled_usd"),
                        "unresolved_hold_usd": replay.get("unresolved_hold_usd"),
                        "normal_ledger": str(path.with_name("normal.json")),
                        "interpretation": "exact parent reported in retrospective native replay; does not establish deployed traffic or admission of newly appended graph leads",
                    }
                )
    audit = []
    for sid, s in prior.items():
        audit.append(
            {
                "seed_id": sid,
                "cohort_id": s["cohort_id"],
                "exact_native_parent_ledgers": matches[sid],
                "status": "native_parent_replay_matched"
                if matches[sid]
                else "no_exact_native_parent_report_and_ledger_match",
                "new_graph_leads_admitted": False,
                "reason": "adaptive-judge-budget owns residual-budget replay; no fresh $0.04 allowance invented after the seed",
            }
        )
    atomic(
        LAB / "NATIVE-LEDGER-AUDIT.json",
        {
            "schema": 1,
            "budget_usd": 0.04,
            "native_reports_checked": checked,
            "provider_seed_exposures": len(prior),
            "matched_seed_exposures": sum(bool(matches[sid]) for sid in prior),
            "new_graph_leads_admitted": 0,
            "provider_calls": 0,
            "rows": audit,
        },
    )
    outcomes = {r["proposal_id"]: r for r in stream(LAB / "outcomes.jsonl")}
    known = {}
    unknown = {}
    priority = {"real_prior_judge_confirmed": 0, "one_available_source_seed_replay": 1, "source_gold_oracle_replay": 2}
    for p in stream(LAB / "proposals.jsonl"):
        if (
            p["seed_mode"] == "false_seed_control"
            or not p["incremental_vs_current_relatives"]
            or p["method"] not in base.METHODS[2:]
        ):
            continue
        labels = outcomes[p["proposal_id"]]["labels"]
        sid = p["seed_id"]
        s = seeds[sid]
        pair = (p["cohort_id"], tuple(sorted((p["query_position"], p["target_position"]))))
        accepted = [l for l in labels if l.get("accepted_gold") and l["label"] in base.USEFUL]
        item = p | {
            "seed_evidence": {
                "seed_id": sid,
                "mode": p["seed_mode"],
                "provider_confirmed": s.get("provider_confirmed", False),
                "independently_source_confirmed": s.get("independently_source_confirmed", False),
                "request_key": s.get("request_key"),
                "source_assessment": s.get("source_assessment", []),
            },
            "source_labels": labels,
            "native_parent_ledgers": matches[sid],
            "native_004_admitted": False,
            "funding_status": "unfunded; requires exact residual-budget replay by adaptive-judge-budget",
        }
        rank = (priority.get(p["seed_mode"], 9), p["method"] != "reciprocal_anchored", p["seed_id"])
        if accepted:
            item["frontier_kind"] = (
                "existing accepted useful pair newly retrieved versus native; validation example, not newly established truth"
            )
            if pair not in known or rank < known[pair][0]:
                known[pair] = (rank, item)
        elif p["seed_mode"] == "real_prior_judge_confirmed" and all(
            l.get("label") in {"unknown", None} for l in labels
        ):
            item["frontier_kind"] = "unverified sibling of exact prior provider observation"
            if pair not in unknown or rank < unknown[pair][0]:
                unknown[pair] = (rank, item)
    atomic(LAB / "USEFUL-FRONTIER.jsonl", [x[1] for k, x in sorted(known.items())])
    atomic(LAB / "PRIOR-SEED-UNKNOWN-FRONTIER.jsonl", [x[1] for k, x in sorted(unknown.items())])
    atomic(
        LAB / "bundle-leads.jsonl",
        (
            p
            | {
                "evidence_details": p["evidence"],
                "evidence": [f"{k}: {json.dumps(v, sort_keys=True)}" for k, v in p["evidence"].items()],
                "source_artifact_reference": p["source_artifact"],
                "funding_status": "unfunded; root scheduler owns admission",
            }
            for p in stream(LAB / "proposals.jsonl")
            if p["method"] in base.METHODS[2:]
        ),
    )
    atomic(
        LAB / "FRONTIER-RECEIPT.json",
        {
            "schema": 1,
            "known_accepted_incremental_pairs": len(known),
            "unknown_pairs_from_prior_provider_seeds": len(unknown),
            "known_useful_frontier": str(LAB / "USEFUL-FRONTIER.jsonl"),
            "prior_seed_unknown_frontier": str(LAB / "PRIOR-SEED-UNKNOWN-FRONTIER.jsonl"),
            "ledger_audit": str(LAB / "NATIVE-LEDGER-AUDIT.json"),
            "new_native_004_admitted": 0,
            "provider_calls": 0,
            "truth": "Source registry categories and prior observations preserved; no similarity score creates truth. Known useful examples need not be paid again.",
        },
    )
    handoff = json.loads((LAB / "HANDOFF.json").read_text())
    handoff.update(
        {
            "artifact_manifest": str(LAB / "ARTIFACT-MANIFEST.json"),
            "final_verification": str(LAB / "FINAL-VERIFICATION.json"),
            "reproduction": "bash " + str(LAB / "REPRODUCE.sh"),
        }
    )
    handoff.update(
        {
            "bundle_leads": str(LAB / "bundle-leads.jsonl"),
            "known_useful_frontier": str(LAB / "USEFUL-FRONTIER.jsonl"),
            "prior_seed_unknown_frontier": str(LAB / "PRIOR-SEED-UNKNOWN-FRONTIER.jsonl"),
            "native_004_ledger_audit": str(LAB / "NATIVE-LEDGER-AUDIT.json"),
            "known_accepted_incremental_pairs": len(known),
            "prior_seed_unknown_pairs": len(unknown),
            "new_native_004_admitted": 0,
            "frontier_receipt": str(LAB / "FRONTIER-RECEIPT.json"),
        }
    )
    atomic(LAB / "HANDOFF.json", handoff)
    lines = []
    for rank, p in sorted(
        known.values(), key=lambda x: (x[0], x[1]["cohort_id"], x[1]["query_position"], x[1]["target_position"])
    )[:8]:

        def loc(f):
            return f"{f['path']}:{f['line']} — {f.get('owner') + '.' if f.get('owner') else ''}{f['name']}"

        labels = ", ".join(
            sorted({l["label"] for l in p["source_labels"] if l.get("accepted_gold") and l["label"] in base.USEFUL})
        )
        lines.append(
            f"| {p['repository']} / `{p['revision'][:12]}` | {loc(p['candidate']['new'])} | {loc(p['candidate']['existing'])} | {p['seed_mode']} | {labels} |"
        )
    (LAB / "FRONTIER-SUMMARY.md").write_text(f"""# Concrete source-pinned frontier

There are **{len(known)} distinct exact-cohort accepted useful pairs** retrieved beyond current native relatives, and **{len(unknown)} distinct unverified pairs** reached from exact prior provider observations. Repeated revisions/scopes remain distinct backgrounds; these counts are not independent repository findings. Accepted useful pairs are existing registry evidence, not newly established truth. Unknown siblings remain speculative and nonblocking, including possible negatives.

[USEFUL-FRONTIER.jsonl](USEFUL-FRONTIER.jsonl) retains complete signatures, docstrings, source bodies, revision/scope hashes, seed lineage, operation evidence and original labels. The following are concrete validation examples, selected deterministically with actual prior observations first:

| Repository / revision | Operation endpoint A | Operation endpoint B | Seed evidence | Existing accepted label |
|---|---|---|---|---|
{chr(10).join(lines)}

[PRIOR-SEED-UNKNOWN-FRONTIER.jsonl](PRIOR-SEED-UNKNOWN-FRONTIER.jsonl) is the source-complete speculative review queue; [bundle-leads.jsonl](bundle-leads.jsonl) supplies all expansion scenarios for the bundle worker. Scores are uncalibrated rankings, never truth. A rejection can downweight its branch without suppressing unrelated branches.

The exact ledger audit checked {checked} native reports at a $0.04 budget and matched {sum(bool(matches[sid]) for sid in prior)} provider seed exposures to reported parents with exact source, prompt and verdict identity. **No newly appended graph lead has native $0.04 admission.** No fresh budget was assigned after the seed. The adaptive worker owns remaining-budget replay and the coordinator owns paid judging and source acceptance. See [NATIVE-LEDGER-AUDIT.json](NATIVE-LEDGER-AUDIT.json) and [FRONTIER-RECEIPT.json](FRONTIER-RECEIPT.json).
""")
    print(
        json.dumps(
            {
                "known_useful_pairs": len(known),
                "prior_seed_unknown_pairs": len(unknown),
                "matched_native_parent_seeds": sum(bool(matches[sid]) for sid in prior),
            }
        )
    )


if __name__ == "__main__":
    main()
