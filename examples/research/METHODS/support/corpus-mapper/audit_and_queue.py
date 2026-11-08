# ruff: noqa: E402  # Bootstrap imports from this assigned worktree, not the shared venv install.
"""Audit source excerpts, source envelopes, baseline replication and bounded handoff; offline."""

import gzip
import hashlib
import json
import sys
import tomllib
from collections import Counter
from pathlib import Path

OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT.parents[1] / "src"))
from build_index import BASE, PACKAGES, jl, sha, write

from dry_lint.models import Candidate


def main():
    rows = jl(OUT / "rows.jsonl")
    cohorts = jl(OUT / "cohorts.jsonl")
    ds = {c["cohort_id"]: jl(c["documents_path"]) for c in cohorts}
    audit = []
    for path in sorted((BASE / "repo/examples").rglob("*gold*.toml")):
        gold = tomllib.loads(path.read_text())
        for ordinal, r in enumerate(gold.get("pair", []), 1):
            ids = sorted(r[s].get("source_id", r[s]["id"]) for s in ["new", "existing"])
            matches = [
                x["row_id"]
                for x in rows
                if len(x["sources"]) == 2 and sorted(e["source_id"] for e in x["sources"].values()) == ids
            ]
            candidate_cohorts = []
            for c in cohorts:
                byid = {d["source_id"]: d for d in ds[c["cohort_id"]]}
                if not all(i in byid for i in ids):
                    continue
                proofs = []
                for side in ["new", "existing"]:
                    source = r[side]
                    identity = source.get("source_id", source["id"])
                    doc = byid[identity]
                    proofs.append(
                        dict(
                            side=side,
                            source_id=identity,
                            position=doc["position"],
                            source_sha256=doc["source_sha256"],
                            snippet_sha256=sha(source["code"].encode()),
                            exact_body=sha(source["code"].encode()) == doc["source_sha256"],
                        )
                    )
                candidate_cohorts.append(
                    dict(
                        cohort_id=c["cohort_id"],
                        repository=c["repository"],
                        revision=c["revision"],
                        background_sha256=c["background_sha256"],
                        endpoints=proofs,
                    )
                )
            audit.append(
                dict(
                    file=str(path),
                    file_sha256=sha(path.read_bytes()),
                    ordinal=ordinal,
                    label=r["label"],
                    source_ids=ids,
                    synthetic=False,
                    classification="private source excerpts"
                    if path.name == "gold.toml"
                    else "pinned original source panel",
                    revision_supplied=r.get("revision"),
                    inventory_lineage=matches,
                    cohort_identity_matches=candidate_cohorts,
                    status="in_inventory"
                    if path.name != "gold.toml"
                    else "source_excerpts_missing_pin_not_in_617_inventory",
                    qualification="Identity matches at another revision are possibilities only; no cross-revision mapping or synthetic claim.",
                )
            )
    write(
        OUT / "example-gold-audit.json",
        dict(
            schema=1,
            files=sorted({r["file"] for r in audit}),
            total_rows=len(audit),
            inventory_original_rows=sum(r["status"] == "in_inventory" for r in audit),
            additional_source_excerpts=sum(r["status"] != "in_inventory" for r in audit),
            additional_labels=dict(Counter(r["label"] for r in audit if r["status"] != "in_inventory")),
            rows=audit,
        ),
    )
    # Verify packaged public file envelopes independently of snippet/enclosing-body SHA differences.
    checks = []
    for row in rows:
        if row["dataset"] not in ["candidate-first-gold-v1", "public-gold-v1"]:
            continue
        package = PACKAGES / ("candidate-first-gold" if row["dataset"] == "candidate-first-gold-v1" else "public-gold")
        for side, e in row["sources"].items():
            ref = e.get("source_artifact")
            if not ref:
                continue
            path = package / ref["package_path"]
            raw = path.read_bytes()
            assert sha(raw) == ref["sha256"]
            env = json.loads(gzip.decompress(raw))
            text = env["source"]
            digest = sha(text.encode())
            assert digest == e["file_sha256"]
            for key, expected in [
                ("repository", row["repository"]),
                ("revision", row["revision"]),
                ("path", e["path"]),
            ]:
                if key in env:
                    assert env[key] == expected
            assert e["blob_url"].startswith(
                f"https://github.com/{row['repository']}/blob/{row['revision']}/{e['path']}"
            )
            if env.get("git_blob_sha1"):
                body = text.encode()
                assert (
                    hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest() == env["git_blob_sha1"]
                )
            checks.append(
                dict(
                    row_id=row["row_id"],
                    side=side,
                    path=str(path),
                    compressed_sha256=sha(raw),
                    source_sha256=digest,
                    repository=row["repository"],
                    revision=row["revision"],
                    status="verified",
                )
            )
    write(OUT / "public-source-validation.json", dict(schema=1, source_endpoint_checks=len(checks), checks=checks))
    if (
        not (OUT / "baseline-progress.json").exists()
        or json.loads((OUT / "baseline-progress.json").read_text())["status"] != "complete"
    ):
        return
    baseline = jl(OUT / "paired-rows.jsonl")
    original = jl(BASE / "retrieval/.lab-results/frozen-baseline/rows.jsonl")
    checked = []
    for old in original:
        dataset = {
            "due": "original-due-consolidation",
            "pytest-selective": "original-pytest-selective",
            "pytest-obligation": "original-pytest-obligation",
        }[old["panel"]]
        selected = [r for r in rows if r["dataset"] == dataset][old["ordinal"] - 1]
        matches = [d for d in baseline if d["row_id"] == selected["row_id"] and d["status"] == "evaluated"]
        for direction, answer in old["directions"].items():
            qside = direction.split("_to_")[0]
            candidates = [d for d in matches if d["query_side"] == qside]
            assert any(d["raw_rank"] == answer["rank"] and d["score"] == answer["score"] for d in candidates), (
                selected["row_id"],
                direction,
            )
            checked.append(
                dict(
                    row_id=selected["row_id"],
                    direction=direction,
                    rank=answer["rank"],
                    score=answer["score"],
                    status="exact_original_baseline_replicated",
                )
            )
    assert len(checked) == 74
    write(OUT / "original-baseline-replication.json", dict(status="pass", rows=37, directions=74, checks=checked))
    # Only source-complete exact frozen endpoints can enter the judge-operations handoff.
    pool = {}
    for r in rows:
        cand = r.get("candidate")
        if not cand or r["record_kind"] != "function":
            continue
        for side, e in r["sources"].items():
            body = cand[side]
            pool[(r["repository"], r["revision"], e["source_id"], sha(body["code"].encode()))] = (
                body,
                dict(
                    row_id=r["row_id"],
                    source_proofs=r["payload"].get("source_proofs"),
                    frozen_packet=r["input_record"]["row"].get("frozen_packet"),
                    origin_input=r["input_record"]["input"],
                ),
            )
    ready = []
    excluded = Counter()
    for n in jl(OUT / "novel-candidates.jsonl"):
        d = n["directions"][0]
        q = pool.get((n["repository"], n["revision"], d["query"], d["query_source_sha256"]))
        t = pool.get((n["repository"], n["revision"], d["target"], d["target_source_sha256"]))
        if not q or not t:
            excluded["one_or_both_exact_full_candidate_bodies_unavailable"] += 1
            continue
        c = Candidate(new=q[0], existing=t[0], similarity=d["score"], comparer="tfidf:2")
        ready.append(
            dict(
                schema=1,
                id="FULL-TFIDF-" + sha(json.dumps([n["cohort_id"], n["pair"]]).encode())[:16],
                method="production-tfidf",
                repository=n["repository"],
                revision=n["revision"],
                candidate=c.model_dump(mode="json"),
                background_proof={k: n[k] for k in ["cohort_id", "background_path", "background_sha256", "scope"]},
                source_proofs=[q[1], t[1]],
                status="proposed_to_judge_operations_unfunded_unjudged",
                label=None,
                stratum="low_score" if d["score"] < 0.5 else "high_score",
                private_retrieval_sidecar=dict(
                    score=d["score"],
                    rank=d["rank"],
                    directions=n["directions"],
                    campaign_accounting_usd=0.04,
                    physical_provider_spend_usd=0,
                    funding="root allocation required; no provider called",
                ),
            )
        )
    write(OUT / "novel-source-complete-candidates.jsonl", ready)
    selected = []
    repos = Counter()
    seen = set()
    # Reserve low-score cases, then diversify repositories and endpoint pairs.
    for stratum in ["low_score", "high_score", "low_score", "high_score"]:
        for r in sorted(ready, key=lambda r: (repos[r["repository"]], r["id"])):
            if len(selected) >= 12:
                break
            if r["id"] in seen or r["stratum"] != stratum or repos[r["repository"]] >= 4:
                continue
            selected.append(r)
            seen.add(r["id"])
            repos[r["repository"]] += 1
    controls = []
    for r in rows:
        if len(controls) >= 4:
            break
        if r["accepted_gold"] and r["label"] == "separate" and r.get("candidate") and r["record_kind"] == "function":
            controls.append(
                dict(
                    schema=1,
                    id="FULL-CONTROL-" + r["id"],
                    method="production-tfidf",
                    control=True,
                    row_id=r["row_id"],
                    repository=r["repository"],
                    revision=r["revision"],
                    candidate=r["candidate"],
                    mappings=r["mappings"],
                    status="control_source_packet_for_judge_operations",
                    private_retrieval_sidecar=dict(
                        known_control_label="separate",
                        funding="root allocation required",
                        physical_provider_spend_usd=0,
                    ),
                )
            )
    write(OUT / "novel-review-queue.jsonl", selected + controls)
    blind = []
    for r in selected + controls:
        blind.append(
            {
                k: v
                for k, v in r.items()
                if k not in ["private_retrieval_sidecar", "control", "row_id", "method", "mappings"]
            }
        )
        blind[-1]["candidate"] = dict(blind[-1]["candidate"], similarity=0, comparer="source-review-score-hidden")
        blind[-1]["id"] = "SOURCE-" + str(len(blind)).zfill(3)
    write(OUT / "novel-score-blind-packets.jsonl", blind)
    write(
        OUT / "novel-queue-summary.json",
        dict(
            novel_unordered_pairs=len(jl(OUT / "novel-candidates.jsonl")),
            source_complete_novel_pairs=len(ready),
            selected_novel=len(selected),
            controls=len(controls),
            excluded_from_funded_handoff=dict(excluded),
            novel_by_repository=dict(Counter(r["repository"] for r in ready)),
            providers_called=0,
            qualification="Discovery from full frozen competitors for evaluated queries, not exhaustive all-query scanning. Missing full-body candidates retained in novel-candidates.jsonl; unjudged remains unknown. Queue is proposed, root owns funding/cache/review and final eligibility.",
        ),
    )


if __name__ == "__main__":
    main()
