# ruff: noqa: E402, E731
# Frozen experiment harness; imports follow runtime selection; predicates close over the current query.
"""Exhaustive recorded-query parity and deterministic standalone regressions."""

import argparse
import gzip
import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path

OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT / "src"))
from dry_lint.operation_blocks import OperationBlocksComparer

from dry_lint.bench_background import BenchBackground
from dry_lint.detector import why_skipped
from dry_lint.functions import behaviour_tokens
from dry_lint.models import Function
from dry_lint.settings import Settings

spec = importlib.util.spec_from_file_location(
    "frozen_operation_blocks", OUT / "before-src/dry_lint/operation_blocks.py"
)
frozen = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = frozen
spec.loader.exec_module(frozen)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def lines(path):
    with path.open() as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def load(cid):
    folder = OUT / "inputs" / cid
    raw = (folder / "background.json.gz").read_bytes()
    bg = BenchBackground.decode(raw)
    payload = json.loads(gzip.decompress((folder / "candidate-index.json.gz").read_bytes()))
    assert payload["binding"]["background_sha256"] == sha(raw)
    native = {int(k): Function.model_validate(v) for k, v in payload["functions"].items()}
    fs = []
    for i, doc in enumerate(bg.documents):
        if i in native:
            f = native[i]
            assert sha(f.code.encode()) == doc.source_sha256
        else:
            path, _, qual = doc.id.partition("::")
            owner, _, name = qual.rpartition(".")
            f = Function(path=path, owner=owner or None, name=name or qual, line=0, end_line=0, code="")
        f.tokens = doc.tokens()
        assert f.qualname == doc.id
        fs.append(f)
    return fs, native


def representations(c):
    h = hashlib.sha256()
    count = 0
    for parents in (c._parents, c._fallback_parents):
        for blocks in parents:
            for b in blocks:
                # Preserve every sequence, including vector insertion/summation order.
                values = [
                    b.line,
                    b.end_line,
                    b.kind,
                    b.tokens,
                    sorted(b.operations),
                    sorted(b.calls),
                    [(k, v.hex()) for k, v in b.vector.items()],
                    b.anchors,
                    sorted(b.retained),
                ]
                h.update(json.dumps(values).encode())
                count += 1
            h.update(b"parent\n")
    for posts in (c._postings, c._fallback_postings):
        h.update(json.dumps(sorted(posts.items())).encode())
    return h.hexdigest(), count


