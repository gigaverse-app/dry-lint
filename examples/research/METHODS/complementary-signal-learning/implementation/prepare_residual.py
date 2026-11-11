# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, E402, E731, E741, F841, I001
"""Join independent retrieval labels to exact native baseline admission recordings.
No labels enter candidate generation; never infer labels from provider answers.
"""

from _recovery_paths import recovery_path
import pathlib, json, collections, hashlib, os

for k in ["OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"]:
    os.environ[k] = "2"
import numpy as np

H = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path(recovery_path(""))
BASE = ROOT / "jobs/encoder-corpus-evaluation/.lab-results"


def jl(p):
    with pathlib.Path(p).open() as f:
        return [json.loads(l) for l in f if l.strip()]


def write(p, d):
    p = pathlib.Path(p)
    p.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in d)
        if p.suffix == ".jsonl"
        else json.dumps(d, indent=2, sort_keys=True) + "\n"
    )


def sha(p):
    with pathlib.Path(p).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


NAMES = [
    "tfidf_score",
    "minilm_score",
    "tail_score",
    "block_score",
    "containment_score",
    "sparse_reciprocal_rank",
    "dense_family_reciprocal_rank",
    "block_reciprocal_rank",
    "containment_reciprocal_rank",
    "shared_api_log",
    "contract_jaccard",
    "length_ratio",
    "query_lines_log",
    "target_lines_log",
    "same_file",
    "same_name",
    "minilm_available",
    "tail_available",
    "block_supported",
    "contract_available",
    "adapter_forwarding_available",
    "direct_call_name_overlap",
]


def vector(r):
    f = r["features"]
    rr = lambda name: 1 / (60 + f.get(name + "_rank", 10**8))
    return [
        f["tfidf_score"],
        f.get("minilm_score", 0),
        max(0, f.get("tail_score", 0)),
        f.get("block_score", 0),
        f.get("containment_score", 0),
        rr("tfidf"),
        max(rr("minilm"), rr("tail") if f.get("tail_score", -1) >= 0.8 else 0),
        rr("block") if f.get("block_score", 0) > 0 else 0,
        rr("containment") if r["routes"]["containment"] else 0,
        np.log1p(f["shared_api_tokens"]),
        f["contract_jaccard"],
        f["length_ratio"],
        np.log1p(f["query_lines"]),
        np.log1p(f["target_lines"]),
        float(f["same_file"]),
        float(f["same_name"]),
        float(f["minilm_available"]),
        float(f["tail_available"]),
        float(f["block_supported"]),
        float(f["contract_available"]),
        float(bool(f["forwarding_target_new"] or f["forwarding_target_existing"])),
        float(f["direct_call_name_overlap"]),
    ]


