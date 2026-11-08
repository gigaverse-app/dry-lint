# ruff: noqa: E402  # Bootstrap imports from this assigned worktree, not the shared venv install.
"""Run production frozen TF-IDF once per exact cohort, two directions, offline."""

import gc
import json
import resource
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT.parents[1] / "src"))
from build_index import jl, sha, write

from dry_lint.bench import GoldFunction, as_function
from dry_lint.bench_background import BenchBackground
from dry_lint.extractors import PythonExtractor
from dry_lint.typescript import TypeScriptExtractor


def language(identity):
    return "python" if identity.split("::")[0].endswith(".py") else "typescript"


def query_length(source):
    start = source.get("line", source.get("start_line"))
    end = source.get("end_line")
    if isinstance(start, int) and isinstance(end, int) and start >= 1 and end >= start:
        return end - start + 1, "supplied_valid_span"
    if source.get("code") and source["code"].strip():
        identity = source.get("source_id", source.get("id"))
        extractor = PythonExtractor() if language(identity) == "python" else TypeScriptExtractor()
        function = as_function(GoldFunction(id=identity, code=source["code"]), extractor)
        return function.lines, "inferred_from_snippet_production_as_function"
    return None, "unknown_no_valid_span_or_snippet"


def correct_floor(d, source):
    lines, provenance = query_length(source)
    floor = None if lines is None else 0.3 if lines < 6 else 0.5
    cross_language = language(d["query"]) != language(d["target"])
    loss = (
        "extractor_language"
        if cross_language
        else "same_file"
        if d["same_file"]
        else "unknown_query_length"
        if floor is None
        else "score_floor"
        if d["score"] < floor
        else "top_k"
        if (d["cross_file_rank"] or 10**12) > 3
        else "retrieved_downstream_unknown"
    )
    d.update(
        query_lines=lines,
        query_lines_provenance=provenance,
        default_floor=floor,
        default_floor_known=lines is not None,
        first_loss=loss,
        default_retrieved=loss == "retrieved_downstream_unknown",
    )


