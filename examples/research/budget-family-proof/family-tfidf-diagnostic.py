"""Whole-function retrieval diagnostics for family membership, not pair-positive gold."""

import argparse
import hashlib
import json
from pathlib import Path

from dry_lint.bench_background import BenchBackground


def run(background, inventory, out):
    raw = background.read_bytes()
    b = BenchBackground.decode(raw)
    inv = json.loads(inventory.read_text())
    assert b.revision == inv["revision"]
    owners = {r["source_id"]: r for r in inv["eligible"]}
    positions = {}
    for sid, o in owners.items():
        found = [i for i, d in enumerate(b.documents) if d.id == sid and d.source_sha256 == o["body_sha256"]]
        assert len(found) == 1, (sid, found)
        positions[sid] = found[0]
    index = b.index()
    rows = []
    query_summary = []
    for sid, own in positions.items():
        scores = dict(index.similar(b.documents[own].tokens(), exclude={own}))
        ranked = sorted((i for i in range(len(b.documents)) if i != own), key=lambda i: (-scores.get(i, 0), i))
        rank = {i: n + 1 for n, i in enumerate(ranked)}
        qpath = owners[sid]["path"]
        cross = [i for i in ranked if b.documents[i].id.rsplit("::", 1)[0] != qpath]
        crossrank = {i: n + 1 for n, i in enumerate(cross)}
        qlines = owners[sid]["function_end_line"] - owners[sid]["function_line"] + 1
        floor = 0.3 if qlines < 6 else 0.5
        these = []
        for target, other in positions.items():
            if target == sid:
                continue
            score = scores.get(other, 0.0)
            same = qpath == owners[target]["path"]
            r = dict(
                query=sid,
                target=target,
                query_position=own,
                target_position=other,
                score=score,
                rank=rank[other],
                same_file=same,
                cross_file_rank=crossrank.get(other),
                query_lines=qlines,
                default_query_score_floor=floor,
                raw_top1=rank[other] <= 1,
                raw_top3=rank[other] <= 3,
                default_tfidf_only=not same and score >= floor and crossrank[other] <= 3,
                balanced_tfidf_only=score >= 0.35 and rank[other] <= 20,
                production_sparse_support=other in scores,
                label="same_refactoring_family; no independent pair-positive assertion",
            )
            rows.append(r)
            these.append(r)
        query_summary.append(
            dict(
                query=sid,
                raw_top1_any_sibling=any(r["raw_top1"] for r in these),
                raw_top3_any_sibling=any(r["raw_top3"] for r in these),
                default_tfidf_any_sibling=any(r["default_tfidf_only"] for r in these),
                balanced_tfidf_any_sibling=any(r["balanced_tfidf_only"] for r in these),
            )
        )
    summary = dict(
        repository=b.repository,
        revision=b.revision,
        background_sha256=hashlib.sha256(raw).hexdigest(),
        documents=len(b.documents),
        scope=b.scope,
        max_df=b.max_df,
        extraction_contract=b.extraction_contract,
        owners=len(owners),
        directed_family_memberships=len(rows),
        source_id_and_body_matches=len(positions),
        missing=0,
        self_excluded=True,
        tie_policy="descending exact production cosine, ascending frozen document position; zero scores ranked mathematically but production sparse support recorded separately",
        raw_top1=sum(r["raw_top1"] for r in rows),
        raw_top3=sum(r["raw_top3"] for r in rows),
        same_file_directions=sum(r["same_file"] for r in rows),
        below_default_query_floor=sum(r["score"] < r["default_query_score_floor"] for r in rows),
        below_balanced_floor=sum(r["score"] < 0.35 for r in rows),
        default_tfidf_directions=sum(r["default_tfidf_only"] for r in rows),
        balanced_tfidf_directions=sum(r["balanced_tfidf_only"] for r in rows),
        query_coverage={
            k: sum(r[k] for r in query_summary)
            for k in [
                "raw_top1_any_sibling",
                "raw_top3_any_sibling",
                "default_tfidf_any_sibling",
                "balanced_tfidf_any_sibling",
            ]
        },
        scope_limit="Post hoc family membership diagnostics on frozen whole-function TF-IDF. Not 45 duplicate-pair gold labels, not a historical PR or full balanced preset replay. No adopter configuration inferred; no judge calls or source mutation. Separate size-ratio filter not assumed; only pinned comparer query-length floor is modeled.",
    )
    out.mkdir(parents=True, exist_ok=False)
    (out / "rows.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out / "queries.json").write_text(json.dumps(query_summary, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--background", type=Path, required=True)
    p.add_argument("--inventory", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    run(a.background, a.inventory, a.out)
