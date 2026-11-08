"""Local publication export. Original evidence is read-only; no network or providers."""

import hashlib
import importlib.metadata
import json
import shutil
import subprocess
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
LAB = PACKAGE.parent
ROOT = LAB.parents[2]
REV = "73709fdbe884c107b665400a186cb71caecc03f7"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def main():
    for name in ["data", "expected", "provenance", "harness", "worked-cases", "licenses"]:
        (PACKAGE / name).mkdir(exist_ok=True)
    source_provenance = []
    for method in ("blocks", "cpu"):
        path = LAB / (method + "-regression.jsonl")
        rows = read(path)
        for row in rows:
            if method == "cpu":
                for d in row["directions"]:
                    d.pop("query_views", None)
                    d.pop("target_views", None)
        jsonl(PACKAGE / "data" / path.name, rows)
        source_provenance.append(
            {
                "source": path.name,
                "original_sha256": sha(path.read_bytes()),
                "export_sha256": sha((PACKAGE / "data" / path.name).read_bytes()),
                "transformation": "Only CPU query_views/target_views removed; labels, mappings, scores, ranks, first losses and funding unchanged."
                if method == "cpu"
                else "byte-exact",
            }
        )
    for name in ["regression-table.jsonl", "regression-table.csv", "stage-counts.jsonl", "direction-table.jsonl"]:
        shutil.copyfile(LAB / name, PACKAGE / "expected" / name)
    material = json.loads((LAB / "materialized-background-manifest.json").read_text())
    contexts = []
    for m in material["backgrounds"]:
        co = {
            k: m[k]
            for k in [
                "cohort_id",
                "profiles",
                "functions",
                "scope",
                "max_df",
                "extraction_contract",
                "python_version",
                "functions_jsonl_sha256",
                "policy_sha256",
                "source_proof_sha256",
            ]
        }
        co["repository"] = {"repository": m["repository"]["repository"], "revision": m["repository"]["revision"]}
        co["background_sha256"] = m["repository"]["background_proof"]["sha256"]
        co["background_required_at_original_location"] = m["repository"]["background_proof"]["path"]
        co["git_required_at_original_location"] = m["repository"]["git"]
        contexts.append(co)
    jsonl(PACKAGE / "data/contexts.jsonl", contexts)
    labels = []
    for r in read(LAB / "selected-rows.jsonl"):
        labels.append(
            {
                k: r.get(k)
                for k in [
                    "row_id",
                    "pair_id",
                    "dataset",
                    "label",
                    "accepted_gold",
                    "pair_lineage",
                    "repository",
                    "revision",
                    "canonical_source_ids",
                ]
            }
        )
    jsonl(PACKAGE / "data/labels.jsonl", labels)
    names = [
        "common.py",
        "materialize.py",
        "blocks.py",
        "cpu.py",
        "helper_fallback_v1.py",
        "trace.py",
        "harness.py",
        "views.py",
        "checks.py",
        "final_check.py",
        "verify_contract.py",
        "freeze_inputs.py",
        "summarize.py",
        "reproduce.sh",
        "run-python",
    ]
    harness = []
    for name in names:
        body = (LAB / name).read_bytes()
        (PACKAGE / "harness" / name).write_bytes(body)
        harness.append({"path": "harness/" + name, "source_sha256": sha(body), "bytes": len(body), "modified": False})
    shutil.copytree(LAB / "frozen-pr109", PACKAGE / "harness/frozen-pr109", dirs_exist_ok=True)
    for name in [
        "frozen-source-manifest.json",
        "input-proofs.json",
        "runtime-summary.json",
        "checks.json",
        "cpu-contract-check.json",
        "final-check.json",
        "cpu-replay-parity.json",
    ]:
        shutil.copyfile(LAB / name, PACKAGE / "provenance" / name)
    dump(
        PACKAGE / "provenance/export.json",
        {
            "source_revision": REV,
            "source_results": source_provenance,
            "harness": harness,
            "historical_labels": "Inherited observed labels; no new judging. Private-historical400 aliases preserve lineage of public-source panel rows; no private source payload or broader private corpus is exported.",
            "omitted": "Full BenchBackground sparse rows, native corpus caches, model weights, vectors and SQLite cache. CPU source views removed from recordings; worked-case full source is separately licensed.",
        },
    )
    deps = {
        n: importlib.metadata.version(n)
        for n in [
            "pydantic",
            "numpy",
            "onnxruntime",
            "tokenizers",
            "tree-sitter",
            "tree-sitter-typescript",
            "httpx",
            "httpx2",
        ]
    }
    dump(
        PACKAGE / "provenance/dependencies.json",
        {
            "recorded_replay": "Python 3.11+ standard library only",
            "native_rerun_python": material["backgrounds"][0]["python_version"],
            "native_packages": deps,
            "original_interpreter": "/home/researcher/dry-lint-round/retrieval/.venv/bin/python",
            "numeric_site_packages": "/home/researcher/dry-lint-round/jobs/experiment-cpu-embeddings/.lab-results/venv/lib/python3.14/site-packages",
        },
    )
    enc = json.loads((LAB / "encoding-summary.json").read_text())["cohorts"][0]["encoder_contract"]
    dump(
        PACKAGE / "provenance/policies.json",
        {
            "schema": 1,
            "baseline_revision": REV,
            "scope": "14 exact backgrounds; 9 pins; 75 lineage rows; 115 row/background mappings; 230 directions per method. Do not combine scopes into an IDF fit or call correlated mappings independent cases.",
            "fit": "Frozen full-background sparse counts, order, document frequencies and max_df=.3. Self excluded; unavailable-native competitors retain sparse rows. All native sources available here.",
            "tfidf_baseline": {
                "neighbours": 3,
                "same_file": False,
                "floor_below_6_lines": 0.3,
                "floor_otherwise": 0.5,
                "size_ratio_filter": None,
            },
            "tfidf_wide": {"neighbours": 20, "floor": 0.35, "same_file": True, "first_route_ownership": True},
            "blocks": {
                "native_source": "harness/frozen-pr109/src/dry_lint/operation_blocks.py",
                "min_region_lines": 4,
                "max_region_lines": 80,
                "behaviour_nodes": [20, 400],
                "original_max_regions": 12,
                "max_anchors": 8,
                "max_postings": 64,
                "max_parents": 64,
                "min_shared_operations": 3,
                "min_shared_calls": 2,
                "whole_function_floor": 0.1,
                "region_floor": 0.65,
                "added_neighbours": 1,
            },
            "helper": {
                "recipe": "harness/helper_fallback_v1.py",
                "sha256": sha((LAB / "helper_fallback_v1.py").read_bytes()),
                "rule": "One bounded complete body, excluding nested owners; use original winners first; fallback only after original abstention. Research recipe v1, not unmeasured production version2.",
            },
            "cpu": {
                "encoder": enc,
                "prefix_floor": 0.65,
                "added_neighbours": 1,
                "fallback_floor": 0.8,
                "views": "At most two complete native statement spans beyond truncated prefix; 48..180 wordpieces; function name prefix; input <=256 tokens; largest then largest disjoint; stable source order.",
                "recipe": "harness/views.py + harness/harness.py; fallback only when original prefix has no new eligible pair",
            },
            "funding": {
                "per_query_cap_usd": 0.04,
                "simulation": "Cold single-function change; normal fixed price estimates, no physical cache discounts. Paired uses shared-operations Sonnet 5.5 plus contextual Jev; concept standalone also retained in blocks recordings. Exact charge implementation and prompt policy in archived harness/frozen source. Not a live PR ledger or an emitted verdict.",
                "pricing_source": "harness/frozen-pr109/src/dry_lint/costs.py",
            },
            "table_units": "Pair units deduplicate lineage at (method, background, label, pair_id). Direction units retain both query directions for each pair unit. Inventory labels retain all 75 rows; evaluated recordings retain all 115 row/background mappings.",
        },
    )
    selected_ids = {
        "original-pytest-obligation:reply-lifetime-before",
        "original-pytest-obligation:reply-lifetime-after",
        "original-pytest-selective:7",
    }
    worked = []
    licensed = []
    for r in read(LAB / "blocks-regression.jsonl"):
        if r["row_id"] not in selected_ids:
            continue
        m = next(m for m in material["backgrounds"] if m["cohort_id"] == r["cohort_id"])
        folder = Path(m["folder"])
        fs = read(folder / "functions.jsonl")
        proof = read(folder / "source-proof.jsonl")
        repo = m["repository"]["git"]
        rev = m["repository"]["revision"]
        short = rev[:8]
        slug = r["repository"].split("/")[-1]
        licensepath = "package/LICENSE" if slug == "pytest-obligation" else "LICENSE"
        licensebody = git(repo, "show", rev + ":" + licensepath)
        lic = PACKAGE / "licenses" / f"{slug}-{short}-LICENSE.txt"
        lic.write_bytes(licensebody)
        licensed.append(
            {
                "repository": r["repository"],
                "revision": rev,
                "source_path": licensepath,
                "export_path": str(lic.relative_to(PACKAGE)),
                "sha256": sha(licensebody),
                "license": "Apache-2.0",
            }
        )
        positions = {s["position"] for s in r["mapping"]["sources"].values()}
        if r["row_id"].endswith("reply-lifetime-after"):
            positions |= {i for i, f in enumerate(fs) if f["name"] == "counted_reply_breaker"}
        functions = []
        for i in sorted(positions):
            f = fs[i]
            p = proof[i]
            body = Path(p["source_file"]).read_bytes()
            assert sha(body) == p["file_sha256"] and sha(f["code"].encode()) == p["source_sha256"]
            dest = PACKAGE / "worked-cases" / slug / short / f["path"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body)
            fun = PACKAGE / "worked-cases" / slug / short / (str(i) + "-function.txt")
            fun.write_bytes(f["code"].encode())
            functions.append(
                {
                    "source_id": p["id"],
                    "position": i,
                    "line": f["line"],
                    "end_line": f["end_line"],
                    "source_sha256": p["source_sha256"],
                    "file_sha256": p["file_sha256"],
                    "git_blob_sha1": p["git_blob_sha1"],
                    "full_file": str(dest.relative_to(PACKAGE)),
                    "full_function": str(fun.relative_to(PACKAGE)),
                    "license": str(lic.relative_to(PACKAGE)),
                }
            )
        worked.append(
            {
                "row_id": r["row_id"],
                "pair_id": r["pair_id"],
                "label": r["label"],
                "repository": r["repository"],
                "revision": rev,
                "cohort_id": r["cohort_id"],
                "functions": functions,
            }
        )
    dump(PACKAGE / "worked-cases/manifest.json", worked)
    drylicense = git(ROOT / "jobs/recall-promotion", "show", REV + ":LICENSE")
    (PACKAGE / "licenses/dry-lint-LICENSE.txt").write_bytes(drylicense)
    licensed.append(
        {
            "repository": "gigaverse-app/dry-lint",
            "revision": REV,
            "source_path": "LICENSE",
            "export_path": "licenses/dry-lint-LICENSE.txt",
            "sha256": sha(drylicense),
            "license": "Apache-2.0",
        }
    )
    dump(PACKAGE / "licenses/provenance.json", licensed)
    print("Exported recorded outcomes, exact harness, 14 contexts and", len(worked), "worked cases")


if __name__ == "__main__":
    main()