def run(cid, gold_only=False):
    started = time.perf_counter()
    fs, native = load(cid)
    settings = Settings()
    positions = {id(f): i for i, f in enumerate(fs)}
    before = frozen.OperationBlocksComparer()
    before.index(fs)
    after = OperationBlocksComparer()
    after.index(fs)
    assert list(before.tfidf.idf.items()) == list(after.tfidf.idf.items())
    reps = representations(before)
    assert reps == representations(after)
    folder = OUT / "inputs" / cid
    gold = list(lines(folder / "gold-directions.jsonl"))
    gold_ids = {r["query"] for r in gold}
    known_count = winners = gold_count = 0
    novel = []
    known_hash = hashlib.sha256()
    samples = []
    buckets = {}
    native_ids = {id(f) for f in native.values()}

    def compare(f, k, allowed):
        left = before.neighbours(f, k, allowed)
        right = after.neighbours(f, k, allowed)
        a = [(positions[id(o)], s.hex()) for o, s in left]
        b = [(positions[id(o)], s.hex()) for o, s in right]
        assert a == b, (cid, f.qualname, a, b)
        assert all(x is y for (x, _), (y, _) in zip(left, right, strict=True))
        for target, _score in left:
            assert before.similarity(f, target).hex() == after.similarity(f, target).hex()
            assert before.shared(f, target) == after.shared(f, target)
        return a

    if not gold_only:
        # Fresh Function objects with identical source/identity fields cannot use the
        # indexed-object fast path. Each sweep has 1,000 different query objects, so
        # the one-entry cache helps fallback within a call, not a whole-history hit.
        import gc
        import heapq
        import os
        import tracemalloc
        import weakref

        sample = heapq.nsmallest(
            1000, lines(folder / "queries.jsonl"), key=lambda r: sha(("paired-runtime-v1/" + str(r["query"])).encode())
        )
        standalone = []
        for r in sample:
            f = fs[r["query"]].model_copy()
            base = {fs[i].qualname for i, *_ in r["baseline"]}

            def allowed(other, f=f, base=base):
                return (
                    id(other) in native_ids
                    and other.qualname != f.qualname
                    and other.qualname not in base
                    and not why_skipped(f, other, settings)
                )

            standalone.append((f, allowed))

        def sweep(c):
            return [
                [(positions[id(other)], score.hex()) for other, score in c.neighbours(f, 1, allowed)]
                for f, allowed in standalone
            ]

        assert sweep(before) == sweep(after)  # warm native-target vector memoization equally
        standalone_trials = []
        for repeat in range(3):
            for arm, c in (
                [("before", before), ("after", after)] if repeat % 2 == 0 else [("after", after), ("before", before)]
            ):
                load_before = os.getloadavg()
                cpu = time.process_time()
                start = time.perf_counter()
                outputs = sweep(c)
                standalone_trials.append(
                    {
                        "repeat": repeat + 1,
                        "arm": arm,
                        "seconds": time.perf_counter() - start,
                        "cpu_seconds": time.process_time() - cpu,
                        "output_sha256": sha(json.dumps(outputs).encode()),
                        "queries": len(standalone),
                        "load_before": load_before,
                        "load_after": os.getloadavg(),
                    }
                )
        assert len({r["output_sha256"] for r in standalone_trials}) == 1
        gc.collect()
        tracemalloc.start()
        old_blocks = []
        old_queries = []
        for i, (f, _) in enumerate(standalone):
            q = f.model_copy(update={"line": 1_000_000 + i, "end_line": 1_000_000 + i + f.end_line - f.line})
            old_queries.append(weakref.ref(q))
            old_blocks.extend(weakref.ref(b) for b in after._query_blocks(q))
            after._query_blocks(q, fallback=True)
        del q
        gc.collect()
        retained, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert not any(ref() is not None for ref in old_queries)
        live = sum(ref() is not None for ref in old_blocks)
        assert live <= 12 and len(after._query_fallback) <= 13
        memory = {
            "distinct_source_edits": len(standalone),
            "live_original_blocks_from_history": live,
            "current_original_blocks": len(after._query_original),
            "current_fallback_blocks": len(after._query_fallback),
            "query_objects_retained": 0,
            "traced_retained_bytes_including_weakref_audit": retained,
            "traced_peak_bytes_including_weakref_audit": peak,
            "ast_cache_scope": "one _representations call; no AST is stored on comparer",
            "persistent_cache_bound": "one source key, <=12 original and <=13 fallback blocks; no full-token vectors cached for standalone query",
        }
        (OUT / "results" / f"{cid}-standalone.json").write_text(
            json.dumps(
                {
                    "cohort": cid,
                    "protocol": "same-process paired sweeps after equal warmup; both fitted indexes resident; alternating order; no concurrent job; fresh non-indexed Function objects; same 1000-query selection as construction benchmark",
                    "trials": standalone_trials,
                    "memory": memory,
                },
                indent=2,
            )
            + "\n"
        )
        print(json.dumps({"cohort": cid, "standalone_completed": len(standalone), "memory": memory}), flush=True)
    for r in lines(folder / "queries.jsonl"):
        q = r["query"]
        if gold_only and q not in gold_ids:
            continue
        f = fs[q]
        base = {fs[i].qualname for i, *_ in r["baseline"]}
        allowed = lambda other, f=f, base=base: (
            id(other) in native_ids
            and other.qualname != f.qualname
            and other.qualname not in base
            and not why_skipped(f, other, settings)
        )
        # k=64 compares full emitted ordering, not just the first winner.
        result = compare(f, 64, allowed)
        known_count += 1
        winners += bool(result)
        gold_count += q in gold_ids
        known_hash.update(json.dumps([q, result]).encode())
        bucket = ("original" if r["original_winner"] is not None else "fallback") if result else "abstention"
        buckets[bucket] = buckets.get(bucket, 0) + 1
        samples.append((sha(f"novel-v1/{q}".encode()), q, bucket, list(base)))
        if known_count % 2000 == 0:
            print(json.dumps({"cohort": cid, "known_queries_completed": known_count}), flush=True)
    # Gold directions without eligible recorded queries must still be replayed.
    recorded = {r["query"] for r in lines(folder / "queries.jsonl")}
    extra_gold = 0
    for q in sorted(gold_ids - recorded):
        compare(fs[q], 64, lambda other, q=q: id(other) in native_ids and other.qualname != fs[q].qualname)
        extra_gold += 1
    assert gold_count + extra_gold == len(gold_ids)
    selected = []
    for bucket in ("original", "fallback", "abstention"):
        selected.extend(sorted(s for s in samples if s[2] == bucket)[:12])
    for _, q, bucket, base in selected:
        original = fs[q]
        # A new source identity, then an actual executable-source edit under the
        # original qualname. No query is added to the IDF fit.
        for kind in ("standalone", "edited"):
            f = original.model_copy(deep=True)
            if kind == "standalone":
                f.path = "novel/" + f.path
                f.line += 17
                f.end_line += 17
            else:
                f.code += "\n    audit_operation_packet()"
                f.end_line += 1
                f.tokens = behaviour_tokens(f)
            allowed = lambda other, f=f, base=base: (
                id(other) in native_ids
                and other.qualname != f.qualname
                and other.qualname not in base
                and not why_skipped(f, other, settings)
            )
            result = compare(f, 64, allowed)
            novel.append({"source_query": q, "bucket": bucket, "kind": kind, "outputs": result})
    result = {
        "cohort": cid,
        "gold_only": gold_only,
        "documents": len(fs),
        "native": len(native),
        "all_representations_sha256": reps[0],
        "route_blocks_compared": reps[1],
        "known_queries": known_count,
        "known_queries_with_winners": winners,
        "known_output_sha256": known_hash.hexdigest(),
        "gold_direction_rows": len(gold),
        "gold_query_ids": len(gold_ids),
        "gold_query_ids_in_recorded": gold_count,
        "additional_gold_queries": extra_gold,
        "buckets": buckets,
        "novel": novel,
        "exact_float_hex_order_native_identity_and_pair_evidence": True,
        "elapsed_seconds": time.perf_counter() - started,
    }
    (OUT / "results" / f"{cid}-parity.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "novel"}), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--cohort", required=True)
    p.add_argument("--gold-only", action="store_true")
    args = p.parse_args()
    run(args.cohort, args.gold_only)