def main():
    receipt = json.loads((OUT / "index-ready.json").read_text())
    rows, cohorts = jl(OUT / "rows.jsonl"), jl(OUT / "cohorts.jsonl")
    assert sha((OUT / "rows.jsonl").read_bytes()) == receipt["rows_sha256"]
    assert sha((OUT / "cohorts.jsonl").read_bytes()) == receipt["cohorts_sha256"]
    grouped = defaultdict(list)
    for row in rows:
        for mapping in row["mappings"]:
            grouped[mapping["cohort_id"]].append((row, mapping))
    result = []
    novel = (
        {(n["cohort_id"], *n["pair"]): n for n in jl(OUT / "novel-candidates.jsonl")}
        if (OUT / "novel-candidates.jsonl").exists()
        else {}
    )
    completed = []
    start = time.monotonic()
    known = {
        (r["repository"], r["revision"], tuple(sorted(e["source_id"] for e in r["sources"].values())))
        for r in rows
        if len(r["sources"]) == 2
    }
    parts = OUT / "baseline-cohorts"
    parts.mkdir(exist_ok=True)
    for c in cohorts:
        cid = c["cohort_id"]
        rr = grouped[cid]
        if not rr:
            continue
        part = parts / (cid + ".jsonl")
        stamp = parts / (cid + ".receipt.json")
        stamp_value = {
            "inventory_sha256": receipt["inventory_sha256"],
            "rows_sha256": receipt["rows_sha256"],
            "baseline_script_sha256": sha(Path(__file__).read_bytes()),
            "index_sha256": sha((OUT.parents[1] / "src/dry_lint/index.py").read_bytes()),
        }
        if stamp.exists() and json.loads(stamp.read_text())["index_sha256"] == stamp_value["index_sha256"]:
            cached = jl(part)
            expected = {(row["row_id"], side): (row, m) for row, m in rr for side in ["new", "existing"]}
            assert set(expected) == {(d["row_id"], d["query_side"]) for d in cached}, (
                "cached row membership changed",
                cid,
            )
            for d in cached:
                row, m = expected[d["row_id"], d["query_side"]]
                for key in ["pair_id", "family_id", "accepted_gold", "label", "record_kind"]:
                    d[key] = row[key]
                if d["status"] == "evaluated":
                    assert m["status"] == "mapped"
                    for side, prefix in [(d["query_side"], "query"), (d["target_side"], "target")]:
                        proof = m["sources"][side]
                        assert (d[prefix + "_position"], d[prefix + "_source_sha256"], d[prefix]) == (
                            proof["position"],
                            proof["source_sha256"],
                            proof["source_id"],
                        )
                    correct_floor(d, row["sources"][d["query_side"]])
                d["raw_rank_cache"] = "reused_exact_cohort_verified_positions_and_source_digests"
            write(part, cached)
            write(stamp, stamp_value)
            result.extend(cached)
            completed.append(cid)
            print(cid, "reused production ranks; corrected floor metadata", flush=True)
            continue
        raw = Path(c["background_path"]).read_bytes()
        assert sha(raw) == c["background_sha256"]
        bg = BenchBackground.decode(raw)
        assert (bg.repository, bg.revision, bg.scope) == (c["repository"], c["revision"], c["scope"])
        index = bg.index()
        cache = {}
        cohort_result = []
        for row, m in rr:
            for qside, tside in [("new", "existing"), ("existing", "new")]:
                d = {
                    k: row[k]
                    for k in [
                        "row_id",
                        "dataset",
                        "id",
                        "pair_id",
                        "family_id",
                        "label",
                        "accepted_gold",
                        "record_kind",
                        "repository",
                        "revision",
                    ]
                }
                d.update(
                    schema=1,
                    cohort_id=cid,
                    profiles=m["profiles"],
                    query_side=qside,
                    target_side=tside,
                    status=m["status"],
                    raw_rank=None,
                    score=None,
                    top1=False,
                    top3=False,
                    top20=False,
                    filter_status="unknown_full_source_rules",
                    budget_status="unknown_no_historical_ledger",
                    judge_status="not_run",
                    report_status="not_replayed",
                )
                if row["record_kind"] == "model":
                    d.update(status="unsupported_record_kind", first_loss="model_declaration_separate_inventory")
                    cohort_result.append(d)
                    continue
                if m["status"] != "mapped":
                    d.update(first_loss="source_mapping", mapping_reasons=m["reasons"])
                    cohort_result.append(d)
                    continue
                q, t = m["sources"][qside], m["sources"][tside]
                qi, ti = q["position"], t["position"]
                d.update(
                    query=q["source_id"],
                    target=t["source_id"],
                    query_position=qi,
                    target_position=ti,
                    query_source_sha256=q["source_sha256"],
                    target_source_sha256=t["source_sha256"],
                )
                if qi == ti:
                    d.update(status="self_pair", first_loss="self_pair")
                    cohort_result.append(d)
                    continue
                if qi not in cache:
                    if len(cache) >= 8:
                        cache.clear()
                    ranked = index.similar(bg.documents[qi].tokens(), exclude={qi})
                    assert all(i != qi for i, _ in ranked)
                    cross = [
                        (i, s)
                        for i, s in ranked
                        if bg.documents[i].id.split("::")[0] != q["source_id"].split("::")[0]
                        and language(bg.documents[i].id) == language(q["source_id"])
                    ]
                    compatible = [(i, s) for i, s in ranked if language(bg.documents[i].id) == language(q["source_id"])]
                    cache[qi] = (
                        ranked,
                        dict(ranked),
                        {i: k for k, (i, _) in enumerate(ranked, 1)},
                        {i: k for k, (i, _) in enumerate(cross, 1)},
                        {i: k for k, (i, _) in enumerate(compatible, 1)},
                    )
                    # Novel full-background neighbors, never gold; exact known unordered endpoints excluded.
                    for rank, (i, score) in enumerate(compatible[:20], 1):
                        target = bg.documents[i]
                        key = (bg.repository, bg.revision, tuple(sorted([q["source_id"], target.id])))
                        if key in known:
                            continue
                        nk = (cid, *key[-1])
                        entry = novel.setdefault(
                            nk,
                            dict(
                                schema=1,
                                method="production-tfidf",
                                cohort_id=cid,
                                background_path=c["background_path"],
                                background_sha256=c["background_sha256"],
                                repository=bg.repository,
                                revision=bg.revision,
                                scope=bg.scope,
                                pair=list(key[-1]),
                                label=None,
                                accepted_gold=False,
                                status="unjudged_unknown",
                                directions=[],
                            ),
                        )
                        entry["directions"].append(
                            dict(
                                query=q["source_id"],
                                query_position=qi,
                                query_source_sha256=q["source_sha256"],
                                target=target.id,
                                target_position=i,
                                target_source_sha256=target.source_sha256,
                                rank=rank,
                                score=score,
                            )
                        )
                ranked, scores, ranks, crossr, langr = cache[qi]
                score = scores.get(ti, 0.0)
                rank = ranks.get(ti)
                source = row["sources"][qside]
                lines, lines_provenance = query_length(source)
                floor = None if lines is None else 0.3 if lines < 6 else 0.5
                same = q["source_id"].split("::")[0] == t["source_id"].split("::")[0]
                cross_language = language(q["source_id"]) != language(t["source_id"])
                loss = (
                    "extractor_language"
                    if cross_language
                    else "same_file"
                    if same
                    else "unknown_query_length"
                    if floor is None
                    else "score_floor"
                    if score < floor
                    else "top_k"
                    if crossr.get(ti, 10**12) > 3
                    else "retrieved_downstream_unknown"
                )
                balanced_loss = (
                    "extractor_language"
                    if cross_language
                    else "score_floor"
                    if score < 0.35
                    else "top_k"
                    if langr.get(ti, 10**12) > 20
                    else "retrieved_downstream_unknown"
                )
                d.update(
                    status="evaluated",
                    raw_rank=rank,
                    score=score,
                    top1=rank == 1,
                    top3=rank is not None and rank <= 3,
                    top20=rank is not None and rank <= 20,
                    same_file=same,
                    cross_file_rank=crossr.get(ti),
                    compatible_language_rank=langr.get(ti),
                    query_lines=lines or None,
                    query_lines_provenance=lines_provenance,
                    default_floor=floor,
                    default_floor_known=lines is not None,
                    first_loss=loss,
                    balanced_first_loss=balanced_loss,
                    default_retrieved=loss == "retrieved_downstream_unknown",
                    balanced_retrieved=balanced_loss == "retrieved_downstream_unknown",
                    positive_candidates=len(ranked),
                    target_exact_score_tie_count=sum(s == score for _, s in ranked)
                    if rank
                    else len(bg.documents) - 1 - len(ranked),
                    top20_neighbors=[
                        dict(
                            position=i,
                            source_id=bg.documents[i].id,
                            source_sha256=bg.documents[i].source_sha256,
                            score=s,
                        )
                        for i, s in ranked[:20]
                    ],
                )
                cohort_result.append(d)
        write(part, cohort_result)
        write(stamp, stamp_value)
        result.extend(cohort_result)
        completed.append(cid)
        write(OUT / "paired-rows.jsonl", result)
        write(
            OUT / "baseline-progress.json",
            dict(
                status="running",
                completed_cohorts=completed,
                total_cohorts=len(cohorts),
                direction_records=len(result),
                elapsed_seconds=time.monotonic() - start,
                max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            ),
        )
        print(cid, len(cohort_result), "completed", len(completed), flush=True)
        del index, bg, cache
        gc.collect()
    # Rows without cohorts also have explicit two-direction records.
    for row in rows:
        if row["mappings"]:
            continue
        for qside, tside in [("new", "existing"), ("existing", "new")]:
            d = {
                k: row[k]
                for k in [
                    "row_id",
                    "dataset",
                    "id",
                    "pair_id",
                    "family_id",
                    "label",
                    "accepted_gold",
                    "record_kind",
                    "repository",
                    "revision",
                ]
            }
            d.update(
                schema=1,
                cohort_id=None,
                query_side=qside,
                target_side=tside,
                status="unsupported_record_kind" if row["record_kind"] == "model" else "incompatible",
                first_loss="source_mapping",
                mapping_reasons=row["reasons"],
                raw_rank=None,
                score=None,
                top1=False,
                top3=False,
                top20=False,
            )
            result.append(d)
    write(OUT / "paired-rows.jsonl", result)
    write(OUT / "novel-candidates.jsonl", list(novel.values()))
    summary = []
    for field in ["dataset", "cohort_id", "family_id", "repository"]:
        groups = defaultdict(list)
        for r in result:
            groups[(r.get(field), r["record_kind"], r["accepted_gold"], r["label"])].append(r)
        for (value, kind, accepted, label), ds in groups.items():
            bypair = defaultdict(list)
            for d in ds:
                bypair[d["pair_id"] or d["row_id"]].append(d)
            summary.append(
                dict(
                    group_by=field,
                    group=value,
                    record_kind=kind,
                    accepted_gold=accepted,
                    label=label,
                    rows=len({d["row_id"] for d in ds}),
                    unique_exact_pairs=len(bypair),
                    directions=len(ds),
                    evaluated_directions=sum(d["status"] == "evaluated" for d in ds),
                    top1=sum(d["top1"] for d in ds),
                    top3=sum(d["top3"] for d in ds),
                    top20=sum(d["top20"] for d in ds),
                    either_direction_pair_top20=sum(any(d["top20"] for d in group) for group in bypair.values()),
                    first_losses=dict(Counter(d["first_loss"] for d in ds)),
                )
            )
    write(
        OUT / "paired-summary.json",
        dict(
            schema=1,
            groups=summary,
            policy="production first-posting ties; no zero-padding; two correlated directions; same-file/language/floors are explicit laboratory diagnostics; no policy/budget/judge/report inference",
            inventory_receipt=receipt,
        ),
    )
    coverage = dict(
        schema=1,
        inventory_receipt=receipt,
        rows=len(rows),
        accepted_function_rows=sum(r["accepted_gold"] and r["record_kind"] == "function" for r in rows),
        accepted_model_rows=sum(r["accepted_gold"] and r["record_kind"] == "model" for r in rows),
        mapped_rows=sum(r["status"] == "mapped" for r in rows),
        evaluated_rows=len({d["row_id"] for d in result if d["status"] == "evaluated"}),
        unsupported_rows=[
            dict(
                row_id=r["row_id"],
                record_kind=r["record_kind"],
                reasons=r["reasons"],
                mapping_reasons=[m["reasons"] for m in r["mappings"]],
            )
            for r in rows
            if r["status"] != "mapped"
        ],
        direction_statuses=dict(Counter(d["status"] for d in result)),
        completed_cohorts=completed,
        elapsed_seconds=time.monotonic() - start,
        max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        threads_max=2,
        providers_called=0,
    )
    write(OUT / "coverage.json", coverage)
    write(
        OUT / "baseline-progress.json",
        dict(
            status="complete",
            completed_cohorts=completed,
            total_cohorts=len(cohorts),
            direction_records=len(result),
            elapsed_seconds=time.monotonic() - start,
            max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        ),
    )
    print(
        json.dumps(
            {
                k: v
                for k, v in coverage.items()
                if k not in ["inventory_receipt", "unsupported_rows", "completed_cohorts"]
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
