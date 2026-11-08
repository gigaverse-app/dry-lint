#!/usr/bin/env python3
"""Provider-free numerical transformation and aggregation of recorded cohort cells.

The half-name transformation is ported from archive/sparse/run.py.txt (Half.vector).
It accepts already normalized vectors, so it does not rebuild TF or corpus IDF.
No archive code is imported, and no private history is reconstructed.
"""

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read(name):
    return json.loads((ROOT / name).read_text())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def close(actual, expected, label):
    require(math.isclose(actual, expected, rel_tol=0, abs_tol=1e-12), label)


def half_name(vector):
    weights = {t: w * (0.5 if t.startswith("fn:") else 1) for t, w in vector.items()}
    norm = math.sqrt(sum(w * w for w in weights.values())) or 1
    return {t: w / norm for t, w in weights.items()}


def cosine(query, target):
    return sum(w * target.get(t, 0) for t, w in query.items())


def projections():
    output = []
    for row in read("inputs/weight-projections.json"):
        for side in ("query", "target"):
            require(all(math.isfinite(w) and w > 0 for w in row[side].values()), "invalid weight")
            close(sum(w * w for w in row[side].values()), 1, "input must be normalized")
        before = cosine(row["query"], row["target"])
        after = cosine(half_name(row["query"]), half_name(row["target"]))
        close(before, row["recorded_before"], "baseline score differs from original recording")
        close(after, row["recorded_after"], "half-name score differs from original recording")
        output.append(
            dict(
                example=row["example"],
                label=row["label"],
                before=round(before, 15),
                after=round(after, 15),
                passes_before=before >= row["floor"],
                passes_after=after >= row["floor"],
            )
        )
    return output


def aggregate():
    sparse = []
    for row in read("recordings/sparse.json"):
        require(row["directions"] == 2 * row["pairs"], "direction denominator")
        require(sum(row["directional_losses"].values()) == row["directions"], "first loss partition")
        require(row["protected_pairs"] - row["deployed20_pairs"] == row["additional_pairs"], "sparse delta")
        sparse.append(
            dict(
                group=row["group"],
                pairs=row["pairs"],
                before=row["deployed20_pairs"],
                after=row["protected_pairs"],
                gain=row["additional_pairs"],
            )
        )
    native = []
    for row in read("recordings/native.json"):
        native.append(
            dict(
                cohort=row["cohort"],
                prompt=row["prompt"],
                budget=row["limits"],
                arm=row["arm"],
                calls=row["calls"],
                usd=round(row["usd"], 7),
                positive=row["true"],
                denominator=7 if row["cohort"] == "historical-trial" else 11,
                separate=row["false"],
                borderline=row["borderline"],
            )
        )
    guarded = []
    for row in read("recordings/guarded.json"):
        labels = Counter()
        for label, count in row["source_bound_report_classes"].items():
            labels[label.rsplit("_", 1)[-1]] += count
        close(row["usage_cost_lower"], row["conservative_accounted_upper"], "completed cost bounds")
        require(row["censored_histories"] == 0 and row["max_PR_accounted_upper"] <= 0.04, "H02 completion/cap")
        guarded.append(
            dict(
                cohort=row["cohort"],
                arm=row["arm"],
                histories=row["histories"],
                revisions=row["commits"],
                reports=sum(labels.values()),
                labels=dict(labels),
                calls=row["source_observation_replay_calls"],
                usd=round(row["usage_cost_lower"], 7),
                reference={k: v for k, v in row["source_bound_report_classes"].items() if k.startswith("frozen_")},
                supplementary={
                    k: v for k, v in row["source_bound_report_classes"].items() if k.startswith("supplementary_")
                },
            )
        )
    deltas = []
    for row in read("recordings/guarded-deltas.json"):
        require(row["censored"] == 0, "delta censored")
        totals = {r["arm"]: r["reports"] for r in guarded if r["cohort"] == row["cohort"]}
        require(
            totals["guarded"] - totals[row["comparator"]] == sum(row["gained"].values()) - sum(row["lost"].values()),
            "paired delta accounting",
        )
        deltas.append(dict(**row, gained_total=sum(row["gained"].values()), lost_total=sum(row["lost"].values())))
    source = read("recordings/source-recovery.json")
    current = source["arms"]["current20"]
    treatment = source["arms"]["protected_half_name"]
    require(source["completed"] and source["pending"] == 0 and source["revisions"] == 8, "H05 completion")
    require(
        sum(treatment["report_labels"].values()) - sum(current["report_labels"].values())
        == source["gained_pairs"] - source["lost_pairs"],
        "H05 paired accounting",
    )
    source["incremental_arm_usage_usd"] = round(treatment["usage_usd"] - current["usage_usd"], 7)
    for arm in source["arms"].values():
        require(arm["usage_usd"] <= 0.04, "H05 cap")
    review = read("recordings/independent-review.json")
    for row in review.values():
        require(sum(row["categories"].values()) == row["report_versions"], "independent review partition")
    physical = read("recordings/guarded-physical.json")
    first_loss = dict(
        native=read("recordings/native-first-loss.json"), guarded=read("recordings/guarded-first-loss.json")
    )
    for row in first_loss["native"]:
        require(
            sum(row["positive_pair_first_stages"].values()) == (7 if row["cohort"] == "historical-trial" else 11),
            "native first-loss denominator",
        )
    return dict(
        guarded_physical=physical,
        first_loss=first_loss,
        projections=projections(),
        sparse=sparse,
        native=native,
        guarded=guarded,
        guarded_deltas=deltas,
        source_recovery=source,
        independent_review=review,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="compare computations with frozen expected outputs")
    args = parser.parse_args()
    result = aggregate()
    if args.check:
        require(result == read("expected.json"), "computed results differ from frozen expected.json")
        for item in read("archive/manifest.json"):
            actual = hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest()
            require(actual == item["published_sha256"], "archived source changed: " + item["path"])
        print(
            "PASS: 3 exact vector transformations; all sparse/native/guarded/source aggregate cells; source archive integrity."
        )
    else:
        print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
