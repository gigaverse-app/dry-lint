# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E741, F403, F405, F841, I001
"""Executable synthetic invariants and oracle-only branch review diagnostics."""

from run_cluster import *
from dry_lint.detector import why_skipped


def synthetic_graph():
    ex = PythonExtractor()
    # Three byte-identical implementations at different source paths. Literal mismatches
    # in other branches are deliberate negative controls, not production truth.
    copy = 'def deliver(account, payload):\n    """Validate, reserve, dispatch and record one delivery."""\n    validate_delivery(account, payload)\n    token = reserve_delivery(account)\n    result = dispatch_delivery(token, payload)\n    record_delivery(account, result)\n    return result\n'
    fs = []
    for i in range(3):
        fs += ex.functions(f"copy{i}.py", copy)
    fs += ex.functions(
        "branch.py",
        "def cancel_delivery(account, payload):\n    validate_delivery(account, payload)\n    token = reserve_delivery(account)\n    return cancel_reservation(token)\n",
    )
    for i in range(30):
        fs += ex.functions(
            f"hub{i}.py",
            f'def create_resource(value):\n    """Deliberate per-resource template."""\n    logger.info("resource{i}")\n    return Resource("kind{i}", value)\n',
        )
    g = Graph.__new__(Graph)
    g.cid = "synthetic-controls"
    g.fs = fs
    g.n = len(fs)
    g.valid = [True] * g.n
    g.lang = ["python"] * g.n
    g.pos = {f.qualname: i for i, f in enumerate(fs)}
    g.api = [
        {
            t
            for t in f.tokens
            if t.startswith(("call:", "attr:", "key:")) and t.partition(":")[2].lower() not in _GENERIC
        }
        for f in fs
    ]
    g.df = collections.Counter(t for ts in g.api for t in ts)
    g.adj = collections.defaultdict(dict)
    g.edges = {}
    comparer = TfidfComparer()
    g.det = Detector(fs, Settings(), comparer, [ex])
    g.ops = OperationBlocksComparer()
    g.ops.index(fs)
    for q in range(g.n):
        for t, s in comparer.tfidf.similar(fs[q].tokens):
            if t == q or s < 0.35:
                continue
            edge = {"edge_id": g.edge_id(q, t), "query_position": q, "target_position": t, "weight": s}
            g.adj[q][t] = edge
            g.edges[edge["edge_id"]] = edge
    g.finish()
    return g


