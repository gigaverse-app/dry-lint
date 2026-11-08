# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, F403, F405, I001
"""Recompute frozen model predictions and allocations without providers or encoders."""

from policy_common import *
import argparse, time, resource
import numpy as np
import joblib
from allocate_policy import allocate
from guard_policy import guarded


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reproduction-policy-v1")
    a = ap.parse_args()
    out = (H / a.out).resolve()
    assert out.is_relative_to(H.resolve()) and not out.exists()
    out.mkdir()
    start = time.perf_counter()
    cpu = time.process_time()
    inputs = json.loads((H / "INPUTS.json").read_text())
    subset = json.loads((H / "COMPLETION-SUBSET.json").read_text())
    original = {(r["cohort_id"], r["query"]): r for r in jl(H / "selections.jsonl")}
    revised = {(r["cohort_id"], r["query"]): r for r in jl(H / "guard-selections.jsonl")}
    results = []
    provenance = []
    for campaign in subset["campaigns"]:
        cid, q = campaign["cohort_id"], campaign["query"]
        ar = next(r for r in inputs["arrays"] if r["cohort_id"] == cid)
        rows = jl(ar["metadata"])
        data = dict(np.load(ar["path"]))
        model_path = H / "models" / (digest(group(ar["repository"]))[:12] + ".joblib")
        model = joblib.load(model_path)
        assert model["features"] == FEATURES
        indices = np.flatnonzero(data["query"] == q)
        xx = data["X"][indices]
        pp = np.array(
            [
                c.predict_proba(m.decision_function(xx).reshape(-1, 1))[:, 1]
                for m, c in zip(model["models"], model["calibrators"], strict=True)
            ]
        ).T
        saved = np.load(pathlib.Path(ar["path"]).with_name("scores.npy"))
        max_error = float(np.max(np.abs(pp - saved[indices])))
        # Original feature matrices are float32; a smaller BLAS batch can differ
        # by one float32 rounding unit. Allocation order must still match exactly.
        assert max_error < 1e-7
        # Only this query is predicted; all allocation inputs are this query's rows.
        pred = np.full(len(rows), np.nan)
        pred[indices] = pp.mean(axis=1)
        ids = [int(i) for i in indices if data["eligible"][i]]
        plans = dict(
            raw_dollar=allocate(ids, rows, data, pred, mode="raw"),
            combined=allocate(ids, rows, data, pred),
            raw_native=allocate(ids, rows, data, pred, mode="raw", native=True),
            combined_native=allocate(ids, rows, data, pred, native=True),
            guarded=guarded(ids, rows, data, pred),
            guarded_native=guarded(ids, rows, data, pred, native=True),
        )
        arms = {}
        for arm, ii in plans.items():
            reference = revised[cid, q] if arm.startswith("guarded") else original[cid, q]
            assert ii == reference["indices"][arm], (cid, q, arm)
            charged = data["hold"] if arm.endswith("_native") else data["cost"]
            usd = sum(float(charged[i]) for i in ii)
            assert usd <= 0.04 + 1e-12
            arms[arm] = dict(
                count=len(ii),
                logical_charge_or_hold_usd=usd,
                source_lines=sum(rows[i]["source_lines"] for i in ii),
                candidate_ids=[rows[i]["candidate_id"] for i in ii],
                exact_frozen_order_match=True,
            )
        results.append(
            dict(
                cohort_id=cid,
                query=q,
                repository=ar["repository"],
                max_score_error=max_error,
                eligible_pool=len(ids),
                arms=arms,
            )
        )
        provenance.append(
            dict(
                cohort_id=cid,
                model={"path": str(model_path), "sha256": sha(model_path)},
                features={"path": ar["path"], "sha256": sha(ar["path"])},
                metadata={"path": ar["metadata"], "sha256": sha(ar["metadata"])},
            )
        )
    write(out / "results.jsonl", results)
    write(
        out / "REPRODUCTION.json",
        dict(
            schema=1,
            passed=True,
            campaigns=len(results),
            arms=sum(len(r["arms"]) for r in results),
            provider_calls=0,
            encoder_calls=0,
            seconds=time.perf_counter() - start,
            cpu_seconds=time.process_time() - cpu,
            peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            invocation_cwd=os.getcwd(),
            runtime_commit=REF,
            inputs=provenance,
            score_tolerance=1e-7,
            allocation_order_tolerance=0,
            scope="Recomputed held-repository model predictions and exact original/revised allocation orders from cached feature matrices. No Report outcome or source-family claim.",
            limitations="No feature recomputation or encoder cost measurement. External frozen corpus and sklearn environment required.",
        ),
    )
    print(json.dumps({"passed": True, "campaigns": len(results), "out": str(out)}))


if __name__ == "__main__":
    main()
