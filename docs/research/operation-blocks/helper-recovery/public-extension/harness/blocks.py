"""Frozen v1 versus complete-helper on every mapped public-pin gold direction."""

import time
from collections import Counter
from trace import trace
from types import SimpleNamespace

from common import HERE, dump, folders, json, jsonl, load, read
from dry_lint.operation_blocks import OperationBlocksComparer
from helper_fallback_v1 import HelperFallback

from dry_lint.costs import estimate
from dry_lint.detector import why_skipped
from dry_lint.judges.jev import CONTEXT_QUESTIONS, state
from dry_lint.models import Candidate
from dry_lint.settings import Settings

SETTINGS = Settings(budget={"usd": 0.04})
CONCEPT = SimpleNamespace(name="anthropic", model="claude-sonnet-5-5", prompt_policy="concept")
CLAUDE = SimpleNamespace(name="anthropic-operations", model="claude-sonnet-5-5", prompt_policy="shared-operations")
# Estimation only: no judge instance or credentials.
JEV = SimpleNamespace(
    name="jev",
    model="jev-1.14.0",
    input_text=lambda c: json.dumps({"model": "jev-1.14.0", "state": state(c, True), "questions": CONTEXT_QUESTIONS}),
)


def admit(fs, qi, items, judges):
    total = 0.0
    selected = []
    charges = []
    for ti, score, comparer, lane in items:
        c = Candidate(new=fs[qi], existing=fs[ti], similarity=round(score, 3), comparer=comparer, lane=lane)
        charge = sum(estimate(j, [c], SETTINGS) for j in judges)
        admitted = total + charge <= 0.04
        if admitted:
            total += charge
            selected.append(ti)
        charges.append(dict(target=ti, charge=charge, cumulative=total, admitted=admitted))
    return dict(selected=selected, charges=charges, total=total)


def baseline(c, qi, native):
    f = c.functions[qi]
    ranked = c.tfidf.similar(f.tokens, exclude={qi})
    floor = 0.3 if f.lines < 6 else 0.5
    first = [(i, s) for i, s in ranked if s >= floor and c.functions[i].path != f.path][:3]
    twenty = [(i, s) for i, s in ranked if s >= 0.35 and c.functions[i].qualname != f.qualname][:20]
    chosen = []
    seen = set()
    for lane, values in [("baseline", first), ("exploration", twenty)]:
        for i, s in values:
            if c.functions[i].qualname in seen or i not in native or why_skipped(f, c.functions[i], SETTINGS):
                continue
            seen.add(c.functions[i].qualname)
            chosen.append((i, s, "tfidf:2", lane))
    return chosen, ranked


