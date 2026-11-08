"""Retain exact pair overlap and declared family lineage; never alter labels."""

import json
from collections import Counter, defaultdict
from pathlib import Path

from build_index import jl, write

OUT = Path(__file__).resolve().parent
rows = jl(OUT / "rows.jsonl")
pairs = defaultdict(list)
families = defaultdict(list)
for r in rows:
    if r["pair_id"]:
        pairs[r["pair_id"]].append(r)
    if r["family_id"]:
        families[(r["repository"], r["family_id"])].append(r)
pr = []
for pid, rs in pairs.items():
    accepted = [r for r in rs if r["accepted_gold"]]
    pr.append(
        dict(
            schema=1,
            pair_id=pid,
            repository=rs[0]["repository"],
            revision=rs[0]["revision"],
            source_ids=rs[0]["canonical_source_ids"],
            row_ids=[r["row_id"] for r in rs],
            datasets=sorted({r["dataset"] for r in rs}),
            accepted_row_ids=[r["row_id"] for r in accepted],
            accepted_labels=sorted({r["label"] for r in accepted}),
            accepted_label_conflict=len({r["label"] for r in accepted}) > 1,
            declared_families=sorted({r["family_id"] for r in rs if r["family_id"]}),
            record_kinds=sorted({r["record_kind"] for r in rs}),
            qualification="Exact enclosing-source pair overlap; operation labels and contexts remain distinct. Directions and profiles are correlated.",
        )
    )
write(OUT / "pair-lineage.jsonl", pr)
fr = []
for (repo, fid), rs in sorted(families.items()):
    fr.append(
        dict(
            schema=1,
            repository=repo,
            family_id=fid,
            row_ids=[r["row_id"] for r in rs],
            pair_ids=sorted({r["pair_id"] for r in rs if r["pair_id"]}),
            revisions=sorted({r["revision"] for r in rs if r["revision"]}),
            datasets=sorted({r["dataset"] for r in rs}),
            accepted_labels=dict(Counter(r["label"] for r in rs if r["accepted_gold"])),
            qualification="Declared lineage only; shared endpoints or unknown family do not establish independent samples.",
        )
    )
write(OUT / "family-lineage.jsonl", fr)
summary = dict(
    schema=1,
    inventory_sha256=json.loads((OUT / "index-ready.json").read_text())["inventory_sha256"],
    raw_records=len(rows),
    accepted_binary_rows=sum(r["accepted_gold"] for r in rows),
    accepted_function_labels=dict(
        Counter(r["label"] for r in rows if r["accepted_gold"] and r["record_kind"] == "function")
    ),
    accepted_model_labels=dict(Counter(r["label"] for r in rows if r["accepted_gold"] and r["record_kind"] == "model")),
    unique_exact_enclosing_source_pairs=len(pr),
    accepted_exact_pair_keys=len({r["pair_id"] for r in rows if r["accepted_gold"]}),
    accepted_function_exact_pair_keys=len(
        {r["pair_id"] for r in rows if r["accepted_gold"] and r["record_kind"] == "function"}
    ),
    repeated_pair_keys=sum(len(p["row_ids"]) > 1 for p in pr),
    cross_dataset_pair_keys=sum(len(p["datasets"]) > 1 for p in pr),
    accepted_label_conflicts=[p for p in pr if p["accepted_label_conflict"]],
    declared_repository_family_keys=len(fr),
    unknown_family_rows=sum(not r["family_id"] for r in rows),
    unknown_family_accepted_rows=sum(not r["family_id"] and r["accepted_gold"] for r in rows),
    dataset_counts=[
        dict(
            dataset=d,
            rows=sum(r["dataset"] == d for r in rows),
            accepted=sum(r["dataset"] == d and r["accepted_gold"] for r in rows),
            mapped=sum(r["dataset"] == d and r["status"] == "mapped" for r in rows),
        )
        for d in sorted({r["dataset"] for r in rows})
    ],
    limits="No independent-family denominator claimed: unknown legacy family membership and operation-level contracts prevent complete family reconciliation. No holdout or significance claim. Exact pair keys do not merge conflicting scoped labels.",
)
write(OUT / "reconciliation.json", summary)
print(json.dumps(summary, indent=2))
