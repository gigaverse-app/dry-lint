# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B905, F403, F405, F841, I001
"""Audit all frozen backgrounds and gold rows; preserve archive/native distinctions."""

from common import *
from collections import Counter, defaultdict
from dry_lint.bench_background import BenchBackground

CW = ROOT / "jobs/corpus-wide-evaluation/.lab-results/full-corpus"
CPU = ROOT / "jobs/experiment-cpu-embeddings/.lab-results/full-corpus/cohorts"
PUB = ROOT / "jobs/public-pin-regressions/.lab-results/cohorts"
KIT = ROOT / "jobs/hybrid-recall-research/.lab-results/combined-recall-data-v1"
OVER = (
    ROOT / "jobs/corpus-wide-evaluation/.lab-results/span-resolution/adjudication-overlay-wave3-wave4-v1/overlay.jsonl"
)


def main():
    inputs = {}
    catalogs = []
    newer = {}
    for p in sorted((ROOT / "jobs").glob("*/catalog.json")):
        d = json.loads(p.read_text())
        if "datasets" not in d:
            continue
        inputs[str(p)] = sha(p)
        for name, v in d["datasets"].items():
            if not v.get("labels"):
                continue
            f = p.parent / v["labels"]["path"]
            rows = jl(f)
            h = sha(f)
            assert h == v["labels"]["sha256"]
            catalogs.append(dict(catalog=str(p), dataset=name, path=str(f), sha256=h, rows=len(rows)))
            inputs[str(f)] = h
            if name.startswith("research-experiments"):
                for row in rows:
                    newer[(row["id"], row.get("repository"), row.get("revision"))] = (name, row, str(f))
    source_rows = jl(CW / "rows.jsonl")
    cohorts = jl(CW / "cohorts.jsonl")
    overlay = jl(OVER)
    for p in [
        CW / "rows.jsonl",
        CW / "cohorts.jsonl",
        CW / "index-ready.json",
        OVER,
        ROOT / "reports/encoder-comparison/EXPERIMENT.json",
    ]:
        inputs[str(p)] = sha(p)
    rows = []
    for r in source_rows:
        nr = newer.get((r["id"], r["repository"], r["revision"]))
        payload = nr[1] if nr else r["payload"]
        rows.append(
            {
                k: r[k]
                for k in [
                    "row_id",
                    "id",
                    "dataset",
                    "repository",
                    "revision",
                    "family_id",
                    "family_lineage",
                    "pair_id",
                    "label",
                    "accepted_gold",
                    "record_kind",
                    "function_retrieval_eligible",
                    "mappings",
                    "sources",
                ]
            }
            | dict(
                original_label=r["label"],
                current_label=payload.get("label", r["label"]),
                catalog_alias=nr[0] + ":" + r["id"] if nr else None,
                label_scope=payload.get("label_scope"),
                whole_function_label=payload.get("whole_function_label"),
                source_review_status=payload.get("review_status"),
                cohort=payload.get("cohort", payload.get("panel")),
                calibration_eligible=r["row_id"] != "candidate-first-gold-v1:CF-C02",
                authority="existing coordinator source-reviewed regression; not human truth",
            )
        )
    for o in overlay:
        rows.append(
            dict(
                row_id="review-wave" + str(o["wave"]) + ":" + o["review_id"],
                id=o["id"],
                dataset="review-wave" + str(o["wave"]),
                repository=o["repository"],
                revision=o["revision"],
                family_id=o["family_id"],
                family_lineage=None,
                pair_id=o["pair_id"],
                label=o["label"],
                original_label=o["label"],
                current_label=o["label"],
                accepted_gold=o["accepted_gold"],
                record_kind="function",
                function_retrieval_eligible=True,
                mappings=[],
                sources={},
                source_ids=o["source_ids"],
                endpoint_body_sha256=o["endpoint_body_sha256"],
                label_scope=o["label_scope"],
                whole_function_label=o["whole_function_label"],
                calibration_eligible=o["calibration_eligible"],
                prior_rows=o["prior_frozen_rows"],
                authority="coordinator adjudication overlay",
            )
        )
    later = jl(HERE / "later-study-rows.jsonl") if (HERE / "later-study-rows.jsonl").exists() else []
    rows.extend(later)
    if later:
        inputs[str(HERE / "later-study-rows.jsonl")] = sha(HERE / "later-study-rows.jsonl")
    # Keep source text out of the compact metadata publication.
    for r in rows:
        r["sources"] = {
            side: {k: v for k, v in s.items() if k not in ["code", "context"]} for side, s in r["sources"].items()
        }
    panels = []
    mapped = []
    failures = []
    unique_bodies = set()
    native_files = {}
    body_sources = {}
    for c in cohorts:
        p = Path(c["background_path"])
        assert sha(p) == c["background_sha256"]
        inputs[str(p)] = c["background_sha256"]
        b = BenchBackground.decode(p.read_bytes())
        assert (b.repository, b.revision, b.scope) == (c["repository"], c["revision"], c["scope"])
        assert len(b.documents) == c["functions"]
        docs = [dict(position=i, source_id=d.id, source_sha256=d.source_sha256) for i, d in enumerate(b.documents)]
        assert docs == jl(c["documents_path"])
        inputs[c["documents_path"]] = sha(c["documents_path"])
        byid = defaultdict(list)
        for d in docs:
            byid[d["source_id"]].append(d)
        panel = {
            k: c[k]
            for k in [
                "cohort_id",
                "repository",
                "revision",
                "scope",
                "extraction_contract",
                "functions",
                "background_path",
                "background_sha256",
                "documents_path",
                "max_df",
                "profiles",
            ]
        }
        panel.update(
            schema=1,
            archive_sparse_valid=True,
            archive_full_source_valid=False,
            native_context_available=False,
            functions_path=None,
            functions_sha256=None,
            minilm_matrix_path=None,
            body_rows_missing=len(docs),
            privacy="private_local_only"
            if c["repository"].startswith("gigaverse-app/")
            else "local_source_license_applies",
        )
        folder = next(
            (
                f
                for f in [
                    HERE / "recovered-cohorts" / c["background_sha256"],
                    CPU / c["background_sha256"],
                    PUB / c["background_sha256"],
                ]
                if (f / "functions.jsonl").exists()
            ),
            None,
        )
        if folder:
            fp = folder / "functions.jsonl"
            fs = jl(fp)
            manifest = json.loads((folder / "manifest.json").read_text())
            assert len(fs) == len(docs)
            fh = sha(fp)
            assert fh == manifest["functions_jsonl_sha256"]
            for i, (f, d) in enumerate(zip(fs, docs, strict=True)):
                assert ident(f) == d["source_id"] and digest(f["code"]) == d["source_sha256"], (c["cohort_id"], i)
                unique_bodies.add(d["source_sha256"])
                body_sources.setdefault(
                    d["source_sha256"],
                    dict(path=str(fp), row=i, code_sha256=d["source_sha256"], bytes=len(f["code"].encode())),
                )
            panel.update(
                archive_full_source_valid=True,
                functions_path=str(fp),
                functions_sha256=fh,
                body_rows_missing=0,
                native_context_available=(folder / "source-proof.jsonl").exists(),
                native_manifest_path=str(folder / "manifest.json"),
            )
            inputs[str(fp)] = fh
            inputs[str(folder / "manifest.json")] = sha(folder / "manifest.json")
            if (folder / "source-proof.jsonl").exists():
                proof = jl(folder / "source-proof.jsonl")
                assert len(proof) == len(docs)
                for i, pr in enumerate(proof):
                    assert pr.get("source_sha256", pr.get("body_sha256")) == docs[i]["source_sha256"], (
                        c["cohort_id"],
                        i,
                        "proof",
                    )
                panel["source_proof_path"] = str(folder / "source-proof.jsonl")
                inputs[panel["source_proof_path"]] = sha(panel["source_proof_path"])
            if (folder / "embeddings.npy").exists():
                panel["minilm_matrix_path"] = str(folder / "embeddings.npy")
                panel["minilm_matrix_sha256"] = sha(folder / "embeddings.npy")
        else:
            failures.append(
                dict(
                    cohort_id=c["cohort_id"],
                    status="sparse_archive_valid_full_body_source_not_located",
                    reason="BenchBackground schema1 contains id/source_sha256/counts, no code field; missing Git alone is not a retrieval exclusion",
                )
            )
        kit = folder if folder and (folder / "view-vectors.npz").exists() else KIT / "cohorts" / c["background_sha256"]
        if (kit / "view-vectors.npz").exists():
            panel["minilm_tail_matrix_path"] = str(kit / "view-vectors.npz")
            panel["minilm_tail_views_path"] = str(
                kit / ("views.jsonl.gz" if (kit / "views.jsonl.gz").exists() else "views.jsonl")
            )
            panel["minilm_tail_matrix_sha256"] = sha(kit / "view-vectors.npz")
        for r in rows:
            if (r["repository"], r["revision"]) != (c["repository"], c["revision"]):
                continue
            candidates = [m for m in r["mappings"] if m["cohort_id"] == c["cohort_id"] and m["status"] == "mapped"]
            if not r["mappings"] and r.get("source_ids"):
                poss = [
                    d
                    for sid in r["source_ids"]
                    for d in byid[sid]
                    if d["source_sha256"] in r["endpoint_body_sha256"].values()
                ]
                if len(poss) == 2:
                    candidates = [
                        dict(sources=dict(zip(["new", "existing"], poss)), status="mapped", cohort_id=c["cohort_id"])
                    ]
            for m in candidates:
                src = m["sources"]
                pp = [src[s]["position"] for s in ["new", "existing"]]
                if len(set(pp)) != 2:
                    continue
                for s, i in zip(["new", "existing"], pp):
                    assert (
                        docs[i]["source_id"] == src[s]["source_id"]
                        and docs[i]["source_sha256"] == src[s]["source_sha256"]
                    )
                key = digest(
                    json.dumps(
                        [
                            c["repository"],
                            c["revision"],
                            sorted((docs[i]["source_id"], docs[i]["source_sha256"]) for i in pp),
                        ]
                    )
                )
                mapped.append(
                    dict(
                        row_id=r["row_id"],
                        cohort_id=c["cohort_id"],
                        pair_identity=key,
                        query_positions=pp,
                        endpoint_identities=[docs[i] for i in pp],
                        family_id=r["family_id"],
                        label=r["current_label"],
                        accepted_gold=r["accepted_gold"],
                        record_kind=r["record_kind"],
                        calibration_eligible=r["calibration_eligible"],
                        dense_evaluable=panel["archive_full_source_valid"],
                        native_context_available=panel["native_context_available"],
                    )
                )
        panels.append(panel)
        print(c["cohort_id"], c["functions"], "source" if folder else "sparse-only", flush=True)
    # Bind related row families through exact shared source pairs, across scopes, without transferring revision labels.
    parent = {r["family_id"] or r["row_id"]: r["family_id"] or r["row_id"] for r in rows}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    pair_families = defaultdict(set)
    for m in mapped:
        pair_families[m["pair_identity"]].add(m["family_id"] or m["row_id"])
    for fams in pair_families.values():
        root = min(fams)
        for f in fams:
            parent[find(f)] = find(root)
    dev_components = {find(r["family_id"] or r["row_id"]) for r in rows if r.get("force_development")}
    for r in rows:
        r["family_component"] = find(r["family_id"] or r["row_id"])
        r["split"] = (
            "development"
            if r["family_component"] in dev_components or int(digest(r["family_component"])[:8], 16) % 5 == 0
            else "evaluation_regression"
        )
        r["coverage"] = (
            "dense_full_background"
            if any(m["row_id"] == r["row_id"] and m["dense_evaluable"] for m in mapped)
            else "sparse_archive_only"
            if any(m["row_id"] == r["row_id"] for m in mapped)
            else "unmapped_or_nonfunction"
        )
    for m in mapped:
        r = next(r for r in rows if r["row_id"] == m["row_id"])
        m.update(family_component=r["family_component"], split=r["split"])
    for name, data in [
        ("panels.jsonl", panels),
        ("gold-rows.jsonl", rows),
        ("mapped-gold.jsonl", mapped),
        ("catalog-inventory.jsonl", catalogs),
        ("coverage-failures.jsonl", failures),
        ("unique-body-workload.jsonl", list(body_sources.values())),
    ]:
        write(HERE / name, data)
    summary = dict(
        schema=1,
        product_commit=REF,
        original_rows=len(source_rows),
        overlay_rows=len(overlay),
        inventory_rows=len(rows),
        backgrounds=len(panels),
        background_documents=sum(p["functions"] for p in panels),
        archive_valid_backgrounds=sum(p["archive_sparse_valid"] for p in panels),
        full_source_backgrounds=sum(p["archive_full_source_valid"] for p in panels),
        full_source_documents=sum(p["functions"] for p in panels if p["archive_full_source_valid"]),
        unique_full_source_bodies=len(unique_bodies),
        minilm_cached_backgrounds=sum(bool(p["minilm_matrix_path"]) for p in panels),
        tail_cached_backgrounds=sum("minilm_tail_matrix_path" in p for p in panels),
        row_coverage=dict(Counter(r["coverage"] for r in rows)),
        original400_coverage=dict(Counter(r["coverage"] for r in rows if r["dataset"] == "private-historical400-v1")),
        mapped_row_panel_records=len(mapped),
        datasets=dict(Counter(r["dataset"] for r in rows)),
        label_counts=dict(Counter(str(r["current_label"]) for r in rows)),
        method="All 79 original backgrounds independently decode/digest/frequency validated; exact body matching, no cross-revision label transfer. Sparse-only remains retrieval-eligible for TFIDF; encoder requires complete source corpus. Family hash split is regression, not unseen test.",
        inference_started=False,
    )
    write(HERE / "COVERAGE.json", summary)
    write(HERE / "input-hashes.json", inputs)
    write(
        HERE / "HANDOFF.json",
        dict(
            schema=1,
            status="panel_manifest_ready_baselines_in_progress",
            panels=str(HERE / "panels.jsonl"),
            mapped_gold=str(HERE / "mapped-gold.jsonl"),
            gold_inventory=str(HERE / "gold-rows.jsonl"),
            coverage=summary,
            model_contract=str(HERE / "MODEL-CONTRACT.json"),
            workload=str(HERE / "unique-body-workload.jsonl"),
            provider_calls=0,
            credentials_read=False,
        ),
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
