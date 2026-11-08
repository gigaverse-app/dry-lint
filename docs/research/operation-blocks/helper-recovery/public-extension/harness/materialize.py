"""Read only exact git objects, extract entire native functions, bind every sparse row."""

import collections
import subprocess
import time

from common import HERE, PR, ROOT, SHARED, BenchBackground, Path, dump, hashlib, json, jsonl, os, read, sha, sys

from dry_lint.extractors import PythonExtractor
from dry_lint.typescript import TypeScriptExtractor

RECEIPT = ROOT / "reports/research-experiments/improvement-wave/public-pin-acquisition.json"


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"},
    ).stdout


def main():
    started = time.perf_counter()
    receipt = json.loads(RECEIPT.read_text())
    roots = {r["repository"]: r for r in receipt}
    cs = read(SHARED / "cohorts.jsonl")
    rows = read(SHARED / "rows.jsonl")
    assert len(cs) == 79 and len(rows) == 617
    selected = [c for c in cs if c["repository"] in roots]
    assert len({(c["repository"], c["revision"]) for c in selected}) == 9
    coverage = {c["cohort_id"]: c for c in read(ROOT / "jobs/improve-cpu-retrieval/.lab-results/source-coverage.jsonl")}
    jsonl(HERE / "selected-cohorts.jsonl", selected)
    selected_ids = {c["cohort_id"] for c in selected}
    selected_rows = [r for r in rows if any(m["cohort_id"] in selected_ids for m in r["mappings"])]
    jsonl(HERE / "selected-rows.jsonl", selected_rows)
    source_dir = HERE / "source-files"
    source_dir.mkdir(exist_ok=True)
    cache = {}
    manifests = []
    for c in selected:
        root = roots[c["repository"]]["git"]
        rev = c["revision"]
        assert any(p["revision"] == rev and p["available"] for p in roots[c["repository"]]["pins"])
        assert git(root, "rev-parse", rev + "^{commit}").decode().strip() == rev
        raw = Path(c["background_path"]).read_bytes()
        assert sha(raw) == c["background_sha256"]
        bg = BenchBackground.decode(raw)
        assert (bg.repository, bg.revision) == (c["repository"], rev)
        folder = HERE / "cohorts" / c["background_sha256"]
        folder.mkdir(parents=True, exist_ok=True)
        matches = collections.defaultdict(list)
        files = {}
        warnings = []
        for path in dict.fromkeys(d.id.split("::", 1)[0] for d in bg.documents):
            # No checkout, target import, configuration execution, or non-source file reads.
            body = git(root, "show", rev + ":" + path)
            digest = sha(body)
            oid = git(root, "rev-parse", rev + ":" + path).decode().strip()
            assert hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest() == oid
            sp = source_dir / (digest + ".txt")
            if sp.exists():
                assert sp.read_bytes() == body
            else:
                sp.write_bytes(body)
            key = (path, digest)
            if key not in cache:
                extractor = PythonExtractor() if path.endswith(".py") else TypeScriptExtractor()
                warning = None
                try:
                    extractor.validate_source(path, body.decode())
                except ValueError as exc:
                    warning = str(exc)
                fs = extractor.functions(path, body.decode())
                for f in fs:
                    f.hash = extractor.structure_hash(f)
                cache[key] = (fs, warning)
            fs, warning = cache[key]
            if warning:
                warnings.append({"path": path, "warning": warning})
            files[path] = {
                "path": path,
                "file_sha256": digest,
                "git_blob_sha1": oid,
                "bytes": len(body),
                "source_file": str(sp),
            }
            for f in fs:
                matches[(f.qualname, sha(f.code.encode()))].append(f)
        functions = []
        policies = []
        proofs = []
        missing = []
        for i, d in enumerate(bg.documents):
            found = matches[(d.id, d.source_sha256)]
            path, qualified = d.id.split("::", 1)
            owner, _, name = qualified.rpartition(".")
            native = found[0] if len(found) == 1 else None
            unit = (
                native.model_dump(mode="json")
                if native
                else {
                    "path": path,
                    "name": name or qualified,
                    "owner": owner or None,
                    "line": 0,
                    "end_line": 0,
                    "code": found[0].code if found else "",
                }
            )
            functions.append(unit)
            policies.append(
                {
                    "position": i,
                    "function": unit if native else None,
                    "status": "exact_native" if native else "ambiguous_native" if found else "missing_exact_body",
                }
            )
            proof = {
                "row": i,
                "id": d.id,
                "background_sha256": d.source_sha256,
                "source_sha256": sha(unit["code"].encode()) if unit["code"] else None,
                "matching_native_symbols": len(found),
                "line": unit["line"],
                "end_line": unit["end_line"],
                **files[path],
            }
            proofs.append(proof)
            if not native:
                missing.append(proof)
            else:
                assert proof["source_sha256"] == d.source_sha256
        jsonl(folder / "functions.jsonl", functions)
        jsonl(folder / "functions-policy-resolver-v1.jsonl", policies)
        jsonl(folder / "source-proof.jsonl", proofs)
        repo = {
            "repository": bg.repository,
            "revision": rev,
            "git": root,
            "background_proof": {"path": c["background_path"], "sha256": c["background_sha256"]},
        }
        manifest = {
            "cohort_id": c["cohort_id"],
            "repository": repo,
            "profiles": c["profiles"],
            "functions": len(bg.documents),
            "matched_functions": sum(p["function"] is not None for p in policies),
            "missing": missing,
            "scope": bg.scope,
            "max_df": bg.max_df,
            "extraction_contract": bg.extraction_contract,
            "python_version": sys.version,
            "native_parse_warnings": warnings,
            "all_source_bodies_verified": not missing,
            "status": "complete" if not missing else "token_only_competitors_retained",
            "functions_jsonl_sha256": sha((folder / "functions.jsonl").read_bytes()),
            "policy_sha256": sha((folder / "functions-policy-resolver-v1.jsonl").read_bytes()),
            "source_proof_sha256": sha((folder / "source-proof.jsonl").read_bytes()),
            "previous_registry_status": coverage[c["cohort_id"]]["status"],
        }
        dump(folder / "manifest.json", manifest)
        manifests.append({"folder": str(folder), **manifest})
        print(c["cohort_id"], bg.repository, manifest["matched_functions"], "/", len(bg.documents), flush=True)
    source_inputs = [
        SHARED / "rows.jsonl",
        SHARED / "cohorts.jsonl",
        RECEIPT,
        ROOT / "jobs/improve-cpu-retrieval/.lab-results/common.py",
        ROOT / "jobs/improve-operation-blocks/.lab-results/common.py",
        ROOT / "jobs/improve-cpu-retrieval/.lab-results/source-coverage.jsonl",
        PR / "src/dry_lint/extractors.py",
        PR / "src/dry_lint/functions.py",
        PR / "src/dry_lint/operation_blocks.py",
        PR / "src/dry_lint/cpu_embedding.py",
    ]
    dump(
        HERE / "input-proofs.json",
        {"files": {str(p): sha(p.read_bytes()) for p in source_inputs}, "acquisition": receipt},
    )
    dump(
        HERE / "materialized-background-manifest.json",
        {
            "status": "READY",
            "historical_observed_regression": True,
            "inventory_rows": 617,
            "inventory_backgrounds": 79,
            "selected_rows": len(selected_rows),
            "mapped_row_backgrounds": sum(
                m["status"] == "mapped" for r in selected_rows for m in r["mappings"] if m["cohort_id"] in selected_ids
            ),
            "exact_pins": 9,
            "backgrounds": manifests,
            "missing_native_functions": sum(len(m["missing"]) for m in manifests),
            "wall_seconds": time.perf_counter() - started,
            "pooling": "none; each revision/scope has its own full frozen IDF, order, competitors",
        },
    )
    print("READY", HERE / "materialized-background-manifest.json", flush=True)


if __name__ == "__main__":
    main()