def main():
    contract = json.loads((H / "SPLIT-CONTRACT.json").read_text())
    excluded = set(contract["holdout"]["exclude_connected_components"])
    held = contract["holdout"]["repository"]
    inventory = {r["row_id"]: r for r in jl(contract["inventory_rows_path"])}
    manifest = json.loads((H / "BANK-MANIFEST.json").read_text())
    completed = json.loads((BASE / "WATCHER.json").read_text())["completed"]
    available = {}
    for r in sorted(completed.values(), key=lambda r: r["completed_unix"], reverse=True):
        folder = pathlib.Path(r["native_run"])
        cid = r["panel"]
        if cid not in available and (folder / "RUN.json").exists():
            available[cid] = folder
    if (H / "RESIDUAL-INPUTS.json").exists():
        frozen = json.loads((H / "RESIDUAL-INPUTS.json").read_text())
        available = {r["cohort_id"]: pathlib.Path(r["path"]).parent for r in frozen["captures"]}
        for r in frozen["captures"]:
            assert sha(r["path"]) == r["sha256"]
    bindings = {}
    training = []
    trainX = []
    captures = []
    missing = []
    arrays = []
    for p in manifest["backgrounds"]:
        cid = p["cohort_id"]
        repo = p["repository"]
        if repo == held:
            continue
        dest = H / "residual" / cid
        dest.mkdir(parents=True, exist_ok=True)
        captured = {}
        if cid in available:
            folder = available[cid]
            meta = json.loads((folder / "RUN.json").read_text())
            assert (
                meta["panel"]["background_sha256"] == p["source"]["background_sha256"]
                and meta["panel"]["functions_sha256"] == p["source"]["functions_sha256"]
            )
            for cap in jl(folder / "campaigns.jsonl"):
                if len(cap["query_positions"]) == 1 and "minilm_stack" in cap["arms"]:
                    q = cap["query_positions"][0]
                    cs = cap["arms"]["minilm_stack"]
                    admitted = {e["key"] for e in cap["native"]["minilm_stack"]["events"] if e["admitted"]}
                    pairs = {}
                    for c in cs:

                        def ident(f):
                            return f["path"] + "::" + ((f.get("owner") + ".") if f.get("owner") else "") + f["name"]

                        a, b = sorted([ident(c["new"]), ident(c["existing"])])
                        ck = hashlib.sha256((a + "\n" + b).encode()).hexdigest()[:16]
                        pairs[ck] = (a, b)
                    assert admitted <= pairs.keys()
                    captured[q] = {"capture": cap, "admitted_pairs": {pairs[k] for k in admitted}}
            captures.append(
                {
                    "cohort_id": cid,
                    "path": str(folder / "campaigns.jsonl"),
                    "sha256": sha(folder / "campaigns.jsonl"),
                    "queries": len(captured),
                }
            )
        else:
            missing.append(cid)
        targets = jl(H / "bank" / cid / "targets.jsonl")
        labels = collections.defaultdict(list)
        for r in targets:
            meta = inventory[r["row_id"]]
            if (
                not r["canonical_evaluation"]
                or not r["accepted_gold"]
                or not r.get("calibration_eligible", True)
                or r["label"] not in ["duplicate", "separate"]
                or meta["component"] in excluded
            ):
                continue
            a, b = r["query_positions"]
            for q, t in [(a, b), (b, a)]:
                labels[q, t].append((r, meta))
        X = []
        ids = []
        qs = []
        ts = []
        known = []
        baseline = []
        fixed = []
        conditional = []
        for row in jl(H / "bank" / cid / "candidates.jsonl"):
            if not row["native_eligible"]:
                continue
            q, t = row["query_position"], row["target_position"]
            cap = captured.get(q)
            isbase = (
                None
                if cap is None
                else tuple(sorted([row["source"]["query"]["source_id"], row["source"]["target"]["source_id"]]))
                in cap["admitted_pairs"]
            )
            x = vector(row)
            i = len(X)
            X.append(x)
            ids.append(row["candidate_id"])
            qs.append(q)
            ts.append(t)
            known.append(cap is not None)
            baseline.append(bool(isbase))
            fixed.append(row["scores"]["fixed_fusion"])
            conditional.append(row["scores"]["conditional"] if row["scores"]["conditional"] is not None else np.nan)
            rs = labels.get((q, t), [])
            if cap is None or isbase or not rs or len({r["label"] for r, m in rs}) != 1:
                continue
            r, m = rs[0]
            training.append(
                {
                    "cohort_id": cid,
                    "repository": repo,
                    "index": i,
                    "query": q,
                    "target": t,
                    "candidate_id": row["candidate_id"],
                    "label": int(r["label"] == "duplicate"),
                    "source_component": m["component"],
                    "row_ids": [r["row_id"] for r, m in rs],
                    "baseline": "exact native admitted minilm_stack",
                    "canonical": True,
                }
            )
            trainX.append(x)
        np.savez_compressed(
            dest / "features.npz",
            X=np.asarray(X, np.float32),
            query=np.asarray(qs, np.int32),
            target=np.asarray(ts, np.int32),
            candidate_id=np.asarray(ids),
            baseline_known=np.asarray(known),
            baseline_admitted=np.asarray(baseline),
            fixed=np.asarray(fixed),
            conditional=np.asarray(conditional),
        )
        arrays.append(
            {
                "cohort_id": cid,
                "repository": repo,
                "path": str(dest / "features.npz"),
                "rows": len(X),
                "native_baseline_queries": len(captured),
            }
        )
    np.save(H / "residual-training.npy", np.asarray(trainX, np.float32))
    write(H / "residual-training.jsonl", training)
    write(
        H / "RESIDUAL-INPUTS.json",
        {
            "schema": 1,
            "features": NAMES,
            "arrays": arrays,
            "captures": captures,
            "missing_baseline_backgrounds": missing,
            "training_directions": len(training),
            "training_positive_directions": sum(r["label"] for r in training),
            "training_positive_components": len({r["source_component"] for r in training if r["label"]}),
            "training_negative_components": len({r["source_component"] for r in training if not r["label"]}),
            "split_sha256": sha(H / "SPLIT-CONTRACT.json"),
            "script_sha256": sha(__file__),
            "source_labels_not_used_as_negatives": True,
            "conditioning": "absence from native admitted current-stack campaign, not absence from TFIDF top4",
        },
    )
    print(
        "training directions",
        len(training),
        "positives",
        sum(r["label"] for r in training),
        "arrays",
        len(arrays),
        "native captures",
        len(captures),
    )


if __name__ == "__main__":
    main()
