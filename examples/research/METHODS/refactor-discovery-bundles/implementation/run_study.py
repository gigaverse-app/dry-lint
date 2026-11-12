# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B007, B023, E741, F403, F405, I001
"""Provider-free development replay; writes only alongside this script."""

from bundles import *
import collections
import time
from dry_lint.bench_background import BenchBackground
from dry_lint.comparers import TfidfComparer
from dry_lint.detector import Detector
from dry_lint.extractors import PythonExtractor
from dry_lint.typescript import TypeScriptExtractor

HERE = Path(__file__).resolve().parent
BANK = ROOT / "jobs/complementary-signal-learning/.lab-results"
CID = "bg-a35412534e3d42e7"
AFTER_CID = "bg-4edc2f988654836c"


def read_jsonl(path):
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


def write(path, data):
    path = HERE / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def load_cohort(cid):
    panel = next(r for r in read_jsonl(BASE / "panels.jsonl") if r["cohort_id"] == cid)
    source = Source(**{k: panel[k] for k in Source.model_fields})
    assert sha(source.functions_path) == source.functions_sha256
    assert sha(panel["background_path"]) == source.background_sha256
    bg = BenchBackground.decode(Path(panel["background_path"]).read_bytes())
    fs = [Function.model_validate(r) for r in read_jsonl(source.functions_path)]
    for f, d in zip(fs, bg.documents, strict=True):
        assert f.qualname == d.id and digest(f.code) == d.source_sha256
        f.tokens = d.tokens()
    settings = Settings(discovery={"enabled": False}, include=source.scope["include"], exclude=source.scope["exclude"])
    comparer = TfidfComparer(max_df=bg.max_df)
    detector = Detector(fs, settings, comparer, [PythonExtractor(), TypeScriptExtractor()])
    return source, fs, detector


def review(row, c):
    return Review(
        authority=row["authority"],
        artifact=str(BASE / "gold-rows.jsonl"),
        artifact_sha256=sha(BASE / "gold-rows.jsonl"),
        row_id=row["row_id"],
        category="duplicate-scope-unspecified" if row["label"] == "duplicate" else "separate",
        evidence="Existing source-reviewed registry label, replayed as evidence; not a new review or actual prior judge confirmation. The inventory does not specify operation boundaries or whole-function interchangeability.",
        inspected=[Boundary.of(f) for f in (c.new, c.existing)],
    )


def make_lead(c, source, path, edges):
    return Lead(
        candidate=c,
        source=source,
        boundaries=[Boundary.of(f) for f in (c.new, c.existing)],
        path=path,
        edges=edges,
        uncertainty="Retrieval evidence only. Similarity is not a calibrated probability. Inspect signatures, docstrings, operation boundaries and callers; shared tokens can represent different behavior. No duplicate judgment exists for this lead in this report.",
    )


def choose(seed, pool, method):
    if sum(token_proxy(f.code + f.context) for f in (seed.candidate.new, seed.candidate.existing)) > 6000:
        return Bundle(method=method, seed=seed, state="escalate-anchor-too-large")
    selected = []
    seen = {seed.candidate.key}
    files = {seed.candidate.new.path, seed.candidate.existing.path}
    pending = list(pool)
    while pending and len(selected) < 4:
        current = Bundle(method=method, seed=seed, leads=selected)
        known = set(unique_functions(current))

        def ordering(l):
            fs = [l.candidate.new, l.candidate.existing]
            new_files = len({f.path for f in fs} - files)
            extra = sum(
                token_proxy(f.code + f.context)
                for f in fs
                if (f.qualname, digest(f.code), digest(f.context)) not in known
            )
            return (-new_files, extra, len(l.path), -l.candidate.similarity, l.candidate.key)

        if method == "diverse-bundle":
            pending.sort(key=ordering)
        lead = pending.pop(0)
        if lead.candidate.key in seen or lead.candidate.filtered:
            continue
        seen.add(lead.candidate.key)
        try:
            Bundle(method=method, seed=seed, leads=selected + [lead])
        except ValueError:
            continue
        selected.append(lead)
        files.update((lead.candidate.new.path, lead.candidate.existing.path))
    return Bundle(method=method, seed=seed, leads=selected)


