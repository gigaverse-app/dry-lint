"""Check the portable report's evidence joins; no models, credentials or source needed."""
import hashlib
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
final = json.loads((HERE / "final-source-decision.json").read_bytes())
for name, digest in final["frozen_metric_snapshots"].items():
    assert hashlib.sha256((HERE / name).read_bytes()).hexdigest() == digest
revised = json.loads((HERE / "revised-metrics.json").read_bytes())
assert final["decision"] == "STOP_THIS_VARIANT"
assert revised["inventory_records"] == final["dataset"]["inventory_records"] == 617
assert revised["backgrounds"] == 79
for metric, expected in [("retrieved", (80, 80, 91)), ("funded", (61, 61, 72))]:
    row = next(r for r in revised["strict_paired"] if r["label"] == "duplicate" and r["profile"] == "balanced" and r["metric"] == metric)
    assert (row["baseline"], row["variant"], row["paired_supported_contexts"]) == expected
    assert row["gains"] == row["losses"] == 0
cases = {r["id"]: r for r in final["source_cases"]}
minor = cases["CTR2-012"]
assert minor["source_label"] == "duplicate"
assert minor["utility"] == "minor_existing_helper_reuse"
assert minor["added_balanced_emission"] is True
assert minor["substantial_useful_incremental_report"] is False
negative = cases["CTR2-035"]
assert negative["source_label"] == "separate"
assert negative["original_balanced_baseline_emitted"] is True
assert negative["original_balanced_variant_emitted"] is True
assert negative["added_balanced_emission"] is False
assert cases["CTR2-028"]["family"] == cases["CTR2-033"]["family"]
assert final["discovery"]["useful_control_pairs"] == 3
assert final["discovery"]["useful_control_families"] == 2
assert final["source_review"]["benchmark_gold_changed"] is False
cost = final["costs"]
assert math.isclose(cost["round1_root_attributed_actual_new_usd"] - cost["round1_supplied_feed_actual_new_usd"], cost["round1_extra_awaiting_exact_ledger_binding_usd"], abs_tol=1e-12)
assert math.isclose(cost["round2_actual_new_usd"], .22040344, abs_tol=1e-12)
assert final["discovery"]["unstarted_novel_pairs_unknown"] == 23
assert final["discovery"]["unstarted_controls_unknown"] == 4
assert cost["cache_credit_usd"] == cost["worker_provider_calls"] == 0
manifest = HERE / "MANIFEST.json"
if manifest.exists():
    for name, item in json.loads(manifest.read_bytes())["files"].items():
        assert hashlib.sha256((HERE / name).read_bytes()).hexdigest() == item["sha256"]
print("PASS: snapshot hashes, matched denominators, scoped source labels, emission attribution, costs and unknowns")
