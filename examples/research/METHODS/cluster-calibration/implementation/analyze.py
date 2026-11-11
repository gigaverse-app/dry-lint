# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B007, B905, E401, E402, E741, F401, F841, I001
"""Selected-label associations and frozen small-model diagnostics; never population truth."""

import os

for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[k] = "2"
import sys

sys.dont_write_bytecode = True
import json, collections, pathlib, hashlib, time
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from prepare import H, jl, write, sha, DSU

SEED = 20261107


def summarize(rows, ids):
    ids = list(ids)
    ys = [rows[i]["label"] for i in ids]
    n = len(ids)
    p = ys.count(1)
    neg = ys.count(0)
    u = ys.count(-1)
    return {
        "pairs": n,
        "positive": p,
        "negative": neg,
        "unknown": u,
        "observed_positive_fraction": p / (p + neg) if p + neg else None,
        "all_candidate_positive_bounds": [p / n, (p + u) / n] if n else None,
        "positive_source_components": len({rows[i]["group"] for i in ids if rows[i]["label"] == 1}),
        "repos": len({rows[i]["repository"] for i in ids}),
    }


def bootstrap(vals, groups):
    by = collections.defaultdict(list)
    for v, g in zip(vals, groups):
        by[g].append(v)
    if len(by) < 2:
        return {"groups": len(by), "interval95": None, "reason": "fewer than two independent observed groups"}
    arr = [np.asarray(v) for v in by.values()]
    rng = np.random.default_rng(SEED)
    means = []
    for _ in range(500):
        sampled = [arr[k] for k in rng.integers(0, len(arr), len(arr))]
        means.append(float(np.concatenate(sampled).mean()))
    return {"groups": len(by), "interval95": np.quantile(means, [0.025, 0.975]).tolist(), "draws": 500}


def matches(rows, X, exposure, ids):
    treated = [i for i in ids if exposure[i]]
    control = [i for i in ids if not exposure[i]]
    available = set(control)
    pairs = []
    # No outcome value used in match selection; same pre-specified label-observed subset.
    for i in sorted(treated, key=lambda i: rows[i]["pair_id"]):
        choices = []
        for j in available:
            if rows[i]["repository"] != rows[j]["repository"]:
                continue
            d = np.abs(X[i] - X[j])
            if d[0] > 0.1 or d[5] > 0.7 or d[6] > 0.7 or d[8] != 0 or d[9] != 0:
                continue
            choices.append((d[0] / 0.1 + d[5] / 0.7 + d[6] / 0.7, rows[j]["pair_id"], j))
        if choices:
            j = min(choices)[2]
            available.remove(j)
            pairs.append((i, j))
    diff = [rows[i]["label"] - rows[j]["label"] for i, j in pairs]
    ds = DSU()
    for i, j in pairs:
        ds.union(rows[i]["group"], rows[j]["group"])
    return {
        "seeded_available": len(treated),
        "unseeded_available": len(control),
        "matched": len(pairs),
        "unmatched_seeded": len(treated) - len(pairs),
        "seeded": summarize(rows, [i for i, j in pairs]),
        "unseeded": summarize(rows, [j for i, j in pairs]),
        "risk_difference": float(np.mean(diff)) if diff else None,
        "source_component_bootstrap": bootstrap(diff, [ds.find(rows[i]["group"]) for i, j in pairs]),
        "repository_bootstrap": bootstrap(diff, [rows[i]["repository"] for i, j in pairs]),
        "balance_mean_absolute_difference": dict(
            zip(
                ["tfidf", "log_min_lines", "log_max_lines"],
                np.mean([np.abs(X[i, [0, 5, 6]] - X[j, [0, 5, 6]]) for i, j in pairs], axis=0).tolist(),
            )
        )
        if pairs
        else None,
        "pairs": [{"seeded": rows[i]["pair_id"], "control": rows[j]["pair_id"]} for i, j in pairs],
    }


