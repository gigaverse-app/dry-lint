# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, E741, F401, F841, I001
"""Summarize complete-corpus ranks, keeping embargoed outcomes unread."""

import pathlib, json, collections, hashlib

HERE = pathlib.Path(__file__).resolve().parent


def jl(p):
    with pathlib.Path(p).open() as f:
        return [json.loads(l) for l in f if l.strip()]


def write(p, d):
    p = pathlib.Path(p)
    p.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in d)
        if p.suffix == ".jsonl"
        else json.dumps(d, indent=2, sort_keys=True) + "\n"
    )


def main():
    manifest = json.loads((HERE / "BANK-MANIFEST.json").read_text())
    contract = json.loads((HERE / "SPLIT-CONTRACT.json").read_text())
    held = contract["holdout"]["repository"]
    inventory = {r["row_id"]: r for r in jl(contract["inventory_rows_path"])}
    outcomes = []
    cases = {}
    aliases = []
    coverage = []
    for p in manifest["backgrounds"]:
        coverage.append(
            {
                k: p[k]
                for k in [
                    "cohort_id",
                    "repository",
                    "revision",
                    "functions",
                    "queries",
                    "candidate_rows",
                    "seconds",
                    "setup_seconds",
                    "bank_bytes",
                    "minilm",
                    "tail",
                ]
            }
        )
        if p["repository"] == held:
            continue
        for r in jl(HERE / "bank" / p["cohort_id"] / "target-ranks.jsonl"):
            if not r["canonical_evaluation"]:
                continue
            meta = inventory[r["row_id"]]
            key = (p["cohort_id"], r["pair_identity"], r["label"], r["accepted_gold"])
            if key not in cases:
                cases[key] = {
                    "cohort_id": p["cohort_id"],
                    "repository": p["repository"],
                    "revision": p["revision"],
                    "pair_identity": r["pair_identity"],
                    "row_ids": set(),
                    "label": r["label"],
                    "accepted_gold": r["accepted_gold"],
                    "calibration_eligible": r["calibration_eligible"],
                    "family_component": r["family_component"],
                    "source_component": meta["component"],
                    "query_positions": r["query_positions"],
                    "same_file": r["same_file"],
                    "same_language": r["same_language"],
                    "native_eligible": r["native_eligible"],
                    "in_bank": False,
                    "ranks": {},
                    "cross_ranks": {},
                }
            c = cases[key]
            c["row_ids"].add(r["row_id"])
            c["in_bank"] |= r["in_bank"]
            for field in ["ranks", "cross_ranks"]:
                for arm, val in r[field].items():
                    if val is not None:
                        c[field][arm] = min(val, c[field].get(arm, val))
    for c in cases.values():
        c["row_ids"] = sorted(c["row_ids"])
        outcomes.append(c)
    metrics = []
    failures = []
    for scope, field in [("raw", "ranks"), ("cross_file", "cross_ranks")]:
        scoped = [c for c in outcomes if scope == "raw" or (not c["same_file"] and c["same_language"])]
        for repo in ["ALL_DEVELOPMENT", *sorted({c["repository"] for c in scoped})]:
            cs = [c for c in scoped if repo == "ALL_DEVELOPMENT" or c["repository"] == repo]
            groups = collections.defaultdict(list)
            for c in cs:
                groups[(str(c["label"]), c["accepted_gold"])].append(c)
            for (label, accepted), rs in groups.items():
                for cap in [4, 20]:
                    baseline = [r for r in rs if r[field].get("tfidf", 10**9) <= cap]
                    bk = {(r["cohort_id"], r["pair_identity"]) for r in baseline}
                    base_components = {r["source_component"] for r in baseline}
                    for arm in ["tfidf", "fixed_fusion", "conditional"]:
                        hit = [r for r in rs if r[field].get(arm, 10**9) <= cap]
                        hk = {(r["cohort_id"], r["pair_identity"]) for r in hit}
                        hc = {r["source_component"] for r in hit}
                        metrics.append(
                            {
                                "scope": scope,
                                "repository": repo,
                                "label": label,
                                "accepted_gold": accepted,
                                "cap": cap,
                                "arm": arm,
                                "cases": len(rs),
                                "hits": len(hit),
                                "components": len({r["source_component"] for r in rs}),
                                "hit_components": len(hc),
                                "added_pairs": len(hk - bk),
                                "lost_pairs": len(bk - hk),
                                "newly_covered_components": len(hc - base_components),
                                "lost_components": len(base_components - hc),
                            }
                        )
        for c in scoped:
            if (
                c["label"] in ["duplicate", "useful-extractable", "useful-bounded-extraction"]
                and c[field].get("tfidf", 10**9) > 4
            ):
                failures.append(
                    c
                    | {
                        "scope": scope,
                        "first_loss": "same_file_policy"
                        if scope == "raw" and c["same_file"]
                        else "native_source_unavailable"
                        if not c["native_eligible"]
                        else "rank_below4",
                        "fusion_recovered_at4": c[field].get("fixed_fusion", 10**9) <= 4,
                        "conditional_recovered_at4": c[field].get("conditional", 10**9) <= 4,
                    }
                )
    write(HERE / "outcomes.jsonl", outcomes)
    write(HERE / "known-misses.jsonl", failures)
    write(HERE / "retrieval-metrics.jsonl", metrics)
    write(HERE / "coverage.jsonl", coverage)
    report = {
        "complete": manifest["complete"],
        "backgrounds": len(coverage),
        "repositories": len({p["repository"] for p in coverage}),
        "functions_across_backgrounds": sum(p["functions"] for p in coverage),
        "queries": sum(p["queries"] for p in coverage),
        "bank_rows": sum(p["candidate_rows"] for p in coverage),
        "bank_bytes_shards": sum(p["bank_bytes"] for p in coverage),
        "build_seconds_sum": sum(p["seconds"] for p in coverage),
        "heldout_outcomes_not_read": held,
        "development_pair_cases": len(outcomes),
        "known_miss_records": len(failures),
        "metrics": [m for m in metrics if m["repository"] == "ALL_DEVELOPMENT"],
        "limits": [
            "Ranks and labeled-control exposure are not provider reports, money or population precision.",
            "Function totals include repeated revisions/scopes, not unique functions.",
            "Utility/source-assessment rows remain separate from accepted gold.",
            "No full58current-stack funding claim; native captures are a separate matched cohort.",
        ],
    }
    write(HERE / "RETRIEVAL-RESULTS.json", report)
    print(json.dumps({k: v for k, v in report.items() if k != "metrics"}, indent=2))
    for m in report["metrics"]:
        if m["scope"] == "raw" and m["cap"] == 4 and m["label"] == "duplicate" and m["accepted_gold"]:
            print(m)


if __name__ == "__main__":
    main()
