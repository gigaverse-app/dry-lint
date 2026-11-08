from paths import evidence_path

# ruff: noqa: E402  # Bootstrap imports from this assigned worktree, not the shared venv install.
"""Exact frozen-corpus mapping. Offline; no providers. Schema 1 research sidecars only."""

import ast
import fnmatch
import hashlib
import json
import sys
import textwrap
import tomllib
from collections import Counter, defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parent
from paths import runtime_path

ROOT = runtime_path()
BASE = Path(evidence_path(""))
sys.path.insert(0, str(ROOT / "src"))
from dry_lint.bench import GoldFunction, as_function
from dry_lint.bench_background import BenchBackground
from dry_lint.extractors import PythonExtractor

INVENTORY = BASE / "reports/research-experiments/full-corpus/input-inventory.jsonl"
PACKAGES = BASE / "reports/candidate-first/corpus-verification"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def jl(path):
    return [json.loads(s) for s in Path(path).read_text().splitlines() if s.strip()]


def write(path, value):
    path = Path(path)
    raw = (
        "".join(json.dumps(r, sort_keys=True, allow_nan=False) + "\n" for r in value)
        if path.suffix == ".jsonl"
        else json.dumps(value, indent=2, sort_keys=True) + "\n"
    )
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(raw)
    tmp.replace(path)


def syntax_fields(node):
    if not isinstance(node, ast.AST):
        return {"_literal": repr(node)}
    return {"_type": type(node).__name__, **{k: v for k, v in ast.iter_fields(node) if v is not None and v != []}}


def ast_sha(source):
    f = as_function(GoldFunction.model_validate(source), PythonExtractor())
    return sha(json.dumps(ast.parse(textwrap.dedent(f.code)), default=syntax_fields, sort_keys=True).encode())


def in_scope(identity, scope):
    p = identity.split("::")[0]
    return any(fnmatch.fnmatch(p, g) for g in scope["include"]) and not any(
        fnmatch.fnmatch(p, g) for g in scope["exclude"]
    )


