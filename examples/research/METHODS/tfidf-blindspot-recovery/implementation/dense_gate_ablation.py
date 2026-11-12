# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: F401, F403, F405, I001
"""Separate predeclared below-dense-gate structural rejection audit. No label reads."""

import recover as R
from recover import *
from dry_lint.operation_blocks import _representations, _cosine


def main():
    out = H / "dense-gate-ablation"
    out.mkdir(exist_ok=True)
    write(
        out / "ABLATION-CONTRACT.json",
        {
            "schema": 1,
            "frozen_main_selection_sha256": sha(H / "diagnostic-single-question/FROZEN-SELECTION.json"),
            "question": "Does the .65 dense agreement gate reject independently repeated executable operations?",
            "population": "Original bounded bank native-block weak pairs rejected by the original max-available dense gate; subset of 5017 structural rejections, not a new broad search",
            "fixed_rule": "largest minimum matching-region AST node count, then original block score, then source hash; require >=3 shared concrete calls, >=25 nodes in each region; exact-body dedup and <=2 per repository, distinct shared-call signatures; select first4",
            "labels": False,
            "provider_answers": False,
            "outcome_separation": "Never merge into original recipe; native diagnostic only; source usefulness remains unknown",
        },
    )
    candidates = []
    coverage = []
    manifest = json.loads((BANK / "BANK-MANIFEST.json").read_text())
    for item in manifest["backgrounds"]:
        p = item["source"]
        cid = p["cohort_id"]
        if p["repository"] == "anomalyco/opencode":
            continue
        metric = json.loads((H / "generation" / cid / "METRICS.json").read_text())
        potential = []
        for r in jl(BANK / "deterministic-v2/bank" / cid / "candidates.jsonl"):
            f = r["features"]
            if (
                r["native_eligible"]
                and f["tfidf_score"] < 0.35
                and f["block_score"] > 0
                and max(f["minilm_score"], f["tail_score"]) < 0.65
            ):
                potential.append(r)
        if not potential:
            continue
        fs = jl(p["functions_path"])
        bg = BenchBackground.decode(pathlib.Path(p["background_path"]).read_bytes())
        idx = bg.index()
        cod = None
        av = metric["availability"].get("coderank", {})
        if av.get("available"):
            assert sha(av["path"]) == av["sha256"]
            cod = np.load(av["path"], mmap_mode="r")
        retained = 0
        for r in potential:
            q, t = r["query_position"], r["target_position"]
            f = r["features"]
            dense = {"minilm": f["minilm_score"], "tail": f["tail_score"]}
            if cod is not None:
                dense["coderank"] = float(cod[q] @ cod[t])
            if max(dense.values()) >= 0.65:
                continue
            retained += 1
            af = Function.model_validate(fs[q])
            bf = Function.model_validate(fs[t])
            aa, ah = _representations(af)
            bb, bh = _representations(bf)
            aa += [ah] if ah else []
            bb += [bh] if bh else []
            matches = []
            for a in aa:
                for b in bb:
                    calls = sorted(a.calls & b.calls)
                    if len(calls) < 3:
                        continue
                    score = _cosine(idx.vector(a.tokens), idx.vector(b.tokens))
                    if abs(score - f["block_score"]) > 1e-6:
                        continue
                    regions = []
                    for block, fn in [(a, af), (b, bf)]:
                        source = "\n".join(fn.code.splitlines()[block.line - fn.line : block.end_line - fn.line + 1])
                        try:
                            tree = ast.parse(textwrap.dedent(source))
                            nodes = len(list(ast.walk(tree)))
                        except SyntaxError:
                            nodes = 0
                        regions.append(
                            {
                                "line": block.line,
                                "end_line": block.end_line,
                                "coordinates": "native_absolute",
                                "source": source,
                                "nodes": nodes,
                                "calls": sorted(block.calls),
                            }
                        )
                    if min(z["nodes"] for z in regions) < 25:
                        continue
                    matches.append((min(z["nodes"] for z in regions), regions, calls, score))
            if not matches:
                continue
            nodes, regions, calls, score = max(matches, key=lambda x: x[0])
            candidates.append(
                {
                    "id": "DG-" + digest(cid + ":" + str(q) + ":" + str(t))[:20],
                    "cohort_id": cid,
                    "repository": p["repository"],
                    "revision": p["revision"],
                    "scope": p["scope"],
                    "query_position": q,
                    "target_position": t,
                    "source": r["source"],
                    "mechanism": {
                        "route": "below-gate-ablation",
                        "region_match": regions,
                        "shared_calls": calls,
                        "minimum_region_nodes": nodes,
                        "strength": score,
                    },
                    "score": 0.6 * score + 0.4 * max(dense.values()),
                    "dense": dense,
                    "trace": {
                        "tfidf_score": f["tfidf_score"],
                        "raw_rank_positive_scores_corpus_ties": f["tfidf_rank"],
                        "zero_shared_postings": False,
                        "first_sparse_loss": "below_score_floor",
                        "balanced_exploration_floor": 0.35,
                    },
                    "query_in_bank": True,
                    "gate_rejected": True,
                    "outcome": "unknown",
                }
            )
        coverage.append(
            {
                "cohort_id": cid,
                "bank_block_prefilter_rejections": len(potential),
                "verified_original_dense_rejections": retained,
            }
        )
    candidates.sort(key=lambda r: (-r["mechanism"]["minimum_region_nodes"], -r["mechanism"]["strength"], r["id"]))
    chosen = []
    bodies = set()
    signatures = set()
    repos = collections.Counter()
    for r in candidates:
        key = tuple(sorted(r["source"][s]["source_sha256"] for s in ["query", "target"]))
        sig = tuple(r["mechanism"]["shared_calls"])
        if key in bodies or sig in signatures or repos[r["repository"]] >= 2:
            continue
        chosen.append(r)
        bodies.add(key)
        signatures.add(sig)
        repos[r["repository"]] += 1
        if len(chosen) == 4:
            break
    write(out / "eligible.jsonl", candidates)
    write(out / "selected.jsonl", chosen)
    write(
        out / "CENSUS.json",
        {
            "matched_region_options": len(candidates),
            "selected": len(chosen),
            "coverage": coverage,
            "selection_sha256": sha(out / "selected.jsonl"),
            "provider_calls": 0,
            "separate_from_original_recipe": True,
        },
    )
    print("selected", len(chosen), "from", len(candidates), flush=True)
    for r in chosen:
        print(
            r["id"],
            r["repository"],
            r["mechanism"]["minimum_region_nodes"],
            r["dense"],
            r["source"]["query"]["source_id"],
            r["source"]["target"]["source_id"],
            flush=True,
        )


if __name__ == "__main__":
    main()
