"""Exact-background prefix MiniLM and frozen complete-statement fallback regression."""

import resource
import sqlite3
import time

import numpy as np
from common import HERE, OLD, dump, folders, json, jsonl, load, read, sha
from dry_lint.cpu_embedding import MiniLMEncoder
from harness import Replay
from views import token_count, views


def encode():
    started = time.perf_counter()
    encoder = MiniLMEncoder(OLD / "model-cache")
    contract = sha(json.dumps(encoder.contract, sort_keys=True).encode())
    db = sqlite3.connect(HERE / "encoder-cache.sqlite3")
    db.execute(
        "CREATE TABLE IF NOT EXISTS vectors (contract TEXT, content TEXT, vector BLOB, PRIMARY KEY(contract, content))"
    )
    stats = []
    viewcache = {}
    for p in folders():
        folder = p.parent
        m, bg, fs, native = load(folder)
        assert all(native), "CPU requires exact full-source competitors; never create a two-snippet matrix"
        start = time.perf_counter()
        records = []
        inputs = {sha(f.code.encode()): f.code for f in fs}
        for i, f in enumerate(fs):
            key = (f.path.rsplit(".", 1)[-1], f.name, sha(f.code.encode()))
            if key not in viewcache:
                viewcache[key] = (token_count(f.code), views(f))
            length, (vv, status) = viewcache[key]
            vs = [
                {
                    **v,
                    "absolute_line": f.line + v["relative_line"] - 1,
                    "absolute_end_line": f.line + v["relative_end_line"] - 1,
                    "function_id": f.qualname,
                }
                for v in vv
            ]
            records.append(
                {
                    "position": i,
                    "qualname": f.qualname,
                    "native": True,
                    "wordpieces": length,
                    "prefix_visible_wordpieces": min(256, length),
                    "omitted_wordpieces": max(0, length - 256),
                    "status": status,
                    "views": vs,
                }
            )
            for v in vs:
                inputs[v["input_sha256"]] = v["text"]
        jsonl(folder / "views.jsonl", records)
        vectors = {}
        missing = []
        for key in inputs:
            row = db.execute("SELECT vector FROM vectors WHERE contract=? AND content=?", (contract, key)).fetchone()
            if row:
                vector = np.frombuffer(row[0], dtype=np.float32).copy()
                assert vector.shape == (384,) and np.isfinite(vector).all() and abs(np.linalg.norm(vector) - 1) < 1e-5
                vectors[key] = vector
            else:
                missing.append(key)
        hits = len(vectors)
        t = time.perf_counter()
        for offset in range(0, len(missing), 64):
            keys = missing[offset : offset + 64]
            vs = encoder.encode([inputs[k] for k in keys])
            db.executemany(
                "INSERT INTO vectors VALUES (?,?,?)",
                [(contract, k, v.tobytes()) for k, v in zip(keys, vs, strict=True)],
            )
            db.commit()
            vectors.update(zip(keys, vs, strict=True))
            if offset % 512 == 0:
                print("ENCODE", folder.name[:8], offset, "/", len(missing), flush=True)
        seconds = time.perf_counter() - t
        matrix = np.asarray([vectors[sha(f.code.encode())] for f in fs], dtype=np.float32)
        assert matrix.shape == (len(bg.documents), 384)
        np.save(folder / "embeddings.npy", matrix)
        keys = []
        owners = []
        ordinals = []
        for r in records:
            for i, v in enumerate(r["views"]):
                keys.append(v["input_sha256"])
                owners.append(r["position"])
                ordinals.append(i)
        vm = np.asarray([vectors[k] for k in keys], dtype=np.float32).reshape(-1, 384)
        np.savez(
            folder / "view-vectors.npz",
            vectors=vm,
            owners=np.asarray(owners),
            ordinals=np.asarray(ordinals),
            contract=np.asarray(contract),
        )
        # Fresh inference parity protects content/contract cache reuse across revisions and scopes.
        check = encoder.encode([fs[0].code])
        delta = float(np.max(np.abs(check[0] - matrix[0])))
        assert delta < 1e-5
        row = {
            "cohort_id": m["cohort_id"],
            "repository": bg.repository,
            "revision": bg.revision,
            "background": folder.name,
            "functions": len(fs),
            "views": len(keys),
            "unique_inputs": len(inputs),
            "cache_hits": hits,
            "cache_misses": len(missing),
            "encoder_seconds": seconds,
            "wall_seconds": time.perf_counter() - start,
            "encoder_contract": encoder.contract,
            "contract_sha256": contract,
            "fresh_cache_parity_max_abs": delta,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "artifacts": {
                n: {"sha256": sha((folder / n).read_bytes()), "bytes": (folder / n).stat().st_size}
                for n in ("embeddings.npy", "view-vectors.npz", "views.jsonl")
            },
        }
        dump(folder / "encoding.json", row)
        stats.append(row)
        print("ENCODED", m["cohort_id"], len(fs), "new", len(missing), flush=True)
    dump(
        HERE / "encoding-summary.json",
        {"cohorts": stats, "wall_seconds": time.perf_counter() - started, "provider_calls": 0, "downloads": 0},
    )