def main():
    inventory_raw = INVENTORY.read_bytes()
    inventory = [json.loads(s) for s in inventory_raw.splitlines() if s.strip()]
    manifests = []
    for profile, name in [
        ("legacy", "legacy-background-manifest.json"),
        ("diagnostic", "background-manifest.json"),
        ("configured", "configured-background-manifest.json"),
    ]:
        path = PACKAGES / "private-historical400" / name
        data = json.loads(path.read_text())
        entries = list(data.values()) if isinstance(data, dict) else data
        for e in entries:
            manifests.append(
                (profile, path, e, path.parent / "backgrounds" / e["path"].replace("\\", "/").rsplit("/", 1)[-1])
            )
    for panel in ["public-gold", "candidate-first-gold"]:
        path = PACKAGES / panel / "backgrounds/manifest.json"
        for e in json.loads(path.read_text())["backgrounds"]:
            manifests.append((panel, path, e, path.parent.parent / e["path"]))
    for path in sorted((BASE / "repo/examples/backgrounds").glob("*/manifest.json")):
        for e in json.loads(path.read_text())["backgrounds"]:
            manifests.append(("original-" + path.parent.name, path, e, path.parent / e["path"]))
    local_manifest = OUT / "materialized-backgrounds/manifest.json"
    if local_manifest.exists():
        for e in json.loads(local_manifest.read_text())["backgrounds"]:
            manifests.append(
                ("full-corpus-materialized-diagnostic", local_manifest, e, local_manifest.parent / e["path"])
            )

    # Locate the scaled packets through the portable reference map, never a guessed revision.
    scaled = PACKAGES / "scaled-v1"
    refmap = json.loads((scaled / "reference-map.json").read_text())
    paths = {r["original"]: scaled / r["mapped"]["path"] for r in refmap["resolutions"]}
    origins = {}
    for miner in ["t3", "litellm", "opencode", "openhands", "kaizen"]:
        f = scaled / "originals" / miner / "scaled-completed.jsonl"
        if f.exists():
            origins[str(f.relative_to(scaled))] = jl(f)
    proposals = {r["id"]: r for r in jl(scaled / "proposals.jsonl")}
    packets = {}
    for rid, r in proposals.items():
        ptr = r["completed_snapshot"]
        item = origins[ptr["path"]][ptr["line"] - 1]
        packet = item["packet"]
        packets[("candidate-first-scaled-v1", rid)] = packet
        proof = packet["background_proof"]
        path = paths.get(proof["path"], Path(proof["path"]))
        manifests.append(("scaled-v1", scaled / "reference-map.json", proof, path))
    for item in inventory:
        r = item["row"]
        if r.get("frozen_packet"):
            packet_path = Path(r["frozen_packet"])
            if packet_path.exists():
                for packet in jl(packet_path):
                    packets[(item["dataset"], packet["id"])] = packet
                    proof = packet.get("background_proof")
                    if proof and Path(proof["path"]).exists():
                        manifests.append(("research-packet", packet_path, proof, Path(proof["path"])))

    # One decoded background at a time. Persist a light identity catalog for consumers and mapping.
    cohorts = {}
    catalogs = {}
    for profile, manifest, entry, path in manifests:
        digest = entry.get("sha256")
        if digest in cohorts:
            c = cohorts[digest]
            c["profiles"] = sorted(set(c["profiles"] + [profile]))
            proof = {
                "manifest_path": str(manifest),
                "manifest_sha256": sha(manifest.read_bytes()),
                "entry": entry,
                "resolved_path": str(path),
            }
            if proof not in c["manifest_proofs"]:
                c["manifest_proofs"].append(proof)
            continue
        raw = path.read_bytes()
        assert sha(raw) == digest, ("background SHA", path)
        bg = BenchBackground.decode(raw)
        for key in ["repository", "revision", "scope", "extraction_contract", "max_df"]:
            if key in entry:
                assert getattr(bg, key) == entry[key], (path, key)
        if "functions" in entry:
            assert len(bg.documents) == entry["functions"]
        cid = "bg-" + digest[:16]
        docpath = OUT / "documents" / (cid + ".jsonl")
        docpath.parent.mkdir(exist_ok=True)
        docs = [
            {"position": i, "source_id": d.id, "source_sha256": d.source_sha256} for i, d in enumerate(bg.documents)
        ]
        write(docpath, docs)
        byid = defaultdict(list)
        for d in docs:
            byid[d["source_id"]].append(d)
        catalogs[digest] = byid
        cohorts[digest] = {
            "schema": 1,
            "cohort_id": cid,
            "background_path": str(path),
            "background_sha256": digest,
            "repository": bg.repository,
            "revision": bg.revision,
            "scope": bg.scope,
            "extraction_contract": bg.extraction_contract,
            "max_df": bg.max_df,
            "functions": len(bg.documents),
            "extractors": [x.model_dump(mode="json") for x in bg.extractors],
            "python_version": bg.python_version,
            "profiles": [profile],
            "status": "verified",
            "documents_path": str(docpath),
            "duplicate_source_ids": {k: [d["position"] for d in v] for k, v in byid.items() if len(v) > 1},
            "manifest_proofs": [
                {
                    "manifest_path": str(manifest),
                    "manifest_sha256": sha(manifest.read_bytes()),
                    "entry": entry,
                    "resolved_path": str(path),
                }
            ],
        }
        del bg
    rows = []
    for line, item in enumerate(inventory, 1):
        r = item["row"]
        dataset = item["dataset"]
        rid = r.get("id", r.get("case", str(line)))
        payload = r
        refs = []
        candidate = None
        if dataset == "private-historical400-v1":
            ptr = r["artifacts"]
            path = PACKAGES / "private-historical400" / ptr["package_path"]
            assert sha(path.read_bytes()) == ptr["sha256"]
            payload = jl(path)[ptr["line"] - 1]
            refs = [
                (p, ref["sha256"]) for p, ref in payload.get("backgrounds", {"legacy": payload["background"]}).items()
            ]
            sources = {s: dict(payload[s], source_id=r["source_ids"][s]) for s in ["new", "existing"]}
        elif (dataset, rid) in packets:
            payload = packets[(dataset, rid)]
            candidate = payload["candidate"]
            sources = {
                s: dict(
                    candidate[s],
                    source_id=candidate[s]["path"]
                    + "::"
                    + (candidate[s].get("class_name") + "." if candidate[s].get("class_name") else "")
                    + candidate[s]["name"],
                )
                for s in ["new", "existing"]
            }
            # Function.qualname may include origin; use the production model to avoid guessed names.
            from dry_lint.models import Candidate

            cm = Candidate.model_validate(candidate)
            for s in sources:
                sources[s]["source_id"] = getattr(cm, s).qualname
            if payload.get("background_proof"):
                refs = [("packet", payload["background_proof"]["sha256"])]
        elif r.get("endpoints"):
            es = r["endpoints"]
            sources = (
                {s: dict(es[s]) for s in ["new", "existing"]}
                if isinstance(es, dict)
                else {e["side"]: dict(e) for e in es}
            )
            for s in sources:
                e = sources[s]
                e["source_id"] = e.get("extracted_source_id", e.get("source_id", e.get("id")))
        elif "new" in r and "existing" in r:
            sources = {s: dict(r[s], source_id=r[s].get("source_id", r[s]["id"])) for s in ["new", "existing"]}
        else:
            sources = {}
        repo, rev = r.get("repository", payload.get("repository")), r.get("revision", payload.get("revision"))
        inherited = None
        if str(item.get("input", "")).endswith(".toml"):
            gold = tomllib.loads(Path(item["input"]).read_text())
            repo = repo or gold.get("provenance", {}).get("repository")
            inherited = {
                "gold_path": item["input"],
                "gold_sha256": sha(Path(item["input"]).read_bytes()),
                "provenance": gold.get("provenance"),
            }
            if not repo and item.get("background_manifest"):
                matching = [
                    c
                    for c in cohorts.values()
                    if c["revision"] == rev
                    and any(p["manifest_path"] == item["background_manifest"] for p in c["manifest_proofs"])
                ]
                assert len({c["repository"] for c in matching}) == 1, ("ambiguous inherited repository", rid)
                repo = matching[0]["repository"]
        accepted = r.get("accepted_gold", r.get("active_panel_eligible", True)) and r.get("label") in [
            "duplicate",
            "separate",
        ]
        kind = (
            "model"
            if any(
                e.get("declaration_kind") or e.get("kind") in ["model", "class", "interface", "type"]
                for e in sources.values()
            )
            or "model" in str(payload.get("candidate_kind", "")).lower()
            else "function"
        )
        identity = sorted(e["source_id"] for e in sources.values() if e.get("source_id"))
        pairid = sha(json.dumps([repo, rev, identity], separators=(",", ":")).encode()) if len(identity) == 2 else None
        row = {
            "schema": 1,
            "row_id": dataset + ":" + rid,
            "inventory_line": line,
            "dataset": dataset,
            "id": rid,
            "label": r.get("label"),
            "accepted_gold": bool(accepted),
            "control": r.get("label") == "separate",
            "family_id": r.get("family_id", r.get("family")),
            "family_lineage": r.get("family_lineage"),
            "repository": repo,
            "revision": rev,
            "record_kind": kind,
            "pair_id": pairid,
            "input_record": item,
            "payload": payload,
            "candidate": candidate,
            "sources": sources,
            "mappings": [],
            "status": "unmapped",
            "reasons": [],
        }
        row["inherited_context"] = inherited
        if not refs:
            refs = [
                ("same-exact-repository-revision", digest)
                for digest, c in cohorts.items()
                if c["repository"] == repo and c["revision"] == rev
            ]
        for profile, digest in refs:
            if digest not in cohorts:
                row["reasons"].append("background_sha_unavailable:" + digest)
                continue
            c = cohorts[digest]
            if (repo, rev) != (c["repository"], c["revision"]):
                row["reasons"].append("background_repository_revision_mismatch:" + c["cohort_id"])
                continue
            m = {"cohort_id": c["cohort_id"], "profiles": [profile], "status": "unmapped", "reasons": [], "sources": {}}
            for side, source in sources.items():
                e = dict(source)
                ident = e["source_id"]
                proofs = []
                for proof in c["manifest_proofs"]:
                    proofs += [g for g in proof["entry"].get("gold_sources", []) if g["id"] == e.get("id", ident)]
                if proofs:
                    assert all(p == proofs[0] for p in proofs), ("conflicting gold_sources", row["row_id"])
                    ident = proofs[0]["source_id"]
                matches = catalogs[digest].get(ident, [])
                endpoint = {
                    "source_id": ident,
                    "gold_id": e.get("id", ident),
                    "position": None,
                    "status": "missing",
                    "source_sha256": None,
                    "verification": None,
                }
                if len(matches) > 1:
                    endpoint.update(status="ambiguous_source_id", positions=[x["position"] for x in matches])
                elif not matches:
                    endpoint["status"] = (
                        "outside_scope"
                        if not in_scope(ident, c["scope"])
                        else "source_id_absent_from_frozen_extraction"
                    )
                else:
                    doc = matches[0]
                    endpoint.update(doc)
                    endpoint["status"] = "present"
                    endpoint["verification"] = "exact_repository_revision_source_id"
                    expected = None
                    if proofs:
                        expected = proofs[0]["source_sha256"]
                        endpoint["gold_source_proof"] = proofs[0]
                        if proofs[0].get("syntax_sha256") and e.get("code"):
                            actual = ast_sha(e)
                            endpoint["snippet_syntax_sha256"] = actual
                            assert actual == proofs[0]["syntax_sha256"], ("gold AST binding", row["row_id"], side)
                            endpoint["verification"] = "manifest_exact_source_sha256_and_gold_AST"
                        elif proofs[0].get("snippet_sha256"):
                            assert proofs[0]["snippet_sha256"] == e.get("snippet_sha256"), (
                                "snippet binding",
                                row["row_id"],
                            )
                            endpoint["verification"] = "manifest_exact_source_sha256_and_snippet_binding"
                        else:
                            endpoint["verification"] = "manifest_exact_source_sha256"
                    elif e.get("code"):
                        expected = sha(e["code"].encode())
                        endpoint["candidate_body_sha256"] = expected
                        endpoint["verification"] = "exact_candidate_body_sha256"
                    elif e.get("candidate_code_sha256"):
                        expected = e["candidate_code_sha256"]
                        endpoint["verification"] = "exact_packaged_candidate_body_sha256"
                    if expected and expected != doc["source_sha256"]:
                        # Historical snippets preserve body labels but may differ in indentation. Never pretend exact source.
                        endpoint["candidate_body_sha256"] = expected
                        if dataset == "private-historical400-v1":
                            endpoint["verification"] = (
                                "exact_repository_revision_source_id; historical_snippet_body_differs"
                            )
                            endpoint["body_relation"] = (
                                "historical_snippet_not_exact_full_source; original package has no gold_sources"
                            )
                        else:
                            endpoint["status"] = "source_body_sha256_mismatch"
                            endpoint["position"] = None
                m["sources"][side] = endpoint
                if endpoint["status"] != "present":
                    m["reasons"].append(side + ":" + endpoint["status"])
            m["status"] = "mapped" if len(m["sources"]) == 2 and not m["reasons"] else "incompatible"
            row["mappings"].append(m)
        row["status"] = "mapped" if any(m["status"] == "mapped" for m in row["mappings"]) else "incompatible"
        mapped = next((m for m in row["mappings"] if m["status"] == "mapped"), None)
        row["canonical_source_ids"] = (
            {s: e["source_id"] for s, e in mapped["sources"].items()}
            if mapped
            else {s: e["source_id"] for s, e in sources.items()}
        )
        if len(row["canonical_source_ids"]) == 2:
            row["pair_id"] = sha(
                json.dumps([repo, rev, sorted(row["canonical_source_ids"].values())], separators=(",", ":")).encode()
            )
        row["function_retrieval_eligible"] = row["record_kind"] == "function"
        if row["record_kind"] == "model":
            row["reasons"].append("model_declaration_separate_inventory_not_function_matrix")
        if not row["mappings"]:
            row["reasons"].append("no_exact_repository_revision_background")
        rows.append(row)
    # Preserve same-pair lineage without inflating independent denominators.
    pairs = defaultdict(list)
    for r in rows:
        if r["pair_id"]:
            pairs[r["pair_id"]].append(r["row_id"])
    for r in rows:
        r["pair_lineage"] = pairs.get(r["pair_id"], [])
    bycohort = defaultdict(list)
    for r in rows:
        for m in r["mappings"]:
            bycohort[m["cohort_id"]].append((r, m))
    for c in cohorts.values():
        rr = bycohort[c["cohort_id"]]
        c["row_counts"] = dict(Counter(m["status"] for _, m in rr))
        c["accepted_positive_mapped"] = sum(
            r["accepted_gold"] and r["label"] == "duplicate" and m["status"] == "mapped" for r, m in rr
        )
    ordered = sorted(
        cohorts.values(),
        key=lambda c: (-c["accepted_positive_mapped"], -c["row_counts"].get("mapped", 0), c["cohort_id"]),
    )
    assert INVENTORY.read_bytes() == inventory_raw, "inventory changed while mapping; rerun"
    write(OUT / "cohorts.jsonl", ordered)
    write(OUT / "rows.jsonl", rows)
    write(OUT / "model-records.jsonl", [r for r in rows if r["record_kind"] == "model"])
    receipt = {
        "schema": 1,
        "inventory_path": str(INVENTORY),
        "inventory_sha256": sha(inventory_raw),
        "records": len(rows),
        "accepted_binary_rows": sum(r["accepted_gold"] for r in rows),
        "accepted_labels": dict(Counter(r["label"] for r in rows if r["accepted_gold"])),
        "record_statuses": dict(Counter(r["status"] for r in rows)),
        "cohorts": len(cohorts),
        "unique_pairs_before_label_family_reconciliation": len(pairs),
        "cohorts_path": str(OUT / "cohorts.jsonl"),
        "rows_path": str(OUT / "rows.jsonl"),
        "schema_readme": str(OUT / "README.md"),
        "cohorts_sha256": sha((OUT / "cohorts.jsonl").read_bytes()),
        "rows_sha256": sha((OUT / "rows.jsonl").read_bytes()),
    }
    write(OUT / "index-ready.json", receipt)
    print(json.dumps(receipt, indent=2), flush=True)


if __name__ == "__main__":
    main()
