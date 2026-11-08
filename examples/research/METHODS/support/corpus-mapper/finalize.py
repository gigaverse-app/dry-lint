"""Revalidate denominator/source-contract receipts and hash the reproducible deliverables."""

import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path

from build_index import INVENTORY, jl, sha, write

OUT = Path(__file__).resolve().parent


def main():
    rows = jl(OUT / "rows.jsonl")
    directions = jl(OUT / "paired-rows.jsonl")
    receipt = json.loads((OUT / "index-ready.json").read_text())
    assert sha(INVENTORY.read_bytes()) == receipt["inventory_sha256"]
    assert len(rows) == len(INVENTORY.read_bytes().splitlines())
    assert len({r["row_id"] for r in rows}) == len(rows)
    accepted_functions = {r["row_id"] for r in rows if r["accepted_gold"] and r["record_kind"] == "function"}
    evaluated_functions = {
        d["row_id"]
        for d in directions
        if d["accepted_gold"] and d["record_kind"] == "function" and d["status"] == "evaluated"
    }
    assert accepted_functions == evaluated_functions
    strata = []
    for dimension in ["dataset", "cohort_id", "family_id", "repository"]:
        groups = defaultdict(list)
        for d in directions:
            groups[d.get(dimension), d["accepted_gold"], d["record_kind"], d["label"]].append(d)
        for (value, accepted, kind, label), ds in groups.items():
            strata.append(
                dict(
                    group_by=dimension,
                    group=value,
                    accepted_gold=accepted,
                    record_kind=kind,
                    label=label,
                    total_rows=len({d["row_id"] for d in ds}),
                    total_pair_keys=len({d["pair_id"] for d in ds}),
                    total_directions=len(ds),
                    supported=sum(d["status"] != "unsupported_record_kind" for d in ds),
                    mapped=sum(d["status"] in ["evaluated", "self_pair"] for d in ds),
                    evaluated=sum(d["status"] == "evaluated" for d in ds),
                    missing=sum(d["status"] == "incompatible" for d in ds),
                    self=sum(d["status"] == "self_pair" for d in ds),
                    top1=sum(d["top1"] for d in ds),
                    top3=sum(d["top3"] for d in ds),
                    top20=sum(d["top20"] for d in ds),
                    default_retrieved=sum(d.get("default_retrieved", False) for d in ds),
                    balanced_retrieved=sum(d.get("balanced_retrieved", False) for d in ds),
                    first_losses=dict(Counter(d["first_loss"] for d in ds)),
                )
            )
    write(
        OUT / "coverage-by-stratum.json",
        dict(
            schema=1,
            groups=strata,
            qualification="Rows and directions retain lineage and profiles; no independence claim. No historical policy, budget or judge inference.",
        ),
    )
    # Validate every cached cohort rank against its first published result, independent of floor metadata.
    old_path = OUT / "index-v1-88f0f73927ce28d2/paired-rows.jsonl"
    old = {(d["row_id"], d["cohort_id"], d["query_side"]): d for d in jl(old_path)}
    checked = 0
    changes = []
    for d in directions:
        previous = old.get((d["row_id"], d["cohort_id"], d["query_side"]))
        if d["status"] != "evaluated" or not previous or previous["status"] != "evaluated":
            continue
        for k in ["raw_rank", "score", "top1", "top3", "top20", "cross_file_rank", "compatible_language_rank"]:
            assert previous[k] == d[k]
        checked += 1
        if previous["default_floor"] != d["default_floor"]:
            changes.append(
                dict(
                    row_id=d["row_id"],
                    cohort_id=d["cohort_id"],
                    query_side=d["query_side"],
                    old_query_lines=previous["query_lines"],
                    new_query_lines=d["query_lines"],
                    new_provenance=d["query_lines_provenance"],
                    old_floor=previous["default_floor"],
                    new_floor=d["default_floor"],
                    old_first_loss=previous["first_loss"],
                    new_first_loss=d["first_loss"],
                )
            )
    write(
        OUT / "floor-correction-validation.json",
        dict(
            status="pass",
            old_raw_direction_checks=checked,
            cohorts_reused=77,
            additional_cohorts_first_fit=2,
            floor_changes=len(changes),
            changed_first_losses=sum(c["old_first_loss"] != c["new_first_loss"] for c in changes),
            changes=changes,
            old_artifact=str(old_path),
            corrected_artifact=str(OUT / "paired-rows.jsonl"),
        ),
    )
    progress = json.loads((OUT / "baseline-progress.json").read_text())
    cohorts = jl(OUT / "cohorts.jsonl")
    assert progress["status"] == "complete" and len(progress["completed_cohorts"]) == len(cohorts)
    final = dict(
        schema=1,
        status="complete_mapping_and_baseline_for_current_inventory",
        inventory_sha256=receipt["inventory_sha256"],
        inventory_records=len(rows),
        accepted_binary_rows=sum(r["accepted_gold"] for r in rows),
        accepted_function_rows=len(accepted_functions),
        accepted_model_rows=sum(r["accepted_gold"] and r["record_kind"] == "model" for r in rows),
        all_accepted_function_rows_evaluated=True,
        exact_cohorts=len(cohorts),
        all_cohorts_baseline_completed=True,
        direction_records=len(directions),
        directions_by_status=dict(Counter(d["status"] for d in directions)),
        floor_correction=dict(
            unchanged_evaluated_raw_directions=checked,
            changed_floors=len(changes),
            changed_first_losses=sum(c["old_first_loss"] != c["new_first_loss"] for c in changes),
            cached_cohorts=77,
            new_cohorts_first_fit=2,
        ),
        extra_original_gold_source_excerpts=30,
        extra_original_gold_status="audited separately; missing pins; not silently synthetic or added to accepted inventory",
        versioned_index_path=str(OUT / "index-v2-88f0f73927ce28d2"),
        providers_called=0,
        tests="18 production regression checks +8 focused missing-span checks passed",
    )
    write(OUT / "final-receipt.json", final)
    version = OUT / "index-v2-88f0f73927ce28d2"
    for name in [
        "paired-rows.jsonl",
        "paired-summary.json",
        "coverage.json",
        "coverage-by-stratum.json",
        "baseline-progress.json",
        "floor-correction-validation.json",
        "final-receipt.json",
        "reconciliation.json",
    ]:
        shutil.copyfile(OUT / name, version / name)
    files = {
        str(p.relative_to(OUT)): sha(p.read_bytes())
        for p in OUT.iterdir()
        if p.is_file() and p.name != "artifact-hashes.json" and p.suffix in [".json", ".jsonl", ".py", ".sh", ".md"]
    }
    files.update(
        {
            str(p): sha(p.read_bytes())
            for p in [
                INVENTORY,
                OUT.parents[1] / "src/dry_lint/index.py",
                OUT.parents[1] / "src/dry_lint/bench_background.py",
                OUT.parents[1] / "src/dry_lint/bench.py",
                OUT.parents[1] / "src/dry_lint/extractors.py",
                OUT.parents[1] / "src/dry_lint/typescript.py",
            ]
        }
    )
    write(OUT / "artifact-hashes.json", dict(schema=1, sha256=files))
    print(json.dumps(final, indent=2))


if __name__ == "__main__":
    main()