def bank_pool(seed, source, fs, detector, rows, bank_sha):
    """Censored selected-query bank proxy, not the all-node graph-worker graph."""
    by_query = collections.defaultdict(list)
    for row in rows:
        if row["native_eligible"]:
            by_query[row["query_position"]].append(row)
    for rs in by_query.values():
        rs.sort(key=lambda r: (-r["scores"]["fixed_fusion"], r["candidate_id"]))
    positions = {f.qualname: i for i, f in enumerate(fs)}
    frontier = [(positions[f.qualname], [f.qualname], []) for f in (seed.candidate.new, seed.candidate.existing)]
    output = []
    for depth in range(2):
        next_frontier = []
        for q, path, edges in frontier:
            for row in by_query.get(q, [])[:3]:
                target = row["target_position"]
                a, b = fs[q], fs[target]
                if b.qualname in path:
                    continue
                assert row["source"]["functions_sha256"] == source.functions_sha256
                for f, ep in ((a, row["source"]["query"]), (b, row["source"]["target"])):
                    assert f.qualname == ep["source_id"] and digest(f.code) == ep["source_sha256"]
                c = detector.pair(a, b, row["scores"]["fixed_fusion"]).model_copy(
                    update={"lane": "exploration", "comparer": "bank-fixed-rrf60:1"}
                )
                common = detector.comparer.shared(a, b, 8)
                edge = Edge(
                    left=a.qualname,
                    right=b.qualname,
                    kind="bank-neighbour",
                    artifact=str(BANK / "bank" / CID / "candidates.jsonl") + "#" + row["candidate_id"],
                    artifact_sha256=bank_sha,
                    evidence=f"Fixed fusion top3 outgoing bank edge; TFIDF={row['features']['tfidf_score']:.3f}; MiniLM={row['features']['minilm_score']}; shared behavior tokens={common}. Prefix/tail are correlated retrieval evidence.",
                )
                p = path + [b.qualname]
                es = edges + [edge]
                if c.key != seed.candidate.key and not c.filtered:
                    output.append(make_lead(c, source, p, es))
                next_frontier.append((target, p, es))
        frontier = next_frontier
    output.sort(key=lambda l: (len(l.path), -l.candidate.similarity, l.candidate.key))
    return output


