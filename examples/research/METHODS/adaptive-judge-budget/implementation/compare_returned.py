# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: F403, F405, I001
"""Report recorded outcomes separately from logical allocation and censored native prefixes."""

from policy import *
import argparse
from collections import Counter

ap = argparse.ArgumentParser()
ap.add_argument("--run", type=Path, required=True)
a = ap.parse_args()
out = a.run.resolve()
before = {(r["cohort_id"], r["query"]): r for r in jl(HERE / "matched-captures/results.jsonl")}
after = jl(out / "results.jsonl")
arms = {}
comparisons = []


def normal_reports(x):
    return {e["key"] for e in x["normal"]["events"] if e["reported"] is True}


for arm in ["fixed", "uniform", "cost", "adaptive"]:
    counts = Counter()
    numbers = Counter()
    versions = set()
    native_versions = set()
    reasons = Counter()
    for row in after:
        key = row["cohort_id"], row["query"]
        old = before[key]["arms"][arm]
        new = row["arms"][arm]
        # Frozen policy: changes are answers/settlement, never allocation changes.
        assert [(e["key"], e["admitted"], e["charge_usd"]) for e in old["normal"]["events"]] == [
            (e["key"], e["admitted"], e["charge_usd"]) for e in new["normal"]["events"]
        ]
        counts["campaigns"] += 1
        counts["normal_funded"] += sum(e["admitted"] for e in new["normal"]["events"])
        counts["normal_unknown"] += new["normal"]["unknown_funded"]
        counts["normal_reports"] += len(normal_reports(new))
        counts["normal_new_reports_after_receipts"] += len(normal_reports(new) - normal_reports(old))
        counts["normal_lost_reports_after_receipts"] += len(normal_reports(old) - normal_reports(new))
        counts["native_complete"] += new["native"]["censored"] is None
        counts["native_censored"] += new["native"]["censored"] is not None
        counts["native_known_failure"] += bool(
            new["native"]["censored"] and new["native"]["censored"].startswith("known_paid_failure:")
        )
        counts["native_reports"] += len(new["native"]["reports"])
        counts["native_new_reports_after_receipts"] += len(
            set(new["native"]["reports"]) - set(old["native"]["reports"])
        )
        counts["native_previous_report_absent"] += len(set(old["native"]["reports"]) - set(new["native"]["reports"]))
        counts["native_settled_answer_occurrences"] += sum(
            e["settled_actual_usd"] is not None for e in new["native"]["events"]
        )
        counts["normal_exact_cache_hits"] += new["normal"]["cached_recordings"]
        counts["normal_known_failed_answers"] += sum(
            bool(e["recording"] and (not e["recording"]["verdict"] or e["recording"]["error"]))
            for e in new["normal"]["events"]
        )
        numbers["normal_estimated_usd"] += new["normal"]["estimated_usd"]
        numbers["native_settled_usd"] += new["native"]["actual_settled_usd"]
        numbers["native_unresolved_hold_usd"] += new["native"]["unresolved_hold_usd"]
        reasons.update(e["reason"] for e in new["native"]["events"] if not e["admitted"])
        for e in new["normal"]["events"]:
            if e["reported"] is True:
                versions.add(canonical(e["recording"]["identity"]))
        for e in new["native"]["recordings"]:
            if e["key"] in new["native"]["reports"] and e["recording"]:
                native_versions.add(canonical(e["recording"]["identity"]))
    arms[arm] = (
        dict(counts)
        | dict(numbers)
        | dict(
            normal_distinct_report_versions=len(versions),
            native_distinct_report_versions=len(native_versions),
            native_declines=dict(reasons),
        )
    )
for r in after:
    f = r["arms"]["fixed"]
    for arm in ["uniform", "cost", "adaptive"]:
        t = r["arms"][arm]
        observed = {
            e["key"]
            for e in t["normal"]["events"]
            if e["recording"] and e["recording"]["verdict"] and not e["recording"]["error"]
        }
        absent = set(f["native"]["reports"]) - set(t["native"]["reports"])
        comparisons.append(
            dict(
                cohort_id=r["cohort_id"],
                query=r["query"],
                arm=arm,
                normal_reports_added=sorted(normal_reports(t) - normal_reports(f)),
                normal_reports_lost=sorted(normal_reports(f) - normal_reports(t)),
                native_known_reports_added=sorted(set(t["native"]["reports"]) - set(f["native"]["reports"])),
                native_baseline_report_absent=sorted(absent),
                absent_known_negative=sorted(k for k in absent if k in observed and k not in normal_reports(t)),
                paired_native_complete=not f["native"]["censored"] and not t["native"]["censored"],
            )
        )
write(
    out / "COMPARISON.json",
    dict(
        campaigns=len(after),
        arms=arms,
        normal_allocation_unchanged=True,
        worker_physical_provider_usd=0,
        report_units="Occurrences count separately funded logical arms. Distinct versions use exact source/prompt/settings identities. New reports are not automatically useful new families.",
        native_absence="Censored-prefix absence is not confirmed report loss; explicit unknowns retained.",
        comparison_vs_fixed={
            arm: dict(
                normal_report_additions=sum(len(x["normal_reports_added"]) for x in comparisons if x["arm"] == arm),
                normal_report_losses=sum(len(x["normal_reports_lost"]) for x in comparisons if x["arm"] == arm),
                native_known_report_additions=sum(
                    len(x["native_known_reports_added"]) for x in comparisons if x["arm"] == arm
                ),
                native_baseline_report_absences=sum(
                    len(x["native_baseline_report_absent"]) for x in comparisons if x["arm"] == arm
                ),
                paired_native_complete=sum(x["paired_native_complete"] for x in comparisons if x["arm"] == arm),
            )
            for arm in ["uniform", "cost", "adaptive"]
        },
    ),
)
write(out / "paired-differences.jsonl", comparisons)
print(json.dumps(json.loads((out / "COMPARISON.json").read_text()), indent=2))