def main():
    start = time.perf_counter()
    allrows = []
    summaries = []
    checks = Counter()
    gold = read(HERE / "selected-rows.jsonl")
    for p in folders():
        folder = p.parent
        m, bg, fs, mask = load(folder)
        native = {i for i, n in enumerate(mask) if n}
        mappings = [
            (r, mp)
            for r in gold
            for mp in r["mappings"]
            if mp["cohort_id"] == m["cohort_id"] and mp["status"] == "mapped"
        ]
        assert bg.max_df == 0.3  # frozen v1's supported fit; never replace a different fit silently.
        c = OperationBlocksComparer()
        c.index(fs)
        assert c.tfidf.idf == bg.index().idf and c.tfidf.size == len(bg.documents)
        before = [f.model_dump(mode="json") for f in fs]
        v = HelperFallback(c)
        pos = {id(f): i for i, f in enumerate(fs)}
        queries = {}
        for _r, mp in mappings:
            for s in mp["sources"].values():
                i = s["position"]
                assert fs[i].qualname == s["source_id"] and bg.documents[i].source_sha256 == s["source_sha256"]
                queries[i] = None
        for qi in queries:
            f = fs[qi]
            base, ranked = baseline(c, qi, native)
            bids = {r[0] for r in base}
            excluded = {fs[i].qualname for i in bids}

            def allowed(other, pos=pos, native=native, excluded=excluded, f=f):
                return (
                    pos[id(other)] in native
                    and other.qualname not in excluded
                    and other.qualname != f.qualname
                    and not why_skipped(f, other, SETTINGS)
                )

            old = c.neighbours(f, 1, allowed)
            new = v.neighbours(f, 1, allowed)
            if old:
                assert new == old
                checks["original_winner_preserved"] += 1
            for fun, _ in new:
                assert fun is fs[pos[id(fun)]] and fun.qualname != f.qualname
            original = base + [(pos[id(g)], s, "operation-blocks:1", "exploration") for g, s in old]
            treatment = (
                original
                if old
                else base + [(pos[id(g)], s, "operation-blocks-helper-fallback:1", "exploration") for g, s in new]
            )
            ledgers = {
                a: {
                    budget: admit(fs, qi, items, judges)
                    for budget, judges in [("concept", [CONCEPT]), ("paired", [JEV, CLAUDE])]
                }
                for a, items in [("baseline", base), ("original", original), ("helper", treatment)]
            }
            for budget in ("concept", "paired"):
                assert set(ledgers["original"][budget]["selected"]) <= set(ledgers["helper"][budget]["selected"])
            queries[qi] = {
                "query": qi,
                "source_id": f.qualname,
                "baseline": base,
                "original": original,
                "helper": treatment,
                "ledgers": ledgers,
                "original_raw": [
                    (pos[id(g)], s) for g, s in c.neighbours(f, len(fs), lambda g, f=f: g.qualname != f.qualname)
                ],
                "helper_raw": [
                    (pos[id(g)], s) for g, s in v.neighbours(f, len(fs), lambda g, f=f: g.qualname != f.qualname)
                ],
            }
        results = []
        for row, mp in mappings:
            a, b = [mp["sources"][s]["position"] for s in ("new", "existing")]
            ds = []
            for qi, ti in ((a, b), (b, a)):
                q = queries[qi]
                t = trace(c, v, qi, ti, {r[0] for r in q["baseline"]})
                t.update(query_position=qi, target_position=ti)
                for arm in ("original", "helper"):
                    ranks = {i: (n + 1, s) for n, (i, s) in enumerate(q[arm + "_raw"])}
                    target_entry = next((i for i in q[arm] if i[0] == ti), None)
                    t[arm]["route_raw_rank_score"] = ranks.get(ti)
                    t[arm]["proposed"] = target_entry is not None
                    t[arm]["funded"] = {b: ti in q["ledgers"][arm][b]["selected"] for b in ("concept", "paired")}
                    t[arm]["pipeline_first_loss"] = {
                        b: "retained"
                        if t[arm]["funded"][b]
                        else "budget"
                        if target_entry
                        else "original_route_did_not_abstain"
                        if arm == "helper" and len(q["original"]) > len(q["baseline"])
                        else "top1"
                        if t[arm]["first_loss"] == "eligible"
                        else t[arm]["first_loss"]
                        for b in ("concept", "paired")
                    }
                ds.append(t)
            result = {
                k: row.get(k)
                for k in (
                    "row_id",
                    "pair_id",
                    "family_id",
                    "pair_lineage",
                    "dataset",
                    "label",
                    "accepted_gold",
                    "repository",
                    "revision",
                )
            }
            result.update(
                cohort_id=m["cohort_id"],
                background_sha256=folder.name,
                profiles=m["profiles"],
                mapping=mp,
                directions=ds,
            )
            results.append(result)
        assert before == [f.model_dump(mode="json") for f in fs]
        checks["immutable_backgrounds"] += 1
        jsonl(folder / "blocks-queries.jsonl", queries.values())
        jsonl(folder / "blocks-regression.jsonl", results)
        summary = {
            "cohort_id": m["cohort_id"],
            "repository": bg.repository,
            "revision": bg.revision,
            "profiles": m["profiles"],
            "rows": len(results),
            "queries": len(queries),
            "directions": len(results) * 2,
            "groups": [],
        }
        for label in sorted({r["label"] for r in results}):
            units = {r["pair_id"]: r for r in results if r["label"] == label}
            counts = {"label": label, "pair_background_units": len(units)}
            for budget in ("concept", "paired"):
                old = [any(d["original"]["funded"][budget] for d in r["directions"]) for r in units.values()]
                new = [any(d["helper"]["funded"][budget] for d in r["directions"]) for r in units.values()]
                counts[budget] = {
                    "original": sum(old),
                    "helper": sum(new),
                    "gained": sum(y and not x for x, y in zip(old, new, strict=True)),
                    "lost": sum(x and not y for x, y in zip(old, new, strict=True)),
                }
            summary["groups"].append(counts)
        dump(folder / "blocks-summary.json", summary)
        summaries.append(summary)
        allrows.extend(results)
        print("BLOCKS", m["cohort_id"], len(results), "rows", len(queries), "queries", flush=True)
    jsonl(HERE / "blocks-regression.jsonl", allrows)
    dump(
        HERE / "blocks-summary.json",
        {
            "cohorts": summaries,
            "checks": dict(checks),
            "wall_seconds": time.perf_counter() - start,
            "provider_calls": 0,
            "scope": "older observed public-source regression; no implicit cohort pooling; funding is cold .04 per query estimated exposure, not emitted reports or paid judging",
        },
    )


if __name__ == "__main__":
    main()