def main():
    g = synthetic_graph()
    a, b = 0, 1
    parent = g.det.pair(g.fs[a], g.fs[b], 1.0)
    native = g.det.relatives([g.fs[a]], [parent])
    exp = g.det.relatives([g.fs[a]], [parent.model_copy(update={"lane": "exploration"})])
    assert any(c.existing.qualname == g.fs[2].qualname for c in native)
    assert not exp
    checks = []
    for method in METHODS[2:]:
        hits = g.proposals(a, b, method)
        assert any(t == 2 for q, t, path, score, e in hits)
        # Hub templates are connected to one another but never prove anything about seed.
        assert all(t < 4 for q, t, path, score, e in hits)
        checks.append(
            {
                "method": method,
                "exact_copy_recovered": True,
                "generic_template_hubs_exposed": sum(t >= 4 for q, t, p, s, e in hits),
                "synthetic_candidates": len(hits),
            }
        )
    ex = PythonExtractor()
    before = ex.functions(
        "before.py",
        "class Store:\n    def normalize(self, key):\n        return key.strip().lower()\n    def read(self, key):\n        key = key.strip().lower()\n        return self.normalize(key)\n",
    )
    after = ex.functions(
        "after.py",
        "class Store:\n    def normalize(self, key):\n        return key.strip().lower()\n    def read(self, key):\n        return self.normalize(key)\n",
    )
    assert why_skipped(before[0], before[1], Settings()) is None
    assert why_skipped(after[0], after[1], Settings()) == "forwarding wrapper"
    # Rejection on one branch must not veto independent work; all methods use
    # the same explicit source-token budget and known synthetic answers.
    schedule = [
        {"branch": "A", "label": "separate", "tokens": 20},
        {"branch": "B", "label": "useful", "tokens": 30},
        {"branch": "A", "label": "useful", "tokens": 20},
        {"branch": "C", "label": "useful", "tokens": 30},
    ]
    comparison = []
    for policy in ["cluster_pause", "branch_local_stop", "branch_local_downweight"]:
        rejected = set()
        spent = 0
        useful = 0
        reviewed = []
        pending = list(schedule)
        while pending:
            item = pending.pop(0)
            if policy == "branch_local_stop" and item["branch"] in rejected:
                continue
            if spent + item["tokens"] > 80:
                continue
            spent += item["tokens"]
            reviewed.append(item)
            if item["label"] == "useful":
                useful += 1
            else:
                rejected.add(item["branch"])
                if policy == "cluster_pause":
                    break
                if policy == "branch_local_downweight":
                    pending.sort(key=lambda x: x["branch"] in rejected)
        comparison.append(
            {
                "policy": policy,
                "budget_tokens_proxy": 80,
                "spent_tokens_proxy": spent,
                "useful": useful,
                "reviewed": reviewed,
            }
        )
    assert comparison[1]["useful"] > comparison[0]["useful"]
    write(
        HERE / "CONTROLS.json",
        {
            "schema": 1,
            "authority": "synthetic mechanism controls, not measured production precision",
            "checks": checks,
            "native_baseline_copy_count": len(native),
            "native_exploration_seed_relative_count": len(exp),
            "before_after": {
                "before_additional_policy_suppressed": False,
                "after_adapter_proven_forwarder_suppressed": True,
                "all_callers_suppressed": False,
            },
            "template_hub_nodes": len(g.hubs),
            "branch_review_comparison": comparison,
            "decision": "branch-local downweight is preferred navigation policy; root independently evaluates leads. One rejection is not cluster-wide evidence.",
        },
    )
    # Published labels are used here only AFTER proposal construction. Unanswered
    # candidates are censored, not imagined useful or negative outcomes.
    if (HERE / "proposals.jsonl").exists():
        outcome = {r["proposal_id"]: r for r in jl(HERE / "outcomes.jsonl")}
        groups = collections.defaultdict(list)
        for r in jl(HERE / "proposals.jsonl"):
            if r["method"] in METHODS[2:]:
                groups[(r["seed_id"], r["method"])].append(r)
        diagnostic = []
        for (seedid, method), rs in groups.items():
            for policy in ["cluster_pause", "branch_local_stop", "branch_local_downweight"]:
                pending = list(rs)
                rejected = set()
                used = set()
                tokens = 0
                useful = negative = unknown = 0
                while pending:
                    r = pending.pop(0)
                    branch = tuple(r["path_positions"][:2])
                    labels = {l["label"] for l in outcome[r["proposal_id"]]["labels"]}
                    if policy == "branch_local_stop" and branch in rejected:
                        continue
                    cost = r["source_tokens_proxy"]
                    if tokens + cost > 15000:
                        continue
                    tokens += cost
                    if labels & USEFUL:
                        useful += 1
                    elif labels & NEGATIVE:
                        negative += 1
                        rejected.add(branch)
                        if policy == "cluster_pause":
                            break
                        if policy == "branch_local_downweight":
                            pending.sort(key=lambda x: tuple(x["path_positions"][:2]) in rejected)
                    else:
                        unknown += 1
                diagnostic.append(
                    {
                        "seed_id": seedid,
                        "method": method,
                        "seed_mode": rs[0]["seed_mode"],
                        "policy": policy,
                        "known_useful": useful,
                        "known_negative": negative,
                        "unknown_review_answers": unknown,
                        "charged_pair_tokens_proxy": tokens,
                        "budget_tokens_proxy": 15000,
                        "interpretation": "offline label oracle branch comparison; unknowns remain unresolved, not stopping evidence; per-pair review charge, not actual human time",
                    }
                )
        write(HERE / "branch-policy-diagnostics.jsonl", diagnostic)
    print("synthetic controls passed")


if __name__ == "__main__":
    from dry_lint.operation_blocks import _GENERIC

    main()
