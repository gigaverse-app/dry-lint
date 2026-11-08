# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, I001
"""Freeze source-only splits. Never read method outcomes or provider answers."""

from _recovery_paths import recovery_path
import collections, gzip, hashlib, json, pathlib

HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path(recovery_path(""))
BASE = ROOT / "jobs/encoder-corpus-evaluation/.lab-results"


def jl(p):
    with gzip.open(p, "rt") if str(p).endswith(".gz") else open(p) as f:
        return [json.loads(x) for x in f if x.strip()]


def sha(p):
    with open(p, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def write(p, x):
    p = pathlib.Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in x)
        if p.suffix == ".jsonl"
        else json.dumps(x, sort_keys=True, indent=2) + "\n"
    )


def main():
    panels = jl(BASE / "panels.jsonl")
    gold = jl(BASE / "gold-rows.jsonl")
    maps = jl(BASE / "mapped-gold.jsonl")
    plan = json.loads((BASE / "ordered-full-background-plan.json").read_text())["plan"]
    overrides = json.loads((BASE / "baseline-matrices.json").read_text())
    prior = json.loads((ROOT / ".lab-results/encoder-ensemble/FEATURES.json").read_text())
    prior_cids = {p["cohort_id"] for p in prior["panels"]}
    reserved_repo = "anomalyco/opencode"
    forbidden = ["firecrawl", "curator"]
    assert not any(any(t in p["repository"].lower() for t in forbidden) for p in panels)
    # The full repository is excluded, including all exact-body matches elsewhere.
    held_bodies = set()
    held_endpoints = set()
    held_docs = []
    for p in panels:
        if p["repository"] == reserved_repo:
            ds = jl(p["documents_path"])
            for d in ds:
                held_bodies.add(d["source_sha256"])
                held_endpoints.add(p["repository"] + "::" + d["source_id"])
            held_docs.append(
                {
                    "cohort_id": p["cohort_id"],
                    "documents_path": p["documents_path"],
                    "sha256": sha(p["documents_path"]),
                    "functions": len(ds),
                }
            )
    byrow = collections.defaultdict(list)
    for m in maps:
        byrow[m["row_id"]].append(m)
    parents = {r["row_id"]: r["row_id"] for r in gold}

    def find(a):
        while parents[a] != a:
            parents[a] = parents[parents[a]]
            a = parents[a]
        return a

    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parents[max(a, b)] = min(a, b)

    tokens = {}
    keys = {}
    bodysets = {}
    endpointsets = {}
    for r in gold:
        rid = r["row_id"]
        bodies = set((r.get("endpoint_body_sha256") or {}).values())
        ends = set(r.get("source_ids") or [])
        for s in (r.get("sources") or {}).values():
            if s.get("snippet_sha256"):
                bodies.add(s["snippet_sha256"])
            if s.get("source_id") or s.get("id"):
                ends.add(s.get("source_id") or s["id"])
        for m in byrow[rid]:
            for e in m.get("endpoint_identities", []):
                bodies.add(e["source_sha256"])
                ends.add(e["source_id"])
        bodysets[rid] = bodies
        endpointsets[rid] = {r["repository"] + "::" + e for e in ends}
        ks = (
            {"family:" + r["family_component"]}
            | {"body:" + b for b in bodies}
            | {"endpoint:" + e for e in endpointsets[rid]}
        )
        # family_lineage explicitly marks many related domains as NON-family; do not union by vocabulary.
        keys[rid] = ks
        for k in ks:
            if k in tokens:
                union(rid, tokens[k])
            else:
                tokens[k] = rid
    components = collections.defaultdict(list)
    for r in gold:
        components[find(r["row_id"])].append(r["row_id"])
    cid_for = {
        rid: "component-" + hashlib.sha256("\n".join(sorted(rs)).encode()).hexdigest()[:16]
        for rs in components.values()
        for rid in rs
    }
    purge_components = {
        cid_for[r["row_id"]]
        for r in gold
        if r["repository"] == reserved_repo
        or bodysets[r["row_id"]] & held_bodies
        or endpointsets[r["row_id"]] & held_endpoints
    }
    chosen = {}
    for p in plan:
        for rid in p["new_rows"]:
            chosen.setdefault(rid, p["cohort_id"])
    rows = []
    for r in gold:
        rid = r["row_id"]
        held = cid_for[rid] in purge_components
        rows.append(
            {
                k: r.get(k)
                for k in [
                    "row_id",
                    "repository",
                    "revision",
                    "dataset",
                    "record_kind",
                    "current_label",
                    "original_label",
                    "accepted_gold",
                    "calibration_eligible",
                    "label_scope",
                    "whole_function_label",
                    "source_review_status",
                    "authority",
                    "coverage",
                    "family_component",
                    "family_id",
                    "split",
                ]
            }
            | {
                "component": cid_for[rid],
                "body_sha256": sorted(bodysets[rid]),
                "endpoint_identities": sorted(endpointsets[rid]),
                "mapped_cohorts": [m["cohort_id"] for m in byrow[rid]],
                "canonical_cohort": chosen.get(rid),
                "previous_ensemble_evaluated": any(m["cohort_id"] in prior_cids for m in byrow[rid]),
                "scientific_split": "previously_studied_development",
                "wave_role": "reserved_validation" if held else "development",
                "holdout_reason": "full_repository"
                if r["repository"] == reserved_repo
                else "connected_source_component"
                if held
                else None,
            }
        )
    write(HERE / "inventory-rows.jsonl", rows)
    panelrows = []
    for p in panels:
        p = p | overrides.get(p["cohort_id"], {})
        panelrows.append(
            {
                k: p[k]
                for k in [
                    "cohort_id",
                    "repository",
                    "revision",
                    "background_path",
                    "background_sha256",
                    "documents_path",
                    "functions_path",
                    "functions_sha256",
                    "scope",
                    "profiles",
                    "extraction_contract",
                    "functions",
                ]
            }
            | {
                k: p.get(k)
                for k in [
                    "minilm_matrix_path",
                    "minilm_matrix_sha256",
                    "minilm_tail_matrix_path",
                    "minilm_tail_matrix_sha256",
                    "minilm_tail_views_path",
                ]
            }
            | {
                "prior_ensemble_evaluated": p["cohort_id"] in prior_cids,
                "wave_reserved": p["repository"] == reserved_repo,
                "canonical_rows": sum(x["canonical_cohort"] == p["cohort_id"] for x in rows),
            }
        )
    write(HERE / "frozen-panels.jsonl", panelrows)
    write(
        HERE / "holdout-source-identities.json",
        {
            "repository": reserved_repo,
            "source_documents": held_docs,
            "body_sha256": sorted(held_bodies),
            "endpoint_identities": sorted(held_endpoints),
            "components": sorted(purge_components),
        },
    )
    coverage = {
        "inventory_rows": len(rows),
        "mapped_panel_rows": len(maps),
        "distinct_mapped_rows": len({m["row_id"] for m in maps}),
        "backgrounds": len(panels),
        "repositories": len({p["repository"] for p in panels}),
        "revisions": len({(p["repository"], p["revision"]) for p in panels}),
        "family_identifiers": len({r["family_component"] for r in rows}),
        "connected_components": len(components),
        "distinct_endpoint_bodies": len(set.union(*bodysets.values())),
        "labels": dict(collections.Counter(str(r["current_label"]) for r in rows)),
        "accepted_labels": dict(collections.Counter(str(r["current_label"]) for r in rows if r["accepted_gold"])),
        "missing_canonical_rows": [r["row_id"] for r in rows if r["canonical_cohort"] is None],
        "reserved_rows": sum(r["wave_role"] == "reserved_validation" for r in rows),
        "reserved_components": len(purge_components),
        "verified_untouched_labeled_families": 0,
        "previous_ensemble_backgrounds": len(prior_cids),
        "prefix_available_backgrounds": sum(bool(p.get("minilm_matrix_path")) for p in panelrows),
        "tail_available_backgrounds": sum(bool(p.get("minilm_tail_matrix_path")) for p in panelrows),
    }
    write(HERE / "COVERAGE.json", coverage)
    contract = {
        "schema": 1,
        "title": "Frozen source groups and evidence acceptance for complementary detection",
        "product_commit": "a10a288530c4aa25711c7ec3b86ac164d182899a",
        "worktree_head": "b74a6223b4b41b8bb881c445c86c2dba82d62dd2",
        "inputs": {
            n: sha(BASE / n)
            for n in [
                "panels.jsonl",
                "mapped-gold.jsonl",
                "gold-rows.jsonl",
                "ordered-full-background-plan.json",
                "baseline-matrices.json",
            ]
        },
        "inventory_rows_path": str(HERE / "inventory-rows.jsonl"),
        "inventory_rows_sha256": sha(HERE / "inventory-rows.jsonl"),
        "frozen_panels_path": str(HERE / "frozen-panels.jsonl"),
        "canonical_scope_rule": "Use first occurrence of row_id in the pre-existing ordered plan; compare same background/source order. Never refit or transfer labels across revisions/scopes. Secondary scope replays stay separate.",
        "source_groups": "Transitive union of declared family_component, exact endpoint body SHA256 globally, and repository-qualified endpoint identity across revisions. Repository itself is separate outer grouping. Related domain strings in family_lineage do not assert common family.",
        "holdout": {
            "repository": reserved_repo,
            "cohorts": [p["cohort_id"] for p in panelrows if p["wave_reserved"]],
            "identity_file": str(HERE / "holdout-source-identities.json"),
            "identity_sha256": sha(HERE / "holdout-source-identities.json"),
            "exclude_from_fitting_and_tuning": True,
            "exclude_connected_components": sorted(purge_components),
            "release": "Final validation only after recipes/allocators are frozen; coordinator releases. This reference will not read held-out method scores.",
            "interpretation": "Prospective reservation for this wave, historically studied development regression. NOT a pristine unseen test or independent replication.",
        },
        "untouched": {
            "verified_labeled_families": 0,
            "reserved_repositories": ["firecrawl", "curator"],
            "instruction": "Do not open these repositories or their results. Root will route opaque new candidate/family packets; source evidence is not training truth.",
        },
        "acceptance": {
            "primary": "At identical native changed-function groups, total budget, judge contract, and exact cache state, count independently source-confirmed newly funded actionable reports in distinct source components; subtract lost confirmed baseline reports. Report useful bounded extraction separately from whole duplication.",
            "promotion_requirement": "Positive incremental confirmed utility with zero lost confirmed baseline outcomes and no newly confirmed false emitted report in reviewed additions/controls; unknown or disputed cases cannot pass this gate. Show family/component counts and finite coverage, not population precision.",
            "diagnostic": "Candidate ranks, pair-either recall and known-negative exposure at fixed candidate counts; not emitted reports, precision or money. Fixed TFIDF/MiniLM RRF60 reference, no weight search.",
            "units": [
                "inventory rows",
                "exact panel-pairs",
                "directional queries",
                "repository/family/body components",
                "native admitted occurrences",
                "emitted reports",
                "physical spend",
                "logical reservations",
                "cache hits",
            ],
            "categories": [
                "actionable-whole-duplication",
                "useful-bounded-extraction",
                "already-shared",
                "related",
                "separate",
                "tiny-convenience",
                "disputed",
                "unknown",
            ],
            "label_authority": "accepted_gold is the existing registry flag, not independent human truth. Never promote provider confidence or this source assessment into accepted gold.",
            "unknown_policy": "Missing, unsupported, unmapped, unjudged, parse failures and dissent remain explicit. Label scope stays operation-level unless whole_function_label actually asserts otherwise.",
        },
        "blinding": {
            "new_packets": "Opaque pair ID; full Candidate functions/context, exact source/callers and before/after controls; no method names, ranks, scores, provider answers, or selected-arm roles in reviewer-facing packet.",
            "existing_disputed_case": "May review with prior_exposure=true; never call blind.",
            "review_authority": "Independent model source assessment; coordinator reconciles with paid judges and accepted labels.",
        },
        "budget_caution": "$0.04 balanced/Haiku/shared-operations shadow campaigns are counterfactual. Authenticate repository revision configuration, actual changed groups and cache history before calling historical deployment replay.",
    }
    write(HERE / "SPLIT-CONTRACT.json", contract)
    write(
        HERE / "STATUS.json",
        {
            "title": "Independent generalization and source-quality audit",
            "stage": "split frozen; reference implementation next",
            "measured_coverage": coverage,
            "next_artifact": "reference-pairs.jsonl and REFERENCE.json",
            "provider_calls": 0,
        },
    )
    print(json.dumps(coverage, indent=2))


if __name__ == "__main__":
    main()
