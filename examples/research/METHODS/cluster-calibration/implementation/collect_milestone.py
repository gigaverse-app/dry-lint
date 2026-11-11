# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, E741, I001, UP017
"""Verify and export only single-seed conditional yield. No learned model execution."""

import collections, datetime, hashlib, json, pathlib

H = pathlib.Path(__file__).resolve().parent
ARMS = {"fixed_fusion", "seed_anchor_first"}


def read(name):
    return json.loads((H / name).read_text())


def jl(path):
    with pathlib.Path(path).open() as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def sha(path):
    with pathlib.Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def write(name, value):
    (H / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main():
    contract = read("EXPERIMENT-CONTRACT.json")
    queues = [r for r in jl(H / "one-seed-queues.jsonl") if r["arm"] in ARMS]
    wanted = {p for q in queues for p in q["queue"]} | {q["seed_pair_id"] for q in queues}
    rows, first = {}, {}
    for r in jl(H / "rows.jsonl"):
        if r["label"] >= 0:
            group = min(l["inventory"]["component"] for l in r["labels"])
            first[group] = min(first.get(group, r["pair_id"]), r["pair_id"])
        if r["pair_id"] in wanted:
            rows[r["pair_id"]] = r
    assert wanted == rows.keys()
    by_queue = {(q["seed_pair_id"], q["arm"]): q for q in queues}
    for q in queues:
        seed = rows[q["seed_pair_id"]]
        assert first[q["source_component"]] == q["seed_pair_id"]
        assert q["seed_pair_id"] not in q["queue"] and q["hidden_sibling_labels"]
        assert not any(t in seed["repository"].lower() for t in ["opencode", "firecrawl", "curator"])
        assert (seed["label"] == 1) == q["seed_source_positive"]
        base = by_queue[q["seed_pair_id"], "fixed_fusion"]["queue"]
        assert base == sorted(base, key=lambda p: (-rows[p]["fixed_fusion"], p))
        endpoints = set(seed["positions"])
        anchored = sorted(
            base, key=lambda p: (-bool(endpoints & set(rows[p]["positions"])), -rows[p]["fixed_fusion"], p)
        )
        assert by_queue[q["seed_pair_id"], "seed_anchor_first"]["queue"] == anchored
    outcomes = [r for r in jl(H / "one-seed-results.jsonl") if r["arm"] in ARMS]
    for r in outcomes:
        q = by_queue[r["seed_pair_id"], r["arm"]]
        endpoints = set(rows[r["seed_pair_id"]]["positions"])
        selected, closed = [], set()
        for p in q["queue"]:
            if len(selected) >= r["budget"]:
                break
            row = rows[p]
            shared = endpoints & set(row["positions"])
            branch = ("endpoint", min(shared)) if shared else ("component", min(row["graph_components"]))
            if branch in closed:
                continue
            selected.append(p)
            if row["label"] == 0:
                if r["policy"] == "cluster_stop":
                    break
                if r["policy"] == "branch_local_stop":
                    closed.add(branch)
        assert selected == r["selected_pair_ids"]
        counts = collections.Counter(rows[p]["label"] for p in selected)
        assert (counts[1], counts[0], counts[-1], len(selected)) == (
            r["positive"],
            r["negative"],
            r["unknown"],
            r["reviewed"],
        )
    summaries = [r for r in read("ONE-SEED-RESULTS.json")["rows"] if r["arm"] in ARMS]
    for s in summaries:
        matching = [r for r in outcomes if all(r[k] == s[k] for k in ("arm", "seed_mode", "budget", "policy"))]
        assert len(matching) == s["scenarios"]
        assert all(sum(r[k] for r in matching) == v for k, v in s["totals_occurrences"].items())
        assert (
            len({p for r in matching for p in r["selected_pair_ids"] if rows[p]["label"] == 1})
            == s["unique_positive_pairs"]
        )
    write(
        "CONDITIONAL-YIELD.json",
        {
            "schema": 1,
            "scope": "Single available source seed; no learned scores or spectral partitioning.",
            "results": summaries,
            "uncertainty": "Preserved 500-draw source-component/repository bootstrap from frozen trials. Selected development sample, not population precision; unknown decisions censor stopping.",
            "cost": "Full-source character burden from recorded execution; collection verifies aggregation, not human reading time. Source reuse is an accounting assumption.",
        },
    )
    seed_queues = [q for q in queues if q["arm"] == "fixed_fusion"]
    sources = {p["cohort_id"]: p for p in contract["inputs"]}
    needed = collections.defaultdict(set)
    for q in seed_queues:
        r = rows[q["seed_pair_id"]]
        needed[r["cohort_id"]].update(r["positions"])
    functions = {}
    for cid, positions in needed.items():
        p = sources[cid]["source"]
        assert sha(p["functions_path"]) == p["functions_sha256"]
        functions[cid] = {i: f for i, f in enumerate(jl(p["functions_path"])) if i in positions}
    with (H / "single-available-seeds.jsonl").open("w") as out:
        for q in seed_queues:
            r = rows[q["seed_pair_id"]]
            endpoint_hashes = {r["source"][k]["position"]: r["source"][k]["source_sha256"] for k in ("query", "target")}
            fs = []
            for pos in r["positions"]:
                f = functions[r["cohort_id"]][pos]
                assert hashlib.sha256(f["code"].encode()).hexdigest() == endpoint_hashes[pos]
                fs.append({"position": pos, "source_sha256": endpoint_hashes[pos], "function": f})
            record = {
                "schema": 1,
                "seed_pair_id": q["seed_pair_id"],
                "source_component": q["source_component"],
                "cohort_id": r["cohort_id"],
                "repository": r["repository"],
                "revision": r["revision"],
                "positions": r["positions"],
                "functions": fs,
                "source": sources[r["cohort_id"]]["source"],
                "seed_mode": "source_positive_oracle_single_seed" if r["label"] == 1 else "false_positive_seed_control",
                "seed_source_label": r["label"],
                "presented_as_positive": True,
                "seed_label_provenance": r["labels"],
                "sibling_labels_included": False,
                "chronological_native_report_verified": False,
            }
            out.write(json.dumps(record, sort_keys=True) + "\n")
    with (H / "single-seed-outcomes.jsonl").open("w") as out:
        for r in outcomes:
            out.write(json.dumps(r, sort_keys=True) + "\n")
    split_path = pathlib.Path(contract["split_path"])
    assert sha(split_path) == contract["split_sha256"]
    write(
        "SOURCE-SPLIT-INDEX.json",
        {
            "schema": 1,
            "product_commit": contract["product_commit"],
            "split_path": str(split_path),
            "split_sha256": contract["split_sha256"],
            "allowed_cohorts": contract["inputs"],
            "restrictions": "Opencode heldout outcomes unreleased; Firecrawl/curator unopened. Exact source/scope identity only. Audit source components group revisions; similarity components never assert duplication.",
        },
    )
    verified = {
        "schema": 1,
        "verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source_seed_scenarios": len(seed_queues),
        "queues_replayed": len(queues),
        "review_trials_replayed": len(outcomes),
        "source_positive_seeds": sum(q["seed_source_positive"] for q in seed_queues),
        "false_seed_controls": sum(not q["seed_source_positive"] for q in seed_queues),
        "seed_selection_verified_without_seed_label_values": True,
        "full_seed_body_hashes_verified": True,
        "sibling_labels_used_for_ordering": False,
        "unknown_as_negative": False,
        "reserved_outcomes_accessed": False,
        "learned_models_executed": False,
        "spectral_partition_implementation": False,
        "inputs": {
            n: sha(H / n)
            for n in ["rows.jsonl", "one-seed-queues.jsonl", "one-seed-results.jsonl", "ONE-SEED-RESULTS.json"]
        },
    }
    write("MILESTONE-VERIFICATION.json", verified)
    names = [
        "SOURCE-SPLIT-INDEX.json",
        "single-available-seeds.jsonl",
        "recorded-seeds.jsonl",
        "OBSERVATION-INPUTS.json",
        "SEED-INGESTION.json",
        "NATIVE-SEED-LINKS.json",
        "HISTORICAL-SEED-LINKS.json",
        "CONDITIONAL-YIELD.json",
        "single-seed-outcomes.jsonl",
        "MILESTONE-VERIFICATION.json",
        "GRAPH-REFERENCE.json",
        "REPRESENTATIVE-CASE.json",
    ]
    write(
        "SPECTRAL-HANDOFF.json",
        {
            "schema": 1,
            "from": "cluster-calibration",
            "to": "spectral-family-recovery",
            "artifacts": {n: {"path": str(H / n), "sha256": sha(H / n)} for n in names},
            "safe_start": ["SOURCE-SPLIT-INDEX.json", "single-available-seeds.jsonl"],
            "held_until_scoring": ["single-seed-outcomes.jsonl", "CONDITIONAL-YIELD.json"],
            "graph_owner": "spectral-family-recovery owns SVD/eigenvalues, normalized Laplacian, Fiedler/conductance cuts and seed-local spectral implementation. No duplicate partition implementation here.",
            "seed_rules": "Expose one seed per scenario. Only its source label is available before scoring. Source-positive oracle, intentionally false-positive source seed and actual recorded provider-positive evidence are distinct. Exact provider answer does not authenticate historical native emission or establish source truth.",
            "leakage_fixes": [
                "Keep audit source components; never merge them through unknown candidate edges.",
                "Keep fitting/calibration/evaluation seed labels isolated if any future learned method is used.",
                "Never construct a graph from sibling outcome labels or infer duplicate equivalence from connectivity.",
            ],
            "label_policy": "Preserve operation scope, before/after negatives, utility/related/tiny/already-shared/disputed/unknown evidence. Ineligible labels remain unknown. Speculative nonblocking leads may include negatives.",
            "legacy": "Completed SVM/model and p-value-related discussion is exploratory and outside the corrected requested direction; excluded from this handoff. No further model tuning or p-value work.",
        },
    )
    print(json.dumps({k: v for k, v in verified.items() if k != "inputs"}, sort_keys=True))


if __name__ == "__main__":
    main()
