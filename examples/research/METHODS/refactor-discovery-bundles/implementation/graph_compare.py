# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B905, E741, F401, F403, F405, I001
"""Read-only graph-worker handoff adapter, exact input snapshots and bounded comparison."""

from bundles import *
from run_study import load_cohort, read_jsonl, write, choose, make_lead, HERE

GRAPH = ROOT / "jobs/confirmed-cluster-expansion/.lab-results"


def main():
    # Deterministic first published source-gold baseline seed, no outcome selection.
    frozen = (HERE / "graph-inputs/seed.json").exists()
    if frozen:
        e = json.loads((HERE / "graph-inputs/seed.json").read_text())
    else:
        exposures = read_jsonl(GRAPH / "seed-exposures.jsonl")
        e = next(e for e in exposures if e["seed_mode"] == "source_gold_oracle_replay" and e["lane"] == "baseline")
    source, fs, det = load_cohort(e["cohort_id"])
    c = Candidate.model_validate(e["seed_candidate"])
    row = next(r for r in read_jsonl(BASE / "gold-rows.jsonl") if r["row_id"] == e["row_id"])
    review = Review(
        authority=row["authority"],
        artifact=str(BASE / "gold-rows.jsonl"),
        artifact_sha256=sha(BASE / "gold-rows.jsonl"),
        row_id=row["row_id"],
        category="duplicate-scope-unspecified",
        scope="operation" if "operation" in str(e.get("label_scope")) else "unspecified",
        evidence="Existing registry positive, oracle replay. Original scope: "
        + str(e.get("label_scope"))
        + ". Inspected spans are full functions, not a claim that all operations are duplicates.",
        inspected=[Boundary.of(f) for f in (c.new, c.existing)],
    )
    seed = Seed(candidate=c, source=source, review=review, mode="source_gold_oracle_replay")
    proposals = (
        json.loads((HERE / "graph-inputs/proposals.json").read_text())
        if frozen
        else [r for r in read_jsonl(GRAPH / "proposals.jsonl") if r["seed_id"] == e["seed_id"]]
    )
    # Snapshot the selected input itself; sibling files can continue growing.
    write("graph-inputs/seed.json", e)
    write("graph-inputs/proposals.json", proposals)
    prop_path = HERE / "graph-inputs/proposals.json"
    prop_sha = sha(prop_path)
    grouped = {}
    rejected = []
    for p in proposals:
        assert p["repository"] == source.repository and p["revision"] == source.revision and p["scope"] == source.scope
        assert p["functions_sha256"] == source.functions_sha256 and p["background_sha256"] == source.background_sha256
        candidate = Candidate.model_validate(p["candidate"])
        assert p["source_body_sha256"] == [digest(f.code) for f in (candidate.new, candidate.existing)]
        path = p["path"]
        es = []
        for a, b in zip(path, path[1:]):
            es.append(
                Edge(
                    left=a,
                    right=b,
                    kind="graph-worker",
                    artifact=str(prop_path) + "#" + p["proposal_id"],
                    artifact_sha256=prop_sha,
                    evidence=json.dumps(
                        {"edge_ids": p["edge_ids"], "retrieval_evidence": p["evidence"]}, sort_keys=True
                    ),
                )
            )
        try:
            lead = Lead(
                candidate=candidate,
                source=source,
                boundaries=[Boundary.of(f) for f in (candidate.new, candidate.existing)],
                path=path,
                edges=es,
                relation_mode="anchor-proposal",
                direct_pair_evidence=json.dumps(p["operation_identity"], sort_keys=True),
                uncertainty="Graph-worker navigation proposal, never transitive duplicate proof. Direct operation regions/tokens are retrieval evidence, not reviewed equivalent boundaries. Confidence is unavailable; ranking score is not probability.",
            )
            grouped.setdefault(p["method"], []).append(lead)
        except ValueError as err:
            rejected.append({"proposal_id": p["proposal_id"], "reason": str(err)})
    bundles = []
    for method in (
        "current_relatives_native",
        "unseeded_changed_endpoint",
        "reciprocal_anchored",
        "bounded_seed_diffusion",
    ):
        bundle = choose(seed, grouped.get(method, []), "graph-" + method)
        validate_source(bundle, fs, source)
        bundles.append(bundle)
    pool = [
        l
        for method in ("current_relatives_native", "reciprocal_anchored", "bounded_seed_diffusion")
        for l in grouped.get(method, [])
    ]
    bundles.append(choose(seed, pool, "diverse-bundle"))
    # Independent source outcome join occurs only after all five selections are fixed.
    selected_outcomes = (
        json.loads((HERE / "graph-inputs/outcomes.json").read_text())
        if frozen
        else [r for r in read_jsonl(GRAPH / "outcomes.jsonl") if r["seed_id"] == e["seed_id"]]
    )
    write("graph-inputs/outcomes.json", selected_outcomes)
    label_by_key = {}
    by_id = {r["proposal_id"]: r for r in proposals}
    for r in selected_outcomes:
        if r["proposal_id"] in by_id:
            key = Candidate.model_validate(by_id[r["proposal_id"]]["candidate"]).key
            label_by_key[key] = r["labels"]
    results = []
    for b in bundles:
        validate_source(b, fs, source)
        stem = "samples/graph-" + b.method
        write(stem + ".json", b.model_dump(mode="json", by_alias=True))
        (HERE / (stem + ".md")).write_text(render(b))
        labels = [
            {"pair_key": l.candidate.key, "labels": label_by_key.get(l.candidate.key, [{"label": "unknown"}])}
            for l in b.leads
        ]
        results.append(
            metrics(b)
            | {
                "method": b.method,
                "labels": labels,
                "sample": stem + ".json",
                "known_positive_pairs": sum(
                    any(
                        x["label"] in ("duplicate", "actionable-whole-duplication", "useful-bounded-extraction")
                        for x in r["labels"]
                    )
                    for r in labels
                ),
                "unknown_pairs": sum(all(x["label"] == "unknown" for x in r["labels"]) for r in labels),
                "new_confirmed_operations": 0,
                "genericity_assessment": None,
            }
        )
    # Check supplied native lane agrees with the actual pinned Detector using rehydrated tokens.
    parent = c.model_copy(update={"new": det.find(c.new.qualname), "existing": det.find(c.existing.qualname)})
    actual = det.relatives([parent.new], [parent])
    assert {r.key for r in actual} == {l.candidate.key for l in grouped.get("current_relatives_native", [])}
    write(
        "graph-comparison.json",
        {
            "schema": 1,
            "seed_id": e["seed_id"],
            "seed_mode": seed.mode,
            "seed_naturally_baseline_admitted": any(
                p.key == parent.key and p.lane == "baseline" for p in det.candidates([parent.new])
            ),
            "cohort": source.model_dump(),
            "results": results,
            "rejected_proposals": rejected,
            "actual_native_relatives_validated": True,
            "graph_source": "published all-node graph-worker proposals, distinct from censored bank proxy",
            "selection": "first published oracle baseline seed; fixed max4 leads and 6000 source-token proxy; no label tuning",
            "scope": "one seed development integration demonstration; not independent precision or operation yield",
            "input_proposal_sha256": prop_sha,
            "provider_calls": 0,
        },
    )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