def evaluate():
    gold = read(HERE / "selected-rows.jsonl")
    allrows = []
    summaries = []
    started = time.perf_counter()
    for p in folders():
        folder = p.parent
        start = time.perf_counter()
        replay = Replay(folder)
        m = replay.manifest
        assert replay.base.comparer.tfidf.idf == replay.bg.index().idf
        mappings = [
            (r, mp)
            for r in gold
            for mp in r["mappings"]
            if mp["cohort_id"] == m["cohort_id"] and mp["status"] == "mapped"
        ]
        queries = {s["position"]: None for _, mp in mappings for s in mp["sources"].values()}
        before = [f.model_dump(mode="json") for f in replay.fs]
        queryrows = []
        for qi in queries:
            arms = replay.proposals(replay.fs[qi])
            queries[qi] = arms
            assert [c.key for c in arms["treatment"][: len(arms["original"])]] == [c.key for c in arms["original"]]
            for arm, cs in arms.items():
                assert all(c.new.qualname != c.existing.qualname for c in cs)
                queryrows.append(
                    {
                        "query_position": qi,
                        "query": replay.fs[qi].qualname,
                        "arm": arm,
                        "paired": replay.ledger(cs),
                        "standalone": replay.ledger(cs, paired=False),
                    }
                )
        results = []
        for row, mp in mappings:
            a, b = [mp["sources"][s]["position"] for s in ("new", "existing")]
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
                directions=[replay.ranks(replay.fs[x], replay.fs[y], queries[x]) for x, y in ((a, b), (b, a))],
            )
            results.append(result)
        assert before == [f.model_dump(mode="json") for f in replay.fs]
        jsonl(folder / "cpu-regression.jsonl", results)
        jsonl(folder / "cpu-query-ledgers.jsonl", queryrows)
        summary = {
            "cohort_id": m["cohort_id"],
            "repository": replay.bg.repository,
            "revision": replay.bg.revision,
            "profiles": m["profiles"],
            "rows": len(results),
            "queries": len(queries),
            "directions": len(results) * 2,
            "wall_seconds": time.perf_counter() - start,
            "index_seconds": replay.index_seconds,
            "groups": [],
        }
        for label in sorted({r["label"] for r in results}):
            units = {r["pair_id"]: r for r in results if r["label"] == label}
            counts = {"label": label, "pair_background_units": len(units)}
            for arm in ("baseline3", "wide", "original", "treatment"):
                counts[arm] = sum(any(d["stages"][arm]["funded"] for d in r["directions"]) for r in units.values())
            counts["gained"] = sum(
                any(d["stages"]["treatment"]["funded"] for d in r["directions"])
                and not any(d["stages"]["original"]["funded"] for d in r["directions"])
                for r in units.values()
            )
            counts["lost"] = sum(
                any(d["stages"]["original"]["funded"] for d in r["directions"])
                and not any(d["stages"]["treatment"]["funded"] for d in r["directions"])
                for r in units.values()
            )
            assert counts["lost"] == 0
            summary["groups"].append(counts)
        summaries.append(summary)
        allrows.extend(results)
        dump(folder / "cpu-summary.json", summary)
        print("CPU", m["cohort_id"], len(results), "rows", len(queries), "queries", flush=True)
    jsonl(HERE / "cpu-regression.jsonl", allrows)
    dump(
        HERE / "cpu-summary.json",
        {
            "cohorts": summaries,
            "wall_seconds": time.perf_counter() - started,
            "provider_calls": 0,
            "scope": "older observed public-source regression; no discovery sweep or implicit cohort pooling; .04 cold-query estimated paired funding",
        },
    )


if __name__ == "__main__":
    encode()
    evaluate()
