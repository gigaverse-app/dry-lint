# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, E402, F401, I001
"""Thin adapter over the completed adaptive-budget exact recording/replay plumbing."""

from _recovery_paths import recovery_path
import os, sys, pathlib, json, collections, time, resource, subprocess

os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
sys.dont_write_bytecode = True
H = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path(recovery_path(""))
A = ROOT / "jobs/adaptive-judge-budget/.lab-results"
sys.path.insert(0, str(A))
import replay_captures as R
from dry_lint.report import Finding  # native model location; no independent replay engine

TARGETS = ["BG-32b6ecfac66de380d0f5", "BG-af54ddaad7ff80896700", "BG-e76098b4a54bcfe5a1b5"]


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="paired-replay-r1")
    ap.add_argument("--all-nominations", action="store_true")
    ap.add_argument("--observations", type=pathlib.Path, action="append", default=[])
    args = ap.parse_args()
    out = H / args.out
    out.mkdir(exist_ok=False)
    targets = (
        json.loads((H / "diagnostic-single-question/FROZEN-SELECTION.json").read_text())["selected_ids"]
        if args.all_nominations
        else TARGETS
    )
    start = time.monotonic()
    cpu = time.process_time()
    cache = R.recordings(args.observations)
    snap = []
    for rs in cache.values():
        for path, row in rs:
            snap.append(
                {
                    "path": str(path),
                    "sha256": R.sha(path),
                    "request_key": row["request_key"],
                    "question_equivalence": row.get("question_equivalence"),
                    "source_physical_request_key": row.get("question_equivalence", {}).get(
                        "source_physical_request_key", row.get("source_physical_request_key", row["request_key"])
                    ),
                }
            )
    R.write(out / "OBSERVATIONS.json", {"observations": snap})
    inputs = {
        "banks": {},
        "machinery": {"path": str(A / "replay_captures.py"), "sha256": R.sha(A / "replay_captures.py")},
        "source_campaigns": [],
        "question_equivalence_contract": {
            "path": str(ROOT / "reports/utility-recovery/QUESTION-EQUIVALENCE-CONTRACT.md"),
            "sha256": R.sha(ROOT / "reports/utility-recovery/QUESTION-EQUIVALENCE-CONTRACT.md"),
        },
        "extra_observation_directories": [str(p) for p in args.observations],
    }
    results = []
    packets = []
    mismatches = []
    for target in targets:
        original = H / "batch-v1/native" / target / "campaigns.jsonl"
        camp = R.jl(original)[0]
        cid = camp["cohort_id"]
        q = camp["query_positions"][0]
        receipt = json.loads(
            (ROOT / "jobs/complementary-signal-learning/.lab-results/bank" / cid / "RECEIPT.json").read_text()
        )
        p = receipt["source"]
        inputs["banks"][cid] = receipt
        inputs["source_campaigns"].append({"id": target, "path": str(original), "sha256": R.sha(original)})
        proofs = {(r["id"], r["source_sha256"]): r for r in R.jl(p["source_proof_path"])}
        for arm in ["raw_tfidf", "deep_raw", "lower_floor_raw", "recovery"]:
            # Compound transport key separates profiles; source query remains exactly q.
            transport_query = f"{q}-{arm}"
            folder = out / cid / transport_query / "fixed"
            raw = camp["arms"][arm]
            cs = [R.Candidate.model_validate(c) for c in raw]
            before = camp["native"][arm]
            s = R.Settings.model_validate(before["settings"])
            run = R.Run.model_validate(before["run"])
            signals = R.features(cs)
            R.write(
                folder.parent / "candidates.json",
                {
                    "current": raw,
                    "extra": [],
                    "signals": signals,
                    "source_query_position": q,
                    "original_arm": arm,
                    "original_candidate_order_sha256": R.canonical(raw),
                },
            )
            normal = R.normal(cs, signals, s, run, folder, "fixed", p, cache)
            native = R.native_replay(cs, signals, s, run, folder, "fixed", p, cache)
            record = {
                "id": target,
                "cohort_id": cid,
                "query": transport_query,
                "source_query_position": q,
                "original_arm": arm,
                "original_campaign": str(original),
                "arms": {"fixed": {"normal": normal, "native": native}},
            }
            results.append(record)
            key = native["censored"]
            judge = R.RecordedJudge(p, cache, s)
            # Audit same oriented prompt observations without accepting identity mismatches.
            for c in cs:
                if c.filtered or c.lane == "relative":
                    continue
                exact = judge.lookup(c)
                if exact:
                    continue
                prompt = R.JUDGE.input_text(c)
                for entries in cache.values():
                    for path, obs in entries:
                        ident = obs["identity"]
                        if (
                            ident.get("repository") == p["repository"]
                            and ident.get("revision") == p["revision"]
                            and ident.get("rendered_input") == prompt
                        ):
                            mismatches.append(
                                {
                                    "id": target,
                                    "arm": arm,
                                    "key": c.key,
                                    "existing_request_key": obs["request_key"],
                                    "observation_path": str(path),
                                    "candidate_sha256_expected": R.canonical(c.model_dump(mode="json")),
                                    "candidate_sha256_recorded": ident.get("candidate_sha256"),
                                    "source_evidence_expected": R.evidence(c),
                                    "source_evidence_recorded": ident.get("source_evidence"),
                                    "context_hash_matches": ident.get("context_hash") == c.context_hash,
                                    "prompt_exact": True,
                                    "reused": False,
                                    "reason": "Strict canonical identity lookup failed; same prompt is not sufficient under OBSERVATION-CONTRACT.",
                                }
                            )
            if key and not key.startswith("known_paid_failure:"):
                c = next(c for c in cs if c.key == key)
                event = next(e for e in native["events"] if e["key"] == key and e["admitted"])
                normalfunded = any(e["key"] == key and e["admitted"] for e in normal["events"])
                if normalfunded:
                    packets.append(
                        {
                            "id": "AB-" + R.canonical(c.model_dump(mode="json"))[:20],
                            "cohort_id": cid,
                            "query": transport_query,
                            "source_query_position": q,
                            "arm": "fixed",
                            "original_arm": arm,
                            "repository": p["repository"],
                            "revision": p["revision"],
                            "candidate": c.model_dump(mode="json"),
                            "source_proofs": [proofs[f.qualname, R.digest(f.code)] for f in [c.new, c.existing]],
                            "background_proof": {"path": p["background_path"], "sha256": p["background_sha256"]},
                            "settings": s.model_dump(mode="json"),
                            "run": run.model_dump(mode="json"),
                            "rendered_prompt": R.JUDGE.input_text(c),
                            "prompt_sha256": R.digest(R.JUDGE.input_text(c)),
                            "funding": {
                                "event": event,
                                "actually_reserved": True,
                                "database": native["database"],
                                "database_sha256": R.sha(native["database"]),
                            },
                            "novel_vs_current": arm == "recovery",
                            "normal_estimated_funded": True,
                            "transport_role": "candidate" if arm == "recovery" else "control",
                            "anchor_role": "actual first-missing original campaign question; not new algorithmic proposal",
                        }
                    )
            print(
                target,
                arm,
                "known",
                len([r for r in native["recordings"] if r["recording"]]),
                "missing",
                key,
                "reports",
                len(native["reports"]),
                flush=True,
            )
            R.write(out / "results.jsonl", results)
            R.write(out / "frontier-all-arms.jsonl", packets)
            R.write(out / "identity-mismatches.jsonl", mismatches)
    selected = {}
    for p in sorted(packets, key=lambda p: (p["transport_role"] != "candidate", p["id"])):
        selected.setdefault(p["id"], p)
    R.write(out / "frontier.jsonl", list(selected.values()))
    R.write(out / "INPUTS.json", inputs)
    R.write(out / "deltas.jsonl", [])
    R.write(
        out / "SUMMARY.json",
        {
            "original_campaigns": len(targets),
            "arms": len(results),
            "frontier_questions": len(selected),
            "completed_native_arms": sum(not r["arms"]["fixed"]["native"]["censored"] for r in results),
            "wall_seconds": time.monotonic() - start,
            "cpu_seconds": time.process_time() - cpu,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "provider_calls": 0,
            "strict_identity_mismatches": len(mismatches),
            "family_gain": "unknown pending complete reports and independent family reconciliation",
            "policy": "fixed native order with original Candidate arrays unchanged; existing replay/normal accounting reused",
        },
    )
    print("FRONTIER", len(selected), str(out / "frontier.jsonl"), flush=True)


if __name__ == "__main__":
    main()
