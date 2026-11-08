# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, E402, E741, F401, I001
"""One label-blind available pair per source component, separate from positive oracle."""

import sys

sys.dont_write_bytecode = True
import json, pathlib, collections
import run_cluster as base

if hasattr(sys.modules["__main__"], "run_one"):
    engine = sys.modules["__main__"]
    LAB, CONTRACT, atomic, sha, digest, jl = (
        getattr(engine, k) for k in ["LAB", "CONTRACT", "atomic", "sha", "digest", "jl"]
    )
else:
    from extended_run import LAB, CONTRACT, atomic, sha, digest, jl


def freeze():
    dest = LAB / "AVAILABLE-SEED-SELECTION.json"
    if dest.exists():
        return json.loads(dest.read_text())
    contract = json.loads(CONTRACT.read_text())
    allowed = {c["cohort_id"] for c in contract["cohorts"]}
    groups = {}
    for l in (base.ROOT / "jobs/cross-repo-recall-audit/.lab-results/inventory-rows.jsonl").open():
        r = json.loads(l)
        if r.get("canonical_cohort") in allowed:
            groups[r["row_id"]] = r["component"]
    selected = {}
    for c in contract["cohorts"]:
        for r in jl(base.BANK / c["cohort_id"] / "targets.jsonl"):
            if not r["canonical_evaluation"] or r["row_id"] not in groups:
                continue
            pair = sorted(r["query_positions"])
            component = groups[r["row_id"]]
            tie = digest(f"{c['cohort_id']}:{':'.join(map(str, pair))}")
            item = {
                "cohort_id": c["cohort_id"],
                "source_component": component,
                "positions": r["query_positions"],
                "row_id": r["row_id"],
                "selection_hash": tie,
            }
            if component not in selected or (tie, r["row_id"]) < (
                selected[component]["selection_hash"],
                selected[component]["row_id"],
            ):
                selected[component] = item
    x = {
        "schema": 1,
        "selection": "One canonical mapped pair per audit source component, min SHA256(cohort_id:sorted endpoint positions), row_id tie break. Label values, graph scores, and answers not used in selection. No replacement if unavailable or negative.",
        "trigger": "Reveal only selected source label. Accepted useful labels trigger retrospective baseline-lane expansion; all others abstain. This is not an actual prior provider observation or true historical availability.",
        "source_components": len(selected),
        "rows": sorted(selected.values(), key=lambda x: (x["cohort_id"], x["source_component"])),
    }
    atomic(dest, x)
    return x


def run_for_graph(g, out, original_targets):
    selected = [r for r in freeze()["rows"] if r["cohort_id"] == g.cid]
    rows = original_targets(g)
    by_id = {r["row_id"]: r for r in rows}
    available = []
    catalog = []
    for selection in selected:
        r = by_id[selection["row_id"]]
        a, b = r["query_positions"]
        trigger = bool(r["accepted_gold"] and r["current_label"] in base.USEFUL and g.eligible(a, b))
        catalog.append(
            selection
            | {
                "selected_label": r["current_label"],
                "accepted_gold": r["accepted_gold"],
                "triggered": trigger,
                "reason": "accepted useful one-pair reveal"
                if trigger
                else "negative/unknown/unaccepted or structurally unavailable; no substitute seed",
                "source": g.p,
                "label_scope": r["label_scope"],
            }
        )
        if trigger:
            available.append(
                {
                    "seed_mode": "one_available_source_seed_replay",
                    "positions": [a, b],
                    "lane": "baseline",
                    "row_id": r["row_id"],
                    "provider_confirmed": False,
                    "independently_source_confirmed": True,
                    "historical_report_emission_verified": False,
                    "reporting_basis": "selected single source label only; hypothetical baseline parent; not actual historical seed",
                    "selection_hash": selection["selection_hash"],
                }
            )
    dest = out / "available"
    dest.mkdir(parents=True, exist_ok=True)
    atomic(dest / "SELECTION-OUTCOMES.jsonl", catalog)
    if not available:
        atomic(
            dest / "COMPLETE.json",
            {"selected": len(selected), "triggered": 0, "source_components": [s["source_component"] for s in selected]},
        )
        return
    # Same frozen evaluator/methods and full post-generation label join. Disable
    # its positive-oracle and all-negative seed selection for this separate arm.
    original_here = base.HERE
    original_loader = base.load_recorded_seeds
    original_graph = base.Graph
    original_get = base.targets
    try:
        base.HERE = dest
        base.Graph = lambda cid: g
        base.targets = lambda graph: [r | {"canonical_evaluation": False} for r in rows]
        base.load_recorded_seeds = lambda graph: (available, {"one_available_labels_revealed": len(selected)})
        from argparse import Namespace

        base.run(Namespace(stage="extended", max_cohorts=None))
        by_seed = collections.defaultdict(lambda: collections.defaultdict(set))
        checked = 0
        with (dest / "proposals.jsonl").open() as f:
            for line in f:
                p = json.loads(line)
                q, t = p["query_position"], p["target_position"]
                assert p["source_body_sha256"] == [digest(g.fs[q].code), digest(g.fs[t].code)]
                assert (
                    p["candidate"]["new"]["code"] == g.fs[q].code and p["candidate"]["existing"]["code"] == g.fs[t].code
                )
                assert not p["reported"] and not p["blocking"]
                by_seed[p["seed_id"]][p["method"]].add(tuple(sorted((q, t))))
                checked += 1
        for exposure in jl(dest / "seed-exposures.jsonl"):
            a, b = exposure["positions"]
            parent = g.det.pair(g.fs[a], g.fs[b], g.det.comparer.similarity(g.fs[a], g.fs[b]))
            native = {
                tuple(sorted((g.pos[c.new.qualname], g.pos[c.existing.qualname])))
                for c in g.det.relatives([g.fs[a]], [parent])
            }
            assert native == by_seed[exposure["seed_id"]]["current_relatives_native"]
            assert all(native <= by_seed[exposure["seed_id"]][m] for m in base.METHODS[2:])
        atomic(
            dest / "COMPLETE.json",
            {
                "selected": len(selected),
                "triggered": len(available),
                "source_components": [s["source_component"] for s in selected],
                "metrics_sha256": sha(dest / "metrics.jsonl"),
                "verified_proposals": checked,
                "verified_native_baselines": len(available),
                "helper_sha256": sha(__file__),
                "outputs": {
                    name: sha(dest / name)
                    for name in [
                        "seed-exposures.jsonl",
                        "proposals.jsonl",
                        "outcomes.jsonl",
                        "metrics.jsonl",
                        "frontier-handoff.jsonl",
                    ]
                },
            },
        )
    finally:
        base.HERE = original_here
        base.load_recorded_seeds = original_loader
        base.Graph = original_graph
        base.targets = original_get


if __name__ == "__main__":
    print("frozen available components", freeze()["source_components"])
