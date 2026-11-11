# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B023, E401, E402, E741, F403, F405, I001
from policy_common import *
import time, re, collections, resource
import numpy as np

sys.path.insert(0, str(B))
sys.path.insert(0, str(R))
from bank_loader import BankLoader
from native_harness import JUDGE
from dry_lint.costs import estimate
from dry_lint.discovery import reservation_cost


def calls(code):
    return set(re.findall(r"\b([A-Za-z_$][\w.$]*)\s*\(", code)) - {
        "if",
        "for",
        "while",
        "with",
        "return",
        "print",
        "len",
        "str",
        "int",
        "super",
    }


def main():
    start = time.monotonic()
    cpu = time.process_time()
    contract = json.loads((A / "SPLIT-CONTRACT.json").read_text())
    inv = {r["row_id"]: r for r in jl(A / "inventory-rows.jsonl") if r["wave_role"] == "development"}
    manifest = json.loads((B / "BANK-MANIFEST.json").read_text())
    arrays = []
    training = []
    cases = []
    source_positive = {"useful-extractable", "useful-bounded-extraction"}
    source_negative = {"already-shared", "related", "related/too-generic", "tiny-convenience", "separate"}
    for panel in manifest["backgrounds"]:
        cid = panel["cohort_id"]
        repo = panel["repository"]
        if repo == contract["holdout"]["repository"]:
            continue
        assert not any(x in repo.lower() for x in ["firecrawl", "curator"])
        dest = H / "arrays" / cid
        dest.mkdir(parents=True, exist_ok=True)
        targets = [
            r
            for r in jl(B / "bank" / cid / "targets.jsonl")
            if r["canonical_evaluation"] and r["row_id"] in inv and r["record_kind"] == "function"
        ]
        labels = collections.defaultdict(list)
        for t in targets:
            m = inv[t["row_id"]]
            label = t["label"]
            kind = None
            y = None
            if t["accepted_gold"] and label in ["duplicate", "separate"] and t.get("calibration_eligible", True):
                kind = "accepted_operation_binary"
                y = int(label == "duplicate")
            elif not t["accepted_gold"] and label in source_positive | source_negative:
                kind = "source_operation_utility"
                y = int(label in source_positive)
            a, b = t["query_positions"]
            case = {
                **t,
                "source_component": m["component"],
                "authority": m.get("authority"),
                "label_scope": m.get("label_scope"),
                "whole_function_label": m.get("whole_function_label"),
                "training_kind": kind,
                "utility_target": y,
            }
            cases.append(case)
            if kind:
                for q, k in [(a, b), (b, a)]:
                    labels[q, k].append(case)
        output = dest / "data.npz"
        metadata = dest / "rows.jsonl"
        if output.exists():
            arrays.append(json.loads((dest / "RECEIPT.json").read_text()))
            training += jl(dest / "training.jsonl")
            print("reuse", cid, flush=True)
            continue
        loader = BankLoader(cid)
        fs = loader.functions
        callsets = [calls(f.code) for f in fs]
        original_hash = loader.detector.hashed
        hash_cache = {}

        def cached_hash(f):
            key = id(f)
            if key not in hash_cache:
                hash_cache[key] = original_hash(f)
            return hash_cache[key]

        loader.detector.hashed = cached_hash
        rows = jl(D / "bank" / cid / "candidates.jsonl")
        rows = [r for r in rows if r["native_eligible"]]
        raw = np.array([[max(0, r["features"].get(k + "_score", 0)) for k in SCORES] for r in rows])
        mu = raw.mean(axis=0)
        sd = np.maximum(raw.std(axis=0), 0.01)
        X = []
        cost = []
        hold = []
        eligible = []
        minutes = []
        meta = []
        localtrain = []
        for i, r in enumerate(rows):
            f = r["features"]
            q, t = r["query_position"], r["target_position"]
            a, b = fs[q], fs[t]
            c = loader.candidate(r)
            normal = estimate(JUDGE, [c], loader.settings)
            native = reservation_cost(JUDGE, c, loader.settings)
            review = (f["query_lines"] + f["target_lines"]) / 60
            ca, cb = callsets[q], callsets[t]
            intersection = ca & cb
            x = (
                raw[i].tolist()
                + [np.log1p(min(f.get(k + "_rank", 100000), 100000)) for k in SCORES]
                + [np.log1p(min(f.get(k + "_cross_rank", 100000), 100000)) for k in SCORES]
                + ((raw[i] - mu) / sd).tolist()
            )
            x += [
                min(raw[i, 1], raw[i, 2]),
                abs(raw[i, 1] - raw[i, 2]),
                raw[i, 0] * raw[i, 1],
                np.log1p(f["shared_api_tokens"]),
                np.log1p(f["shared_idf_mass"]),
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
                float(bool(a.owner and a.owner == b.owner)),
                float(c.new.hash == c.existing.hash),
                len(intersection) / max(1, len(ca | cb)),
                len(intersection) / max(1, min(len(ca), len(cb))),
                np.log1p(normal * 1000),
                np.log1p(review),
            ]
            assert len(x) == len(FEATURES)
            X.append(x)
            cost.append(normal)
            hold.append(native)
            eligible.append(not bool(c.filtered))
            minutes.append(review)
            meta.append(
                {
                    "candidate_id": r["candidate_id"],
                    "query": q,
                    "target": t,
                    "key": c.key,
                    "query_source": a.qualname,
                    "target_source": b.qualname,
                    "query_sha": r["source"]["query"]["source_sha256"],
                    "target_sha": r["source"]["target"]["source_sha256"],
                    "shared_calls": sorted(intersection),
                    "target_calls": sorted(cb),
                    "owner": b.owner,
                    "filtered": c.filtered,
                    "tfidf_rank": f["tfidf_rank"],
                    "tfidf_cross_rank": f["tfidf_cross_rank"],
                    "block": f["block_score"],
                    "containment": f["containment_score"],
                    "normal": normal,
                    "reservation": native,
                    "source_lines": f["query_lines"] + f["target_lines"],
                    "same_file": f["same_file"],
                }
            )
            ls = labels[q, t]
            if ls and len({l["utility_target"] for l in ls}) == 1:
                best = sorted(ls, key=lambda l: l["training_kind"] != "accepted_operation_binary")[0]
                localtrain.append(
                    {
                        "cohort_id": cid,
                        "repository": repo,
                        "index": i,
                        "label": best["utility_target"],
                        "source_component": best["source_component"],
                        "kind": best["training_kind"],
                        "row_ids": [l["row_id"] for l in ls],
                        "label_scope": best["label_scope"],
                        "authority": best["authority"],
                    }
                )
        np.savez_compressed(
            output,
            X=np.array(X, np.float32),
            cost=np.array(cost),
            hold=np.array(hold),
            eligible=np.array(eligible),
            minutes=np.array(minutes),
            query=np.array([r["query"] for r in meta]),
            target=np.array([r["target"] for r in meta]),
            tfidf=raw[:, 0],
        )
        write(metadata, meta)
        write(dest / "training.jsonl", localtrain)
        training += localtrain
        rec = {
            "cohort_id": cid,
            "repository": repo,
            "revision": panel["revision"],
            "path": str(output),
            "metadata": str(metadata),
            "rows": len(rows),
            "native_eligible": sum(eligible),
            "bank_sha256": sha(D / "bank" / cid / "candidates.jsonl"),
            "source_sha256": panel["source"]["functions_sha256"],
            "feature_normalization_mean": mu.tolist(),
            "feature_normalization_std": sd.tolist(),
        }
        write(dest / "RECEIPT.json", rec)
        arrays.append(rec)
        write(
            H / "PREPARE-PROGRESS.json",
            {"completed": len(arrays), "seconds": time.monotonic() - start, "training": len(training)},
        )
        print(cid, len(rows), len(localtrain), round(time.monotonic() - start, 1), flush=True)
    write(H / "training.jsonl", training)
    write(H / "cases.jsonl", cases)
    write(
        H / "INPUTS.json",
        {
            "arrays": arrays,
            "features": FEATURES,
            "training_rows": len(training),
            "positive_components": len({r["source_component"] for r in training if r["label"]}),
            "negative_components": len({r["source_component"] for r in training if not r["label"]}),
            "kinds": dict(collections.Counter(r["kind"] for r in training)),
            "seconds": time.monotonic() - start,
            "cpu_seconds": time.process_time() - cpu,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "split_sha256": sha(A / "SPLIT-CONTRACT.json"),
            "contract_sha256": sha(H / "POLICY-CONTRACT.json"),
            "provider_calls": 0,
            "encoder_calls": 0,
        },
    )


if __name__ == "__main__":
    main()