def main():
    tick = time.monotonic()
    rows = list(jl(H / "rows.jsonl"))
    X = np.load(H / "features.npy")
    c = json.loads((H / "EXPERIMENT-CONTRACT.json").read_text())
    n = len(rows)
    Y = np.array([r["label"] for r in rows])
    known = np.where(Y >= 0)[0]
    groups = DSU()
    for r in rows:
        cs = sorted({l["inventory"]["component"] for l in r["labels"]})
        for a in cs[1:]:
            groups.union(cs[0], a)
    for r in rows:
        cs = sorted({l["inventory"]["component"] for l in r["labels"]})
        r["group"] = groups.find(cs[0]) if cs else "unknown:" + r["pair_id"]
    repos = sorted({r["repository"] for r in rows})
    repo = np.array([r["repository"] for r in rows])
    g = np.array([r["group"] for r in rows])
    oracle = X[:, 17] > 0
    false = np.array([bool(r["false_endpoint_seed_pairs"]) for r in rows])
    avail = X[:, 19] > 0
    lift = {
        "all": summarize(rows, range(n)),
        "known_seed_support": int(sum(avail[known])),
        "oracle": {
            "seeded": summarize(rows, np.where(oracle)[0]),
            "unseeded_with_seed_support": summarize(rows, np.where(~oracle & avail)[0]),
        },
        "false_seed": {"exposed": summarize(rows, np.where(false)[0])},
        "matching_oracle": matches(rows, X, oracle, [i for i in known if avail[i]]),
        "matching_false_seed": matches(rows, X, false, [i for i in known if avail[i]]),
        "component_exposure": {
            "exposed": summarize(rows, np.where(X[:, 18] > 0)[0]),
            "unexposed": summarize(rows, np.where(X[:, 18] == 0)[0]),
        },
    }
    write("CONDITIONAL-LIFT.json", lift)
    preds = {k: np.full(n, np.nan) for k in ["shrinkage", "svm", "svm_no_seed"]}
    folds = []
    models = []
    for testrepo in repos:
        test = np.where(repo == testrepo)[0]
        tg = set(g[test])
        pool = [i for i in known if repo[i] != testrepo and g[i] not in tg]
        cal = [i for i in pool if int(hashlib.sha256(g[i].encode()).hexdigest(), 16) % 4 == 0]
        fit = [i for i in pool if i not in set(cal)]
        f = {
            "test_repository": testrepo,
            "test_known": summarize(rows, [i for i in test if Y[i] >= 0]),
            "fit_pairs": len(fit),
            "calibration_pairs": len(cal),
            "fit_components": len(set(g[fit])),
            "calibration_components": len(set(g[cal])),
            "excluded_cross_repo_component_pairs": sum(repo[i] != testrepo and g[i] in tg for i in known),
        }
        assert not set(g[fit]) & set(g[cal]) and not set(g[fit]) & tg and not set(g[cal]) & tg
        if len(set(Y[fit])) < 2 or len(set(Y[cal])) < 2:
            f["status"] = "insufficient classes"
            folds.append(f)
            continue

        def weight(ids):
            count = collections.Counter(g[ids])
            return np.array([1 / count[g[i]] for i in ids])

        wf, wc = weight(fit), weight(cal)

        def role_features(ids):
            positive_endpoint = collections.defaultdict(set)
            positive_component = collections.defaultdict(set)
            reviewed_endpoint = collections.defaultdict(set)
            for i in ids:
                r = rows[i]
                if Y[i] < 0:
                    continue
                for pos in r["positions"]:
                    reviewed_endpoint[r["cohort_id"], pos].add(i)
                    if Y[i] == 1:
                        positive_endpoint[r["cohort_id"], pos].add(i)
                if Y[i] == 1:
                    for cc in r["graph_components"]:
                        positive_component[r["cohort_id"], cc].add(i)
            xx = X[ids].copy()
            for offset, i in enumerate(ids):
                r = rows[i]
                cid = r["cohort_id"]
                a, b = r["positions"]
                xx[offset, 17] = bool((positive_endpoint[cid, a] | positive_endpoint[cid, b]) - {i})
                xx[offset, 18] = bool(set().union(*(positive_component[cid, cc] for cc in r["graph_components"])) - {i})
                xx[offset, 19] = bool((reviewed_endpoint[cid, a] | reviewed_endpoint[cid, b]) - {i})
            return xx

        fitX, calX, testX = role_features(fit), role_features(cal), role_features(test)
        prior = float(np.average(Y[fit], weights=wf))
        bins = np.digitize(X[:, 0], [0.3, 0.5, 0.7, 0.9])
        cells = {}
        for b in range(5):
            for seed in [0, 1]:
                ix = [k for k, i in enumerate(fit) if bins[i] == b and fitX[k, 17] == seed]
                mass = sum(wf[ix])
                success = sum(wf[ix] * Y[np.array(fit)[ix]]) if ix else 0
                cells[b, seed] = (success + 10 * prior) / (mass + 10)
        preds["shrinkage"][test] = [cells[bins[i], int(testX[k, 17])] for k, i in enumerate(test)]
        for arm in ["svm", "svm_no_seed"]:
            columns = list(range(X.shape[1])) if arm == "svm" else [k for k in range(X.shape[1]) if k not in [17, 18]]
            scaler = StandardScaler().fit(fitX[:, columns], sample_weight=wf)
            clf = LinearSVC(C=0.1, max_iter=10000, random_state=SEED, dual="auto")
            clf.fit(scaler.transform(fitX[:, columns]), Y[fit], sample_weight=wf)
            margin = clf.decision_function(scaler.transform(calX[:, columns]))
            platt = LogisticRegression(C=1, random_state=SEED)
            platt.fit(margin[:, None], Y[cal], sample_weight=wc)
            preds[arm][test] = platt.predict_proba(clf.decision_function(scaler.transform(testX[:, columns]))[:, None])[
                :, 1
            ]
            models.append(
                {
                    "test_repository": testrepo,
                    "arm": arm,
                    "features": [c["features"][k] for k in columns],
                    "scaler_mean": scaler.mean_.tolist(),
                    "scaler_scale": scaler.scale_.tolist(),
                    "svm_coef": clf.coef_.tolist(),
                    "svm_intercept": clf.intercept_.tolist(),
                    "sigmoid_coef": platt.coef_.tolist(),
                    "sigmoid_intercept": platt.intercept_.tolist(),
                    "iterations": int(clf.n_iter_),
                }
            )
        f["status"] = "fit"
        folds.append(f)
        print("fit", testrepo, len(fit), len(cal), len(test), flush=True)
    np.savez_compressed(H / "predictions.npz", **preds)
    metric = {}
    for arm, v in preds.items():
        ix = [i for i in known if np.isfinite(v[i])]
        count = collections.Counter(g[ix])
        weights = [1 / count[g[i]] for i in ix]
        yy = Y[ix]
        pp = v[ix]
        metric[arm] = {
            "known_pairs": len(ix),
            "source_components": len(count),
            "component_weighted_brier": float(brier_score_loss(yy, pp, sample_weight=weights)) if ix else None,
            "component_weighted_log_loss": float(log_loss(yy, pp, sample_weight=weights, labels=[0, 1]))
            if ix
            else None,
            "auc": float(roc_auc_score(yy, pp)) if len(set(yy)) == 2 else None,
            "calibration_bins": [],
        }
        for low, high in zip([0, 0.2, 0.4, 0.6, 0.8], [0.2, 0.4, 0.6, 0.8, 1.01]):
            j = [i for i in ix if low <= v[i] < high]
            metric[arm]["calibration_bins"].append(
                {
                    "range": [low, high],
                    "count": len(j),
                    "mean_score": float(np.mean(v[j])) if j else None,
                    "observed_fraction": float(np.mean(Y[j])) if j else None,
                }
            )
    groups_by_query = collections.defaultdict(list)
    for i, r in enumerate(rows):
        for d in r["directions"]:
            groups_by_query[r["cohort_id"], d["query"]].append(i)
    scores = preds | {"tfidf": X[:, 0], "fixed_fusion": np.array([r["fixed_fusion"] for r in rows])}
    budgets = []
    # Fair common query universe where all learned scores are available; no unknown-label filtering.
    common = {k: ids for k, ids in groups_by_query.items() if all(np.isfinite(preds["svm"][i]) for i in ids)}
    for arm, v in scores.items():
        for budget in c["budgets"]:
            selected = set()
            directions = 0
            chars = 0
            for key, ids in common.items():
                chosen = sorted(ids, key=lambda i: (-v[i], rows[i]["pair_id"]))[:budget]
                selected.update(chosen)
                directions += len(chosen)
            # Exact source characters computed separately; line-based burden here explicitly only a proxy.
            lineburden = sum(np.expm1(X[i, 5]) + np.expm1(X[i, 6]) for i in selected)
            budgets.append(
                {
                    "arm": arm,
                    "leads_per_selected_query": budget,
                    "queries": len(common),
                    "directional_leads": directions,
                    "full_source_line_proxy_no_read_reuse": float(lineburden),
                    "outcomes": summarize(rows, selected),
                    "per_repository": {r: summarize(rows, [i for i in selected if repo[i] == r]) for r in repos},
                }
            )
    write(
        "MODELS.json",
        {
            "folds": folds,
            "parameters": models,
            "seed_feature_isolation": "Seed labels restricted to same fit/calibration/test role; target pair always excluded. No calibration outcome enters fit features.",
            "calibration_interpretation": "Held-calibration sigmoid within selected source labels; not deployment base-rate probability. Margins never probabilities. No case-control prevalence correction possible without inclusion probabilities.",
        },
    )
    write("MODEL-METRICS.json", metric)
    write("BUDGETS.json", budgets)
    byrepo = {r: summarize(rows, np.where(repo == r)[0]) for r in repos}
    write(
        "RESULTS.json",
        {
            "schema": 1,
            "rows": n,
            "known_pairs": len(known),
            "known_source_components": len(set(g[known])),
            "repositories": byrepo,
            "seconds": time.monotonic() - tick,
            "contract_sha256": sha(H / "EXPERIMENT-CONTRACT.json"),
            "script_sha256": sha(__file__),
            "p_values": None,
            "reason_no_p_values": c["null_protocol"],
            "oracle_lift_risk_difference": lift["matching_oracle"]["risk_difference"],
            "calibration": metric,
            "actual_prior_judge_seed_lift": "Pending separate exact observation ingestion; not assumed zero.",
        },
    )
    write(
        "SPLIT-ASSIGNMENTS.json",
        {
            "outer": "leave-one-repository-out; shared source component exclusion",
            "rows": [
                {
                    "pair_id": rows[i]["pair_id"],
                    "repository": repo[i],
                    "source_group": g[i],
                    "inner_role": "calibration"
                    if int(hashlib.sha256(g[i].encode()).hexdigest(), 16) % 4 == 0
                    else "fit",
                    "label": int(Y[i]),
                }
                for i in known
            ],
        },
    )
    print("complete", n, len(known), "matched", lift["matching_oracle"]["matched"], flush=True)


if __name__ == "__main__":
    main()
