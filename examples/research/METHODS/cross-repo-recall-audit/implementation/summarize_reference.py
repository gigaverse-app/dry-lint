# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B023, E401, E731, F401, I001
"""Paired stage-specific reference metrics. No providers, training, or held-out scores."""

import collections, json, pathlib
from inventory import HERE, BASE, jl, sha, write

CAPS = [1, 3, 4, 10, 50, 100]
METHODS = ["tfidf", "minilm", "rrf60"]


def main():
    ref = HERE / "reference"
    run = json.loads((ref / "RUN.json").read_text())
    inv = jl(HERE / "inventory-rows.jsonl")
    byid = {r["row_id"]: r for r in inv}
    dirs = []
    for receipt in run["receipts"]:
        p = ref / (receipt["cohort_id"] + ".jsonl")
        assert sha(p) == receipt["output_sha256"]
        dirs += jl(p)
    # Unique exact panel-pairs retain all label scopes/row aliases; conflicts cannot silently vote.
    groups = collections.defaultdict(list)
    for d in dirs:
        groups[(d["cohort_id"], tuple(sorted((d["query"], d["target"]))))].append(d)
    pairs = []
    for (cid, positions), rs in sorted(groups.items()):
        ids = sorted({r["row_id"] for r in rs})
        reg = [byid[i] for i in ids]
        accepted = {
            r["current_label"] for r in reg if r["accepted_gold"] and r["current_label"] in ["duplicate", "separate"]
        }
        labels = {r["current_label"] for r in reg}
        category = (
            next(iter(accepted))
            if len(accepted) == 1
            else "conflicting-accepted"
            if len(accepted) > 1
            else "useful-extraction"
            if labels & {"useful-extractable", "useful-bounded-extraction"}
            else "source-only:" + "|".join(sorted(str(x) for x in labels))
        )
        first = rs[0]
        ranks = {
            scope: {
                m: min((d[scope + "_ranks"][m] for d in rs if d[scope + "_ranks"][m] is not None), default=None)
                for m in METHODS
            }
            for scope in ["raw", "eligible"]
        }
        pairs.append(
            {
                "cohort_id": cid,
                "repository": first["repository"],
                "revision": first["revision"],
                "background_sha256": first["background_sha256"],
                "positions": positions,
                "row_ids": ids,
                "components": sorted({r["component"] for r in rs}),
                "family_identifiers": sorted({r["family_component"] for r in rs}),
                "endpoint_source_ids": sorted({r["query_source_id"] for r in rs}),
                "endpoint_bodies": sorted({r["query_body_sha256"] for r in rs}),
                "category": category,
                "original_labels": sorted(str(x) for x in labels),
                "accepted_binary": len(accepted) == 1,
                "label_scopes": sorted({str(r["label_scope"]) for r in reg}),
                "whole_function_labels": sorted({str(r["whole_function_label"]) for r in reg}),
                "same_file": first["same_file"],
                "same_language": first["same_language"],
                "size_stratum": first["size_stratum"],
                "size_ratio": first["size_ratio"],
                "sparse_score": max(r["scores"]["tfidf"] for r in rs),
                "sparse_score_stratum": first["sparse_score_stratum"],
                "raw_rank_stratum": "long_tail_over50"
                if (ranks["raw"]["tfidf"] or 10**9) > 50
                else "rank11_to50"
                if ranks["raw"]["tfidf"] > 10
                else "top10",
                "prior_ensemble_evaluated": any(r["prior_ensemble_evaluated"] for r in rs),
                "ranks": ranks,
            }
        )
    write(HERE / "reference-pairs.jsonl", pairs)

    def aggregate(ps):
        result = {
            "pair_cases": len(ps),
            "inventory_rows": len({i for p in ps for i in p["row_ids"]}),
            "components": len({c for p in ps for c in p["components"]}),
            "families": len({f for p in ps for f in p["family_identifiers"]}),
            "repositories": len({p["repository"] for p in ps}),
            "same_file_pairs": sum(p["same_file"] for p in ps),
            "raw": {},
            "eligible": {},
        }
        for scope in ["raw", "eligible"]:
            for k in CAPS:
                hit = lambda p, m: p["ranks"][scope][m] is not None and p["ranks"][scope][m] <= k
                hits = {m: [p for p in ps if hit(p, m)] for m in METHODS}
                gains = [p for p in ps if hit(p, "rrf60") and not hit(p, "tfidf")]
                losses = [p for p in ps if hit(p, "tfidf") and not hit(p, "rrf60")]
                result[scope][str(k)] = {
                    "hits": {m: len(h) for m, h in hits.items()},
                    "components_with_any_hit": {
                        m: len({c for p in h for c in p["components"]}) for m, h in hits.items()
                    },
                    "tfidf_only": sum(hit(p, "tfidf") and not hit(p, "minilm") for p in ps),
                    "minilm_only": sum(hit(p, "minilm") and not hit(p, "tfidf") for p in ps),
                    "both": sum(hit(p, "tfidf") and hit(p, "minilm") for p in ps),
                    "neither": sum(not hit(p, "tfidf") and not hit(p, "minilm") for p in ps),
                    "fusion_gains": len(gains),
                    "fusion_losses": len(losses),
                    "gained_components": len({c for p in gains for c in p["components"]}),
                    "lost_components": len({c for p in losses for c in p["components"]}),
                }
        return result

    strata = []
    for dimension in [
        "repository",
        "size_stratum",
        "sparse_score_stratum",
        "raw_rank_stratum",
        "same_file",
        "prior_ensemble_evaluated",
    ]:
        for value in sorted({str(p[dimension]) for p in pairs}):
            for category in sorted({p["category"] for p in pairs}):
                selected = [p for p in pairs if str(p[dimension]) == value and p["category"] == category]
                if selected:
                    strata.append({"dimension": dimension, "value": value, "category": category, **aggregate(selected)})
    write(HERE / "reference-strata.jsonl", strata)
    exposure_sets = collections.defaultdict(set)
    for receipt in run["receipts"]:
        for e in jl(ref / (receipt["cohort_id"] + ".exposure.jsonl")):
            for z in e["targets"]:
                exposure_sets[(e["method"], e["scope"], e["cap"])].add((e["cohort_id"], tuple(sorted((e["query"], z)))))
    categories = {k: p["category"] for k, p in zip(sorted(groups), pairs, strict=True)}
    exact_registry = collections.defaultdict(set)
    for m in jl(BASE / "mapped-gold.jsonl"):
        if m["record_kind"] != "function":
            continue
        r = byid[m["row_id"]]
        label = r["current_label"]
        category = (
            ("accepted:" + str(label))
            if r["accepted_gold"] and label in ["duplicate", "separate"]
            else "source-only:" + str(label)
        )
        exact_registry[(m["cohort_id"], tuple(sorted(m["query_positions"])))].add(category)
    exposure = [
        {
            "method": m,
            "scope": s,
            "cap": k,
            "unique_panel_pairs": len(v),
            "canonical_categories": dict(
                collections.Counter(categories.get(x, "outside_canonical_inventory") for x in v)
            ),
            "all_exact_scope_categories": dict(
                collections.Counter(
                    "|".join(sorted(exact_registry[x])) if x in exact_registry else "outside_all_exact_scope_labels"
                    for x in v
                )
            ),
        }
        for (m, s, k), v in sorted(exposure_sets.items())
    ]
    write(HERE / "reference-exposure.json", exposure)
    effective = collections.Counter(
        (r["record_kind"], r["accepted_gold"], str(r["current_label"]), bool(r["canonical_cohort"]), r["wave_role"])
        for r in inv
    )
    write(
        HERE / "effective-labels.jsonl",
        [
            {
                "record_kind": k[0],
                "accepted_gold_flag": k[1],
                "current_label": k[2],
                "mapped": k[3],
                "wave_role": k[4],
                "rows": v,
            }
            for k, v in sorted(effective.items())
        ],
    )
    represented = {d["row_id"] for d in dirs}
    expected = {
        r["row_id"]
        for r in inv
        if r["record_kind"] == "function" and r["canonical_cohort"] and r["wave_role"] == "development"
    }
    summary = {
        "title": "Full-background sparse/prefix complementarity under frozen source groups",
        "inventory_rows": len(inv),
        "model_rows_excluded": sum(r["record_kind"] == "model" for r in inv),
        "accepted_flag_rows": sum(r["accepted_gold"] for r in inv),
        "accepted_flag_null_label_rows": sum(r["accepted_gold"] and r["current_label"] is None for r in inv),
        "accepted_function_flag_rows": sum(r["accepted_gold"] and r["record_kind"] == "function" for r in inv),
        "effective_accepted_binary_function_rows": sum(
            r["accepted_gold"] and r["record_kind"] == "function" and r["current_label"] in ["duplicate", "separate"]
            for r in inv
        ),
        "function_rows_unmapped": sum(r["record_kind"] == "function" and not r["canonical_cohort"] for r in inv),
        "wave_reserved_rows": sum(r["wave_role"] == "reserved_validation" for r in inv),
        "reference_rows": len(represented),
        "expected_development_mapped_function_rows": len(expected),
        "missing_development_rows": sorted(expected - represented),
        "backgrounds": len(run["receipts"]),
        "repositories": len({d["repository"] for d in dirs}),
        "queries": sum(r["queries"] for r in run["receipts"]),
        "directional_label_rows": len(dirs),
        "unique_pair_cases": len(pairs),
        "by_category": {
            c: aggregate([p for p in pairs if p["category"] == c]) for c in sorted({p["category"] for p in pairs})
        },
        "no_holdout_scores_read": True,
        "no_new_labels": True,
        "interpretation": "Repeated scopes/revisions are pair cases, not independent examples. Components are conservative leakage groups, not proof of semantic family truth. This is unbudgeted retrieval on previously studied labeled queries, with no reports or provider spend. Whole-function and bounded-operation label scopes are retained.",
        "reference_run": str(ref / "RUN.json"),
    }
    write(HERE / "REFERENCE.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "by_category"}, indent=2))
    for c in ["duplicate", "separate", "useful-extraction"]:
        if c in summary["by_category"]:
            print(
                c,
                summary["by_category"][c]["pair_cases"],
                summary["by_category"][c]["raw"]["4"],
                summary["by_category"][c]["eligible"]["4"],
            )


if __name__ == "__main__":
    main()
