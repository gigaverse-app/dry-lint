# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, I001
"""Keep lifetime verified replay coverage separate from the active ordered pass."""

import json, pathlib


def augment_status(lab, status):
    lab = pathlib.Path(lab)
    index = json.loads((lab / "GRAPH-CACHE-INDEX.json").read_text())
    verified = []
    historical = []
    typeerrors = []
    for c in index["cohorts"]:
        cid = c["cohort_id"]
        d = lab / "extended" / cid
        receipts = [d / "COMPLETE.json", *sorted(d.glob("PRIOR-COMPLETE-*.json"))]
        for p in receipts:
            if p.exists():
                r = json.loads(p.read_text())
                if r.get("status") == "complete" and "verification" in r:
                    verified.append({"cohort_id": cid, "receipt": str(p)})
                    break
        if (d / "FAILURE.json").exists():
            historical.append(cid)
        log = d / "execution.log"
        if log.exists() and "TypeError:" in log.read_text():
            typeerrors.append(cid)
    n = sum(c["evaluation_status"] == "complete" for c in index["cohorts"])
    fail = sum(c["evaluation_status"] == "failed" for c in index["cohorts"])
    completed_ids = {c["cohort_id"] for c in index["cohorts"] if c["evaluation_status"] == "complete"}
    return status | {
        "completed": n,
        "failures": fail,
        "denominator": 56,
        "total_verified_complete_cohorts": len(verified),
        "current_pass_completed_cohorts": n,
        "current_pass_failures": fail,
        "final_ordered_replay_complete": n == 56 and fail == 0,
        "graphs_ready": index["ready"],
        "coverage_meaning": "Total verified counts complete replay receipts from any pass, never graph construction alone. Current pass reconciles frozen seed order; prior receipts remain evidence but do not establish final cross-cohort oracle consistency.",
        "historical_failure_cohorts": len(historical),
        "historical_typeerror_cohorts": len(typeerrors),
        "typeerror_cohorts_reconciled_in_current_pass": len(set(typeerrors) & completed_ids),
        "failure_receipts_preserved": True,
        "replay_receipt_index": verified,
        "graph_cache_hash_index": str(lab / "GRAPH-CACHE-INDEX.json"),
    }
