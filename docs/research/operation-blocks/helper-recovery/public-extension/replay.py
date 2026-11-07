"""Standard-library replay of recorded directional outcomes, not source/model inference."""

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent


def read(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def jsonl(path, rows):
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))


def band(rank):
    return "absent" if rank is None else "top3" if rank <= 3 else "top20" if rank <= 20 else "beyond20"


def recompute(data, output):
    output.mkdir(parents=True, exist_ok=True)
    cohorts = {c["cohort_id"]: c for c in read(data / "contexts.jsonl")}
    assert len(cohorts) == 14
    assert len({(c["repository"]["repository"], c["repository"]["revision"]) for c in cohorts.values()}) == 9
    for method in ("blocks", "cpu"):
        records = read(data / (method + "-regression.jsonl"))
        assert len(records) == 115 and all(len(r["directions"]) == 2 for r in records)
        for r in records:
            c = cohorts[r["cohort_id"]]
            assert (r["repository"], r["revision"], r["background_sha256"]) == (
                c["repository"]["repository"],
                c["repository"]["revision"],
                c["background_sha256"],
            )
            expected = {s["source_id"] for s in r["mapping"]["sources"].values()}
            assert all({d["query"], d["target"]} == expected and d["query"] != d["target"] for d in r["directions"])
    table = []
    stages = []
    directions = []
    for method, file in [("blocks", "blocks-regression.jsonl"), ("cpu", "cpu-regression.jsonl")]:
        if not (data / file).exists():
            continue
        rows = read(data / file)
        group = defaultdict(list)
        for r in rows:
            group[(r["cohort_id"], r["label"])].append(r)
        for (cid, label), rs in sorted(group.items()):
            co = cohorts[cid]
            units = {r["pair_id"]: r for r in rs}
            ds = [d for r in units.values() for d in r["directions"]]
            base = {
                "method": method,
                "cohort_id": cid,
                "repository": co["repository"]["repository"],
                "revision": co["repository"]["revision"],
                "scope_profiles": ",".join(co["profiles"]),
                "label": label,
                "lineage_rows": len(rs),
                "pair_background_units": len(units),
                "direction_units": len(ds),
            }
            if method == "blocks":

                def funded(d, a):
                    return d[a]["funded"]["paired"]

                arms = ["original", "helper"]

                def ranks(d):
                    return d["full_raw_rank_score"][0] if d["full_raw_rank_score"] else None

                def floor(d):
                    return d["baseline_floor"]

                def same(d):
                    return d["same_file"]

                def score(d):
                    return d["full_raw_rank_score"][1] if d["full_raw_rank_score"] else 0.0
            else:

                def funded(d, a):
                    return d["stages"][a]["funded"]

                arms = ["baseline3", "wide", "original", "treatment"]

                def ranks(d):
                    return d["tfidf"]["raw_nonself"]

                def floor(d):
                    return d["baseline_floor"]

                def same(d):
                    return d["samefile"]

                def score(d):
                    return d["tfidf"]["score"]

            out = dict(base)
            for arm in arms:
                out[arm + "_funded_pairs"] = sum(any(funded(d, arm) for d in r["directions"]) for r in units.values())
                stage = {
                    **base,
                    "arm": arm,
                    "funded_directions": sum(funded(d, arm) for d in ds),
                    "same_file_directions": sum(same(d) for d in ds),
                    "small_function_floor_0_3": sum(floor(d) == 0.3 for d in ds),
                    "ordinary_floor_0_5": sum(floor(d) == 0.5 for d in ds),
                    "below_applicable_tfidf_floor": sum(score(d) < floor(d) for d in ds),
                    "size_ratio_floor": None,
                    "minimum_size_filter": "none beyond frozen native extraction; TFIDF small-function floor is .3 below 6 lines, otherwise .5",
                    "raw_rank_bands": dict(Counter(band(ranks(d)) for d in ds)),
                }
                stage["first_loss"] = dict(
                    Counter(
                        d[arm]["pipeline_first_loss"]["paired"]
                        if method == "blocks"
                        else d["stages"][arm]["first_loss"]
                        for d in ds
                    )
                )
                if method == "blocks":
                    stage["region_first_loss"] = dict(Counter(d[arm]["first_loss"] for d in ds))
                stages.append(stage)
            treatment = arms[-1]
            out["gained_pairs"] = sum(
                any(funded(d, treatment) for d in r["directions"])
                and not any(funded(d, "original") for d in r["directions"])
                for r in units.values()
            )
            out["lost_pairs"] = sum(
                any(funded(d, "original") for d in r["directions"])
                and not any(funded(d, treatment) for d in r["directions"])
                for r in units.values()
            )
            table.append(out)
            for r in units.values():
                for d in r["directions"]:
                    directions.append(
                        {
                            **base,
                            "row_id": r["row_id"],
                            "pair_id": r["pair_id"],
                            "query_source_id": d["query"],
                            "target_source_id": d["target"],
                            "same_file": same(d),
                            "query_lines": d["query_lines"],
                            "tfidf_floor": floor(d),
                            "tfidf_score": score(d),
                            "raw_nonself_rank": ranks(d),
                            "funded": {a: funded(d, a) for a in arms},
                            "first_loss": {
                                a: d[a]["pipeline_first_loss"]["paired"]
                                if method == "blocks"
                                else d["stages"][a]["first_loss"]
                                for a in arms
                            },
                        }
                    )
    jsonl(output / "regression-table.jsonl", table)
    jsonl(output / "stage-counts.jsonl", stages)
    jsonl(output / "direction-table.jsonl", directions)
    columns = list(dict.fromkeys(k for r in table for k in r))
    with (output / "regression-table.csv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(table)
    floors = []
    for row in stages:
        if row["method"] != "cpu" or row["arm"] != "baseline3":
            continue
        matching = [
            d
            for d in directions
            if d["method"] == "cpu" and d["cohort_id"] == row["cohort_id"] and d["label"] == row["label"]
        ]
        floors.append(
            {
                "repository": row["repository"],
                "revision": row["revision"],
                "scope": row["scope_profiles"],
                "label": row["label"],
                "directions": row["direction_units"],
                "same_file": row["same_file_directions"],
                "small_floor_0_3": row["small_function_floor_0_3"],
                "ordinary_floor_0_5": row["ordinary_floor_0_5"],
                "below_query_floor": row["below_applicable_tfidf_floor"],
                "below_wide_floor_0_35": sum(d["tfidf_score"] < 0.35 for d in matching),
                "baseline_first_loss_same_file": row["first_loss"].get("same_file", 0),
                "baseline_first_loss_score_floor": row["first_loss"].get("score_floor", 0),
                "raw_top3": row["raw_rank_bands"].get("top3", 0),
                "raw_top20_excluding3": row["raw_rank_bands"].get("top20", 0),
                "raw_beyond20": row["raw_rank_bands"].get("beyond20", 0),
                "raw_absent": row["raw_rank_bands"].get("absent", 0),
                "baseline_funded": row["funded_directions"],
                "wide_funded": sum(d["funded"]["wide"] for d in matching),
                "original_cpu_funded": sum(d["funded"]["original"] for d in matching),
                "fallback_cpu_funded": sum(d["funded"]["treatment"] for d in matching),
            }
        )
    jsonl(output / "floor-samefile.jsonl", floors)
    with (output / "floor-samefile.csv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=list(floors[0]))
        writer.writeheader()
        writer.writerows(floors)
    return table, stages, directions, floors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=PACKAGE / "data")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.out.resolve() in (args.data.resolve(), (PACKAGE / "expected").resolve()):
        parser.error("Output must be separate from input and expected tables")
    tables = recompute(args.data, args.out)
    if args.verify:
        for name in (
            "regression-table.jsonl",
            "regression-table.csv",
            "stage-counts.jsonl",
            "direction-table.jsonl",
            "floor-samefile.jsonl",
            "floor-samefile.csv",
        ):
            assert (args.out / name).read_bytes() == (PACKAGE / "expected" / name).read_bytes(), name
    print(
        json.dumps(
            {
                "replayed_row_backgrounds_per_method": 115,
                "directions_per_method": 230,
                "table_rows": len(tables[0]),
                "stage_rows": len(tables[1]),
                "floor_rows": len(tables[3]),
                "verified": args.verify,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
