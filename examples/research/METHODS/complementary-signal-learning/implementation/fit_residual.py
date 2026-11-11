# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B905, E401, E402, E741, I001
"""One fixed regularized residual ranker; no hyperparameter search or unknown negatives."""

import os

for k in ["OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"]:
    os.environ[k] = "2"
import pathlib, json, collections, hashlib, time
import numpy as np
import sklearn, joblib
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

H = pathlib.Path(__file__).resolve().parent


def jl(p):
    with pathlib.Path(p).open() as f:
        return [json.loads(l) for l in f if l.strip()]


def write(p, d):
    pathlib.Path(p).write_text(json.dumps(d, indent=2, sort_keys=True) + "\n")


def group(repo):
    return (
        "due-backend-lineage"
        if repo in ["gigaverse-app/due", "gigaverse-app/backend-common", "gigaverse-app/gigaverse-backend"]
        else repo
    )


def main():
    start = time.monotonic()
    meta = json.loads((H / "RESIDUAL-INPUTS.json").read_text())
    contract = json.loads((H / "SPLIT-CONTRACT.json").read_text())
    inventory = jl(contract["inventory_rows_path"])
    train = jl(H / "residual-training.jsonl")
    X = np.load(H / "residual-training.npy")
    y = np.array([r["label"] for r in train])
    assert len(X) == len(y)
    forbidden = set(contract["holdout"]["exclude_connected_components"])
    assert not any(
        r["source_component"] in forbidden or r["repository"] == contract["holdout"]["repository"] for r in train
    )
    folds = []
    out = (H / "residual-predictions.jsonl").open("w")
    metrics = []
    case_results = []
    for held in sorted({group(p["repository"]) for p in meta["arrays"]}):
        components = {r["component"] for r in inventory if group(r["repository"]) == held}
        ti = np.array(
            [
                i
                for i, r in enumerate(train)
                if group(r["repository"]) != held and r["source_component"] not in components
            ],
            np.int64,
        )
        positive = {train[i]["source_component"] for i in ti if y[i]}
        negative = {train[i]["source_component"] for i in ti if not y[i]}
        fold = {
            "held_repository_group": held,
            "training_directions": len(ti),
            "positive_components": len(positive),
            "negative_components": len(negative),
            "excluded_source_components": len(components),
            "component_overlap": 0,
            "status": "insufficient_training",
            "train_indices": ti.tolist(),
        }
        if len(ti) >= 20 and len(positive) >= 2 and len(negative) >= 2:
            counts = collections.Counter(train[i]["source_component"] for i in ti)
            weights = np.array([1 / counts[train[i]["source_component"]] for i in ti])
            weights *= len(weights) / weights.sum()
            model = make_pipeline(
                StandardScaler(), LogisticRegression(C=0.1, max_iter=1000, solver="lbfgs", random_state=917)
            )
            model.fit(X[ti], y[ti], logisticregression__sample_weight=weights)
            path = H / "residual" / ("model-" + hashlib.sha256(held.encode()).hexdigest()[:12] + ".joblib")
            joblib.dump(model, path)
            fold.update(
                status="fitted",
                model=str(path),
                coefficients=dict(zip(meta["features"], model[-1].coef_[0].tolist())),
                intercept=float(model[-1].intercept_[0]),
            )
        for p in meta["arrays"]:
            if group(p["repository"]) != held:
                continue
            with np.load(p["path"]) as z:
                data = {k: z[k] for k in z.files}
            pred = model.decision_function(data["X"]) if fold["status"] == "fitted" else np.full(len(data["X"]), np.nan)
            np.save(pathlib.Path(p["path"]).with_name("residual-scores.npy"), pred)
            for i, score in enumerate(pred):
                out.write(
                    json.dumps(
                        {
                            "candidate_id": str(data["candidate_id"][i]),
                            "cohort_id": p["cohort_id"],
                            "query_position": int(data["query"][i]),
                            "target_position": int(data["target"][i]),
                            "residual_rank_score": float(score) if np.isfinite(score) else None,
                            "baseline_known": bool(data["baseline_known"][i]),
                            "baseline_admitted": bool(data["baseline_admitted"][i]),
                            "residual_eligible": bool(data["baseline_known"][i] and not data["baseline_admitted"][i]),
                            "fold": held,
                            "availability": fold["status"],
                            "calibrated_probability": False,
                        }
                    )
                    + "\n"
                )
            # Fixed versus learned ranking uses the identical baseline-missed bank.
            test = {(r["query"], r["target"]): r for r in train if r["cohort_id"] == p["cohort_id"]}
            for q in np.unique(data["query"]):
                ids = np.flatnonzero((data["query"] == q) & data["baseline_known"] & ~data["baseline_admitted"])
                if not len(ids):
                    continue
                orders = {
                    name: ids[np.argsort(-score[ids], kind="stable")]
                    for name, score in [("fixed", data["fixed"]), ("residual", pred)]
                    if name != "residual" or fold["status"] == "fitted"
                }
                ranks = {
                    name: {int(data["target"][i]): j + 1 for j, i in enumerate(order)} for name, order in orders.items()
                }
                for (qq, t), r in test.items():
                    if qq == int(q):
                        case_results.append(
                            r
                            | {"ranks": {name: rr.get(t) for name, rr in ranks.items()}, "fold_status": fold["status"]}
                        )
        folds.append(fold)
    out.close()
    with (H / "residual-case-outcomes.jsonl").open("w") as f:
        for r in case_results:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    for repo in sorted({r["repository"] for r in case_results}):
        for label in [0, 1]:
            rs = [
                r
                for r in case_results
                if r["repository"] == repo and r["label"] == label and r["fold_status"] == "fitted"
            ]
            if not rs:
                continue
            for cap in [4, 20]:
                for arm in ["fixed", "residual"]:
                    hits = [r for r in rs if r["ranks"].get(arm, 10**8) <= cap]
                    metrics.append(
                        {
                            "repository": repo,
                            "label": "duplicate" if label else "separate",
                            "arm": arm,
                            "cap": cap,
                            "baseline_missed_directions": len(rs),
                            "hits": len(hits),
                            "components": len({r["source_component"] for r in rs}),
                            "hit_components": len({r["source_component"] for r in hits}),
                        }
                    )
    write(
        H / "RESIDUAL-RESULTS.json",
        {
            "schema": 1,
            "sklearn": sklearn.__version__,
            "recipe": "standardized logistic C=.1; equal connected-component total sample weight; no class rebalancing; decision score only",
            "training_directions": len(train),
            "training_positive_directions": int(y.sum()),
            "folds": folds,
            "metrics": metrics,
            "seconds": time.monotonic() - start,
            "limitations": [
                "Training coverage is existing exact native current-stack captures only, not all58backgrounds.",
                "Accepted binary labels proxy previously reviewed useful duplication; source-assessment utility and provider observations are not training truth.",
                "Case-control selection bias remains; learned scores are not probabilities or expected dollars.",
                "Historical source repetition and prototype choice make this grouped development evidence. OpenCode outcomes remain embargoed.",
            ],
        },
    )
    print(
        "fitted",
        sum(f["status"] == "fitted" for f in folds),
        "of",
        len(folds),
        "folds",
        round(time.monotonic() - start, 2),
        "seconds",
    )


if __name__ == "__main__":
    main()
