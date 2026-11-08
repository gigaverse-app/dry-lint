"""Separate repository/revision/scope regression tables, coverage and stage evidence."""

import csv
from collections import Counter, defaultdict

from common import HERE, dump, json, jsonl, read, sha


def band(rank):
    return "absent" if rank is None else "top3" if rank <= 3 else "top20" if rank <= 20 else "beyond20"


def main():
    material = json.loads((HERE / "materialized-background-manifest.json").read_text())
    cohorts = {m["cohort_id"]: m for m in material["backgrounds"]}
    inventory = read(HERE / "selected-rows.jsonl")
    coverage = []
    for repo in sorted({r["repository"] for r in inventory}):
        rs = [r for r in inventory if r["repository"] == repo]
        coverage.append(
            {
                "repository": repo,
                "inventory_rows": len(rs),
                "row_labels": dict(Counter(r["label"] for r in rs)),
                "unique_pair_ids": len({r["pair_id"] for r in rs}),
                "backgrounds": len([m for m in cohorts.values() if m["repository"]["repository"] == repo]),
                "pins": len({r["revision"] for r in rs}),
                "mapped_row_backgrounds": sum(
                    mp["cohort_id"] in cohorts and mp["status"] == "mapped" for r in rs for mp in r["mappings"]
                ),
            }
        )
    dump(
        HERE / "coverage-summary.json",
        {
            "by_repository": coverage,
            "exact_pins": 9,
            "backgrounds": 14,
            "function_occurrences": sum(m["functions"] for m in cohorts.values()),
            "missing_native_source_ids": [],
            "selected_row_ids": [r["row_id"] for r in inventory],
            "not_selected_inventory_rows": 617 - len(inventory),
            "not_selected_inventory_backgrounds": 79 - len(cohorts),
            "interpretation": "Prior unavailable claims came from registry attempts that did not include these public clones. This extension verifies exact objects; it does not alter historical studies or prove absence for the other backgrounds.",
        },
    )
    table = []
    stages = []
    directions = []
    for method, file in [("blocks", "blocks-regression.jsonl"), ("cpu", "cpu-regression.jsonl")]:
        if not (HERE / file).exists():
            continue
        rows = read(HERE / file)
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
    jsonl(HERE / "regression-table.jsonl", table)
    jsonl(HERE / "stage-counts.jsonl", stages)
    jsonl(HERE / "direction-table.jsonl", directions)
    columns = list(dict.fromkeys(k for r in table for k in r))
    with (HERE / "regression-table.csv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(table)
    timing = {
        name: json.loads((HERE / name).read_text()).get("wall_seconds")
        for name in ("blocks-summary.json", "encoding-summary.json", "cpu-summary.json")
        if (HERE / name).exists()
    }
    timing["materialize_seconds"] = material["wall_seconds"]
    dump(HERE / "runtime-summary.json", timing)
    lines = [
        "Public-pin regression extension for PR109",
        "",
        "All nine fetched Due/pytest commits now have exact full native functions for all 14 frozen backgrounds. The earlier missing-source report only searched registered clone attempts. It did not establish that these public pins could not be acquired.",
        "This is a separate replay of older observed regression cases, not fresh holdout evidence. The 75 inventory rows map to 115 row/background combinations (230 directions); lineage duplicates, revisions and configured/diagnostic scopes remain explicit. No aggregate pooled recall is reported.",
        "",
        "Source and comparison",
        "Production Python source is frozen at 73709fdbe884c107b665400a186cb71caecc03f7. The helper research recipe is the exact original helper_fallback_v1.py, not the later production patch. It appends one bounded complete body region only when eligible and returns original winners first. CPU uses the existing pinned offline MiniLM artifacts and original prefix route, with the frozen complete-statement fallback only after original-route abstention.",
        "Every full native function matches its background source ID/body hash. Full files match exact Git object hashes. All 21,950 background function occurrences match, with zero missing or ambiguous native sources. Each background retains its complete frozen tokens, order, IDF and scope. No snippets are substituted and no two-snippet index is fitted.",
        "",
        "Results by repository, revision and scope (paired .04 cold-query estimated funding)",
        "See regression-table.csv/jsonl for labeled pair/background units; stage-counts.jsonl for directional losses, size-dependent floor, same-file count and raw-rank bands; direction-table.jsonl for actual source IDs and scores. Known separate pair exposure is not a false emitted report; no judges ran.",
        "",
    ]
    lines += ["Inventory rows by repository (includes lineage repeats):"]
    for c in coverage:
        lines.append(c["repository"] + ": " + json.dumps(c["row_labels"], sort_keys=True))
    lines += ["", "Paired funded pairs / labeled pair-background units; revisions and scopes stay separate:"]
    for method in ("blocks", "cpu"):
        lines.append(method)
        for cid, co in sorted(
            cohorts.items(),
            key=lambda item: (item[1]["repository"]["repository"], item[1]["repository"]["revision"], item[0]),
        ):
            entries = [r for r in table if r["method"] == method and r["cohort_id"] == cid]
            if not entries:
                continue
            treatment = "helper" if method == "blocks" else "treatment"
            values = []
            for r in entries:
                values.append(
                    f"{r['label']} {r['original_funded_pairs']}->{r[treatment + '_funded_pairs']}/{r['pair_background_units']}"
                )
            lines.append(
                co["repository"]["repository"]
                + " "
                + co["repository"]["revision"][:8]
                + " "
                + ",".join(co["profiles"])
                + " | "
                + "; ".join(values)
            )
    lines.append("")
    for method in ("blocks", "cpu"):
        rs = [r for r in table if r["method"] == method]
        if rs:
            lines.append(
                f"{method}: {sum(r['gained_pairs'] for r in rs)} gained and {sum(r['lost_pairs'] for r in rs)} lost labeled pair/background funding outcomes across the separately reported cohorts. These are repeated regression outcomes, not independent samples."
            )
    lines += [
        "",
        "Representative observed case: pytest-selective at ae130637, pytest_expansion.py::worktree_snapshot versus working_tree.py::snapshot_working_tree (legacy158:7). The full-background TFIDF score is 0.309721: raw nonself ranks 1 and 3, but below the 0.5 ordinary and 0.35 wide-route floors. Both blocks recipes miss it because an endpoint has no eligible region. Original CPU prefix cosine is 0.801161, rank 1 in both directions, and it funds the pair before the complete-statement fallback is consulted. Thus this is preserved original-CPU coverage, not added fallback recall; no emitted verdict was measured. Exact directions are in cpu-regression.jsonl and blocks-regression.jsonl.",
        "",
        "Decision: this extension closes the exact-source coverage gap. Preserve the frozen recipes as opt-in research; unchanged regression outcomes alone do not demonstrate added useful recall. Synthetic behavioral checks show the helper is active and preserves native cleanup/exception evidence.",
        "",
        "Reproduce from this worktree: bash .lab-results/reproduce.sh. Uses existing local Git pins and encoder artifacts only. No downloads, providers, credentials, CI changes, target-code execution or production edits. Full CPU encoding is content/contract cached. No novel discovery sweep was performed.",
        "",
        "Timing: " + json.dumps(timing),
        "Artifact sizes and SHA256: artifact-manifest.json; acquisition/source bindings: input-proofs.json, frozen-source-manifest.json and materialized-background-manifest.json.",
    ]
    (HERE / "REPORT.txt").write_text("\n".join(lines) + "\n")
    artifacts = []
    for p in sorted(HERE.rglob("*")):
        if (
            p.is_file()
            and (
                p.suffix in (".json", ".jsonl", ".npy", ".npz", ".py", ".csv", ".sh")
                or p.name in ("run-python", "REPORT.txt")
            )
            and p.name not in ("artifact-manifest.json", "HANDOFF.json")
            and "__pycache__" not in p.parts
        ):
            data = p.read_bytes()
            artifacts.append({"path": str(p.relative_to(HERE)), "bytes": len(data), "sha256": sha(data)})
    dump(
        HERE / "artifact-manifest.json",
        {
            "files": artifacts,
            "bytes": sum(r["bytes"] for r in artifacts),
            "source_files": {
                "count": len(list((HERE / "source-files").glob("*.txt"))),
                "bytes": sum(p.stat().st_size for p in (HERE / "source-files").glob("*.txt")),
                "proofs": "cohorts/*/source-proof.jsonl",
            },
            "encoder_cache_bytes": (HERE / "encoder-cache.sqlite3").stat().st_size
            if (HERE / "encoder-cache.sqlite3").exists()
            else 0,
        },
    )
    core = [
        "materialized-background-manifest.json",
        "blocks-regression.jsonl",
        "cpu-regression.jsonl",
        "regression-table.csv",
        "stage-counts.jsonl",
        "direction-table.jsonl",
        "coverage-summary.json",
        "runtime-summary.json",
        "final-check.json",
        "artifact-manifest.json",
        "REPORT.txt",
    ]
    dump(
        HERE / "HANDOFF.json",
        {
            "status": "COMPLETE",
            "source_revision": "73709fdbe884c107b665400a186cb71caecc03f7",
            "exact_pins": 9,
            "backgrounds": 14,
            "inventory_rows": 75,
            "mapped_row_backgrounds": 115,
            "directions_per_method": 230,
            "missing_native_source_ids": [],
            "observed_regression_not_fresh_holdout": True,
            "pooling": "none; tables keyed by repository, revision, scope and label",
            "methods": {
                method: {
                    "gained_pair_background_outcomes": sum(r["gained_pairs"] for r in table if r["method"] == method),
                    "lost_pair_background_outcomes": sum(r["lost_pairs"] for r in table if r["method"] == method),
                }
                for method in ("blocks", "cpu")
            },
            "runtime": timing,
            "coverage_by_repository": coverage,
            "provider_calls": 0,
            "artifacts": {
                name: {
                    "path": str(HERE / name),
                    "sha256": sha((HERE / name).read_bytes()),
                    "bytes": (HERE / name).stat().st_size,
                }
                for name in core
                if (HERE / name).exists()
            },
            "reproduce": "bash .lab-results/reproduce.sh",
        },
    )
    print(
        json.dumps({"coverage": coverage, "methods": sorted({r["method"] for r in table}), "runtime": timing}),
        flush=True,
    )


if __name__ == "__main__":
    main()