def main():
    started = time.monotonic()
    source, fs, detector = load_cohort(CID)
    bank_path = BANK / "bank" / CID / "candidates.jsonl"
    bank_sha = sha(bank_path)
    rows = read_jsonl(bank_path)
    # Development demonstrations explicitly chosen in advance; no holdout outcomes enter.
    gold = [
        r
        for r in read_jsonl(BASE / "gold-rows.jsonl")
        if r.get("repository") == "gigaverse-app/due" and r["row_id"].startswith("private-historical400-v1:due-183-")
    ]
    selected_ids = ["due-183-manual0-before", "due-183-manual1-before", "due-183-0-before", "due-183-1-before"]
    by_name = {f.qualname: f for f in fs}
    outcomes = {}
    for r in gold:
        if r["revision"] != source.revision:
            continue
        names = tuple(sorted(v["source_id"] for v in r["sources"].values()))
        outcomes[names] = r
    all_metrics = []
    bundles = []
    exposures = []
    for rid in selected_ids:
        row = next(r for r in gold if r["id"] == rid)
        a, b = (by_name[row["sources"][side]["source_id"]] for side in ("new", "existing"))
        c = detector.pair(a, b, detector.comparer.similarity(a, b))
        seed = Seed(
            candidate=c,
            source=source,
            review=review(row, c),
            mode="source_gold_oracle_replay" if row["label"] == "duplicate" else "false_seed_control",
        )
        actual_primaries = detector.candidates([a])
        natural = any(p.key == c.key and p.lane == "baseline" for p in actual_primaries)
        relatives = detector.relatives([a], [c])
        native = []
        for relative in relatives:
            edge = Edge(
                left=relative.new.qualname,
                right=relative.existing.qualname,
                kind="native-relative",
                artifact=str(SRC / "dry_lint/detector.py") + ":322",
                artifact_sha256=sha(SRC / "dry_lint/detector.py"),
                evidence=f"Actual pinned Detector.relatives, baseline parent, neighbours=3; TFIDF={relative.similarity}; shared behavior tokens={detector.comparer.shared(relative.new, relative.existing, 8)}. Conditional on seed report and available budget; no judge replay performed.",
            )
            native.append(make_lead(relative, source, [edge.left, edge.right], [edge]))
        pool = bank_pool(seed, source, fs, detector, rows, bank_sha)
        for method, candidates in [
            ("current-one-hop", native),
            ("bank-two-hop-proxy", pool),
            ("diverse-bundle", native + pool),
        ]:
            bundle = choose(seed, candidates, method)
            validate_source(bundle, fs, source)
            report = native_report(bundle)
            stem = f"samples/{rid}-{method}"
            write(stem + ".json", bundle.model_dump(mode="json", by_alias=True))
            (HERE / (stem + ".md")).write_text(render(bundle))
            write(stem + "-native-report.json", report.model_dump(mode="json", by_alias=True))
            counts = collections.Counter()
            pair_labels = []
            for lead in bundle.leads:
                match = outcomes.get(tuple(sorted((lead.candidate.new.qualname, lead.candidate.existing.qualname))))
                label = match["label"] if match else "unknown"
                counts[label] += 1
                pair_labels.append(
                    {
                        "pair_key": lead.candidate.key,
                        "label": label,
                        "row_id": match["row_id"] if match else None,
                        "label_scope": match.get("label_scope") if match else None,
                        "additional_confirmed_operation_count": None,
                        "branch": lead.path[:2],
                    }
                )
            m = metrics(bundle) | {
                "seed_id": rid,
                "seed_mode": seed.mode,
                "seed_naturally_baseline_admitted": natural,
                "method": method,
                "known_positive_pairs": counts["duplicate"],
                "known_separate_pairs": counts["separate"],
                "unknown_pairs": counts["unknown"],
                "additional_independently_confirmed_operations": 0,
                "operation_yield_measured": False,
                "labels": pair_labels,
                "sample": stem + ".json",
                "native_relatives_before_bundle_bounds": len(native),
                "generic_leads": None,
                "generic_leads_note": "No independent genericity labels; unknown is not negative.",
            }
            all_metrics.append(m)
            bundles.append(bundle)
        exposures.append(
            {
                "seed_id": rid,
                "natural_baseline": natural,
                "conditional_native_relatives": len(native),
                "label_free_bank_pool_pairs": len({l.candidate.key for l in pool}),
                "seed_label": row["label"],
                "counterfactual_reported_seed": True,
            }
        )
    # Exact before/after negative regression: never carry the before source evidence to the after pin.
    after, afs, adet = load_cohort(AFTER_CID)
    aby = {f.qualname: f for f in afs}
    ar = next(r for r in gold if r["id"] == "due-183-0-after")
    ac = adet.pair(*(aby[ar["sources"][s]["source_id"]] for s in ("new", "existing")), 0.0)
    aseed = Seed(candidate=ac, source=after, review=review(ar, ac), mode="false_seed_control", status="rejected")
    stopped = Bundle(method="after-consolidation-control", seed=aseed, state="stopped-seed")
    write("samples/after-consolidation-control.json", stopped.model_dump(mode="json", by_alias=True))
    (HERE / "samples/after-consolidation-control.md").write_text(render(stopped))
    write(
        "controls.json",
        {
            "before_after": {
                "before": "due-183-0-before",
                "after": ar["row_id"],
                "before_revision": source.revision,
                "after_revision": after.revision,
                "after_category": "separate",
                "not_relabelled_already_shared": True,
                "after_expansion": len(stopped.leads),
                "note": "Existing negative label; exact-source post-consolidation control. Does not establish all wrappers are shared.",
            },
            "false_seed": {
                "mode": "known separate counterfactually injected as reported, same proposal budgets",
                "exposure": [m for m in all_metrics if m["seed_mode"] == "false_seed_control"],
                "after_seed_rejection_state": feedback_state("rejected", []),
                "leads_after_seed_rejection": 0,
            },
        },
    )
    write(
        "outcomes.json",
        {
            "schema": 1,
            "kind": "development source-gold/oracle replay, not judge execution",
            "cohort": source.model_dump(),
            "input_bank_sha256": bank_sha,
            "outcomes_joined_after_generation": True,
            "source_labels_used_for_graph_edges_or_ranking": False,
            "scope_note": "Configured due-183 demonstration; not pooled with diagnostic-scope historical results; three correlated positive seed orientations, one negative control, not independent families.",
            "metrics": all_metrics,
            "seed_exposures": exposures,
            "wall_seconds": round(time.monotonic() - started, 3),
            "provider_calls": 0,
            "real_prior_confirmed_seeds": 0,
        },
    )
    write("bundle.schema.json", Bundle.model_json_schema(by_alias=True))
    write(
        "INPUTS.json",
        {
            "source": source.model_dump(),
            "after_source": after.model_dump(),
            "bank": {"path": str(bank_path), "sha256": bank_sha},
            "product_modules": {
                str(p.relative_to(SRC)): sha(p)
                for p in [SRC / "dry_lint/models.py", SRC / "dry_lint/report.py", SRC / "dry_lint/detector.py"]
            },
            "selection": selected_ids,
            "seed_evidence": {"path": str(BASE / "gold-rows.jsonl"), "sha256": sha(BASE / "gold-rows.jsonl")},
        },
    )
    print(
        json.dumps(
            {
                "bundles": len(bundles),
                "metrics": [
                    {
                        k: m[k]
                        for k in (
                            "seed_id",
                            "method",
                            "leads",
                            "known_positive_pairs",
                            "known_separate_pairs",
                            "unknown_pairs",
                            "bundle_source_token_proxy",
                            "source_token_reuse",
                        )
                    }
                    for m in all_metrics
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
