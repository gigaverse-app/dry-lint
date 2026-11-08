"""Recompute bounded results from recordings, without providers or model inference.

This is a result replay, not source extraction or an encoder rerun. See each method
README for the separate original implementation and missing-input boundaries.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def rows(path):
    with path.open() as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def read(path):
    return json.loads(path.read_text())


def resolve(root, recorded):
    """Map recorded locations into an explicitly supplied materialized evidence tree."""
    path = Path(recorded)
    if not path.is_absolute():
        result = root / path
    else:
        parts = path.parts
        if "dry-lint-round" not in parts:
            raise ValueError(f"No approved relative mapping for {path.name}")
        result = root.joinpath(*parts[parts.index("dry-lint-round") + 1 :])
    result = result.resolve()
    if not result.is_relative_to(root):
        raise ValueError("Evidence path escapes the supplied root")
    if not result.is_file():
        raise FileNotFoundError(result)
    return result


def ranks(lab, method):
    complementary = method == "complementary-signal-learning"
    path = lab / ("deterministic-v2/outcomes.jsonl" if complementary else "reference-pairs.jsonl")
    data = list(rows(path))
    data = (
        [r for r in data if r["accepted_gold"] and r["label"] == "duplicate"]
        if complementary
        else [r for r in data if r["accepted_binary"] and r["category"] == "duplicate"]
    )
    arms = ["tfidf", "fixed_fusion", "conditional"] if complementary else ["tfidf", "rrf60", "minilm"]
    output = []
    for cap in [4, 20]:

        def rk(r):
            return r["ranks"] if complementary else r["ranks"]["raw"]

        baseline = {
            i for i, r in enumerate(data) if rk(r).get("tfidf", 10**9) is not None and rk(r).get("tfidf", 10**9) <= cap
        }
        for arm in arms:
            hit = {i for i, r in enumerate(data) if rk(r).get(arm, 10**9) is not None and rk(r).get(arm, 10**9) <= cap}
            output.append(
                dict(
                    arm=arm,
                    cap=cap,
                    hits=len(hit),
                    denominator=len(data),
                    added=len(hit - baseline),
                    lost=len(baseline - hit),
                )
            )
    assert len(data) == 159
    assert [r["hits"] for r in output[:2]] == [134, 130]
    return dict(
        scope="Known-positive pair-case rank aggregation; not native reports",
        results=output,
        inputs=[dict(path=str(path.relative_to(lab)), sha256=sha(path))],
    )


def cluster(lab):
    """Replay actual queue selection and stopping against frozen hidden outcomes."""
    queues = [q for q in rows(lab / "one-seed-queues.jsonl") if q["arm"] in {"fixed_fusion", "seed_anchor_first"}]
    wanted = {p for q in queues for p in q["queue"]} | {q["seed_pair_id"] for q in queues}
    data = {r["pair_id"]: r for r in rows(lab / "rows.jsonl") if r["pair_id"] in wanted}
    assert set(data) == wanted
    by = {(q["seed_pair_id"], q["arm"]): q for q in queues}
    for q in queues:
        seed = data[q["seed_pair_id"]]
        assert q["hidden_sibling_labels"] and q["seed_pair_id"] not in q["queue"]
        base = by[q["seed_pair_id"], "fixed_fusion"]["queue"]
        assert base == sorted(base, key=lambda p: (-data[p]["fixed_fusion"], p))
        endpoints = set(seed["positions"])
        assert by[q["seed_pair_id"], "seed_anchor_first"]["queue"] == sorted(
            base, key=lambda p: (-bool(endpoints & set(data[p]["positions"])), -data[p]["fixed_fusion"], p)
        )
    trials = 0
    totals = collections.defaultdict(collections.Counter)
    for r in rows(lab / "one-seed-results.jsonl"):
        if r["arm"] not in {"fixed_fusion", "seed_anchor_first"}:
            continue
        q = by[r["seed_pair_id"], r["arm"]]
        endpoints = set(data[r["seed_pair_id"]]["positions"])
        selected, closed = [], set()
        for p in q["queue"]:
            if len(selected) >= r["budget"]:
                break
            row = data[p]
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
        c = collections.Counter(data[p]["label"] for p in selected)
        assert (c[1], c[0], c[-1], len(selected)) == (r["positive"], r["negative"], r["unknown"], r["reviewed"])
        key = (r["arm"], r["seed_mode"], r["budget"], r["policy"])
        totals[key].update(positive=c[1], negative=c[0], unknown=c[-1], reviewed=len(selected), scenarios=1)
        trials += 1
    return dict(
        scope="Recomputed queue orders, stop decisions and known/negative/unknown counts",
        queues=len(queues),
        trials=trials,
        results=[
            dict(zip(["arm", "seed_mode", "budget", "policy"], k, strict=True), **v) for k, v in sorted(totals.items())
        ],
    )


def metrics(lab, method):
    data = list(rows(lab / "metrics.jsonl"))
    if method == "spectral-family-recovery":
        group = ["seed_mode", "seed_lane", "method", "cap"]
        fields = [
            "known_useful",
            "known_negative",
            "unknown",
            "other",
            "leads",
            "lost_native_pairs",
            "source_tokens_proxy",
            "conditional_recall_numerator",
            "conditional_recall_denominator",
        ]
    else:
        group = ["seed_mode", "seed_lane", "method"]
        fields = [
            "proposals",
            "known_useful",
            "known_negative_exposure",
            "known_other",
            "unknown",
            "unique_source_tokens_proxy",
            "incremental_known_useful",
        ]
    totals = collections.defaultdict(collections.Counter)
    for r in data:
        totals[tuple(r[k] for k in group)].update({k: r[k] for k in fields})
        totals[tuple(r[k] for k in group)]["scenarios"] += 1
    return dict(
        scope="Aggregate frozen per-seed measurements; not graph or source reconstruction",
        rows=len(data),
        results=[dict(zip(group, k, strict=True), **v) for k, v in sorted(totals.items(), key=lambda kv: repr(kv[0]))],
        inputs=[dict(path="metrics.jsonl", sha256=sha(lab / "metrics.jsonl"))],
    )


def campaigns(lab, method):
    if method == "adaptive-judge-budget":
        files = [lab / "completion-final-measured/results.jsonl"]
    elif method == "learned-budget-policy":
        files = [lab / "dynamic-residual-v2/results.jsonl"]
    else:
        files = [lab / p / "results.jsonl" for p in ["full12-original-r3", "full12-residual-r3", "full12-hybrid-r1"]]
    answer = []
    for path in files:
        grouped = collections.defaultdict(collections.Counter)
        for r in rows(path):
            for arm, value in (r["arms"] if "arms" in r else {r["arm"]: r}).items():
                for accounting in ["normal", "native"]:
                    if accounting not in value:
                        continue
                    item = value[accounting]
                    c = grouped[arm, accounting]
                    c.update(campaigns=1, censored=int(bool(item.get("censored"))))
                    parts = [item[k] for k in ["protected_prefix", "residual"] if k in item]
                    if not parts:
                        parts = [item]
                    events = [e for part in parts for e in part.get("events", [])]
                    successful = [e for e in events if e.get("success")]
                    c["successful_attempts"] += len(successful)
                    if accounting == "native":
                        for part in parts:
                            charge = sum(e.get("settled_actual_usd", 0) or 0 for e in part.get("events", []))
                            if "actual_settled_usd" in part:
                                assert abs(charge - part["actual_settled_usd"]) < 1e-8
                            c["actual_settled_usd"] += charge
                            c["paid_failed_attempts"] += sum(
                                e.get("success") is False and bool(e.get("settled_actual_usd"))
                                for e in part.get("events", [])
                            )
                    reports = item.get("reported_keys", item.get("reports"))
                    if reports is not None:
                        c["reported_occurrences"] += len(reports)
                    else:
                        c["report_count_unavailable_campaigns"] += 1
        answer.append(
            dict(
                input=str(path.relative_to(lab)),
                sha256=sha(path),
                arms=[dict(arm=k[0], accounting=k[1], **v) for k, v in sorted(grouped.items())],
            )
        )
    return dict(
        scope="Recompute settled usage and censoring from frozen events; no scheduler or provider execution",
        results=answer,
    )


def matrix(root, receipt_path):
    import numpy as np

    receipt = read(receipt_path)
    encoder = root / "jobs/encoder-corpus-evaluation/.lab-results"
    panel = next(p for p in rows(encoder / "panels.jsonl") if p["cohort_id"] == receipt["cohort_id"])
    docs = list(rows(resolve(root, panel["documents_path"])))
    dpath = resolve(root, receipt["document_matrix_path"])
    qpath = resolve(root, receipt.get("query_matrix_path", receipt["document_matrix_path"]))
    assert sha(dpath) == receipt["document_matrix_sha256"]
    assert sha(qpath) == receipt.get("query_matrix_sha256", receipt["document_matrix_sha256"])
    assert receipt["background_sha256"] == panel["background_sha256"]
    assert receipt["functions_sha256"] == panel["functions_sha256"]
    d = np.load(dpath, mmap_mode="r", allow_pickle=False)
    q = np.load(qpath, mmap_mode="r", allow_pickle=False)
    assert len(d) == len(docs) and np.isfinite(d).all()
    expected = encoder / "ranks" / receipt["method"] / (receipt["cohort_id"] + ".jsonl")
    checked = 0
    maximum = 0.0
    tie = [(r["source_id"], r["source_sha256"]) for r in docs]
    cache = {}
    for row in rows(expected):
        position = row["query_position"]
        target = row["target_position"]
        if position not in cache:
            scores = d @ q[position]
            order = sorted((i for i in range(len(d)) if i != position), key=lambda i: (-float(scores[i]), tie[i], i))
            cache[position] = (scores, {i: j for j, i in enumerate(order, 1)})
        scores, ranks = cache[position]
        error = abs(float(scores[target]) - row["score"])
        maximum = max(maximum, error)
        assert error <= 1e-6 and ranks[target] == row["raw_rank"]
        checked += 1
    assert checked > 0
    return dict(
        scope="Recomputed full-background cosine scores and raw ranks from frozen matrices; no encoder inference",
        directions=checked,
        documents=len(d),
        maximum_score_error=maximum,
        rank_mismatches=0,
        receipt_sha256=sha(receipt_path),
        matrix_sha256=sha(dpath),
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--method", required=True)
    ap.add_argument("--evidence-root", type=Path, required=True)
    ap.add_argument("--receipt", type=Path, help="Relative matrix receipt for encoder replay")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    root = args.evidence_root.resolve()
    if not root.is_dir():
        ap.error("Evidence root is unavailable")
    recipe_path = Path(__file__).resolve().parent / args.method / "recipe.json"
    recipe = read(recipe_path)
    for binding in recipe["replay_inputs"]:
        path = root / binding["path"]
        if sha(path) != binding["sha256"]:
            raise ValueError("Frozen input hash mismatch: " + binding["path"])
    if args.receipt is not None and str(args.receipt) not in {r["path"] for r in recipe["replay_inputs"]}:
        ap.error("Receipt is outside this recovered frozen replay; make a new recipe for other matrices")
    lab = root / "jobs" / args.method / ".lab-results"
    if args.method in {"complementary-signal-learning", "cross-repo-recall-audit"}:
        result = ranks(lab, args.method)
    elif args.method == "cluster-calibration":
        result = cluster(lab)
    elif args.method in {"spectral-family-recovery", "confirmed-cluster-expansion"}:
        result = metrics(lab, args.method)
    elif args.method in {"adaptive-judge-budget", "learned-budget-policy", "tfidf-blindspot-recovery"}:
        result = campaigns(lab, args.method)
    elif args.method in {"encoder-corpus-evaluation", "coderank-cpu-evaluation", "gemma-cpu-evaluation"}:
        if args.receipt is None:
            ap.error("Specify an exact completed --receipt")
        result = matrix(root, resolve(root, str(args.receipt)))
    else:
        ap.error("Use the method-specific implementation; no aggregate replay supplied for this direction")
    result = dict(schema=1, method=args.method, provider_calls=0, encoder_calls=0, **result)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as output:
        json.dump(result, output, indent=2)
        output.write("\n")
    print(json.dumps({"method": args.method, "scope": result["scope"], "passed": True}))


if __name__ == "__main__":
    main()
