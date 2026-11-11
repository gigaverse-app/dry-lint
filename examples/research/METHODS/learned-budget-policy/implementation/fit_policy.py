# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B905, E401, F403, F405, I001
from policy_common import *
import numpy as np, time, collections, resource
import sklearn, joblib
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import brier_score_loss, roc_auc_score


def main():
    start = time.monotonic()
    cpu = time.process_time()
    inputs = json.loads((H / "INPUTS.json").read_text())
    train = jl(H / "training.jsonl")
    inventory = [r for r in jl(A / "inventory-rows.jsonl") if r["wave_role"] == "development"]
    arrays = {}
    for a in inputs["arrays"]:
        with np.load(a["path"]) as z:
            arrays[a["cohort_id"]] = z["X"]
    X = np.array([arrays[r["cohort_id"]][r["index"]] for r in train])
    y = np.array([r["label"] for r in train])
    folds = []
    oof = []
    for held in sorted({group(a["repository"]) for a in inputs["arrays"]}):
        purge = {r["component"] for r in inventory if group(r["repository"]) == held}
        pool = [i for i, r in enumerate(train) if group(r["repository"]) != held and r["source_component"] not in purge]
        cal = [i for i in pool if int(digest(train[i]["source_component"])[:8], 16) % 4 == 0]
        fit = [i for i in pool if i not in set(cal)]
        assert set(train[i]["source_component"] for i in fit).isdisjoint(train[i]["source_component"] for i in cal)
        counts = collections.Counter(train[i]["source_component"] for i in fit)
        w = np.array(
            [
                (1 if train[i]["kind"] == "accepted_operation_binary" else 0.5) / counts[train[i]["source_component"]]
                for i in fit
            ]
        )
        w *= len(w) / w.sum()
        models = [
            make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=1000, random_state=917)),
            HistGradientBoostingClassifier(
                max_iter=80,
                max_leaf_nodes=7,
                max_depth=3,
                min_samples_leaf=15,
                l2_regularization=10,
                learning_rate=0.05,
                early_stopping=False,
                random_state=917,
            ),
        ]
        models[0].fit(X[fit], y[fit], logisticregression__sample_weight=w)
        models[1].fit(X[fit], y[fit], sample_weight=w)
        calibrators = []
        for model in models:
            raw = model.decision_function(X[cal]).reshape(-1, 1)
            counts = collections.Counter(train[i]["source_component"] for i in cal)
            cw = np.array([1 / counts[train[i]["source_component"]] for i in cal])
            cw *= len(cw) / cw.sum()
            calibrator = LogisticRegression(C=1, max_iter=1000).fit(raw, y[cal], sample_weight=cw)
            calibrators.append(calibrator)
        path = H / "models" / (digest(held)[:12] + ".joblib")
        path.parent.mkdir(exist_ok=True)
        joblib.dump({"models": models, "calibrators": calibrators, "features": FEATURES}, path)
        fold = {
            "held_repository_group": held,
            "fit_rows": len(fit),
            "calibration_rows": len(cal),
            "fit_positive_components": len({train[i]["source_component"] for i in fit if y[i]}),
            "fit_negative_components": len({train[i]["source_component"] for i in fit if not y[i]}),
            "fit_components": sorted({train[i]["source_component"] for i in fit}),
            "calibration_components": sorted({train[i]["source_component"] for i in cal}),
            "purged_components": sorted(purge),
            "model": str(path),
            "linear_coefficients": dict(zip(FEATURES, models[0][-1].coef_[0].tolist())),
        }
        for a in inputs["arrays"]:
            if group(a["repository"]) != held:
                continue
            xx = arrays[a["cohort_id"]]
            pp = np.array(
                [c.predict_proba(m.decision_function(xx).reshape(-1, 1))[:, 1] for m, c in zip(models, calibrators)]
            ).T
            np.save(pathlib.Path(a["path"]).with_name("scores.npy"), pp)
            for r in train:
                if r["cohort_id"] == a["cohort_id"]:
                    oof.append(
                        {
                            **r,
                            "linear": float(pp[r["index"], 0]),
                            "interaction": float(pp[r["index"], 1]),
                            "combined": float(pp[r["index"]].mean()),
                            "outer_fold": held,
                        }
                    )
        folds.append(fold)
        write(
            H / "FIRST-SCORES.json",
            {
                "status": "partial"
                if len(folds) < len({group(a["repository"]) for a in inputs["arrays"]})
                else "complete",
                "completed_folds": len(folds),
                "scored_training_rows": len(oof),
                "seconds": time.monotonic() - start,
                "last_fold": {
                    k: v
                    for k, v in fold.items()
                    if k not in ["linear_coefficients", "fit_components", "calibration_components", "purged_components"]
                },
                "scope": "outer-held source-grouped development scores, not emitted reports",
            },
        )
        print(held, len(fit), len(cal), fold["fit_positive_components"], flush=True)
    metrics = []
    for kind in ["accepted_operation_binary", "source_operation_utility"]:
        rs = [r for r in oof if r["kind"] == kind]
        for arm in ["linear", "interaction", "combined"]:
            metrics.append(
                {
                    "kind": kind,
                    "arm": arm,
                    "rows": len(rs),
                    "positive": sum(r["label"] for r in rs),
                    "brier": brier_score_loss([r["label"] for r in rs], [r[arm] for r in rs]),
                    "auc": roc_auc_score([r["label"] for r in rs], [r[arm] for r in rs]),
                }
            )
    write(H / "OOF.jsonl", oof)
    write(
        H / "FIT-RESULTS.json",
        {
            "folds": folds,
            "metrics": metrics,
            "seconds": time.monotonic() - start,
            "cpu_seconds": time.process_time() - cpu,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "sklearn": sklearn.__version__,
            "recipe_sha256": sha(H / "POLICY-CONTRACT.json"),
            "calibration_limit": "Brier/AUC on selected labeled development cases only. Not prevalence or unseen-proposal calibration.",
        },
    )


if __name__ == "__main__":
    main()
