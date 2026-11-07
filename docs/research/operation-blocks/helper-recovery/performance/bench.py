"""Offline isolated-process construction/query profiler and exact-output recorder."""

import argparse
import cProfile
import gc
import gzip
import hashlib
import json
import os
import platform
import pstats
import resource
import sys
import time
from pathlib import Path

OUT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--arm", choices=["before", "after"], required=True)
parser.add_argument("--cohort", required=True)
parser.add_argument("--profile", action="store_true")
parser.add_argument("--label", default="run")
a = parser.parse_args()
sys.path.insert(0, str(OUT / ("before-src" if a.arm == "before" else "src")))
from dry_lint.operation_blocks import OperationBlocksComparer  # noqa: E402 -- import only after selecting the frozen runtime

from dry_lint.bench_background import BenchBackground  # noqa: E402 -- import only after selecting the frozen runtime
from dry_lint.detector import why_skipped  # noqa: E402 -- import only after selecting the frozen runtime
from dry_lint.models import Function  # noqa: E402 -- import only after selecting the frozen runtime
from dry_lint.settings import Settings  # noqa: E402 -- import only after selecting the frozen runtime


def digest(data):
    return hashlib.sha256(data).hexdigest()


def rss():
    return int(Path("/proc/self/status").read_text().split("VmRSS:")[1].split()[0])


def load():
    folder = OUT / "inputs" / a.cohort
    bg = BenchBackground.decode((folder / "background.json.gz").read_bytes())
    payload = json.loads(gzip.decompress((folder / "candidate-index.json.gz").read_bytes()))
    assert payload["binding"]["background_sha256"] == digest((folder / "background.json.gz").read_bytes())
    native = {int(k): Function.model_validate(v) for k, v in payload["functions"].items()}
    fs = []
    for i, doc in enumerate(bg.documents):
        if i in native:
            f = native[i]
            assert digest(f.code.encode()) == doc.source_sha256
        else:
            path, _, qual = doc.id.partition("::")
            owner, _, name = qual.rpartition(".")
            f = Function(path=path, owner=owner or None, name=name or qual, line=0, end_line=0, code="")
        f.tokens = doc.tokens()
        assert f.qualname == doc.id
        fs.append(f)
    rows = [json.loads(line) for line in (folder / "queries.jsonl").read_text().splitlines()]
    selected = sorted(rows, key=lambda r: digest(("paired-runtime-v1/" + str(r["query"])).encode()))[:1000]
    gold = [json.loads(line) for line in (folder / "gold-directions.jsonl").read_text().splitlines()]
    return fs, selected, gold


def main():
    fs, selected, gold = load()
    gc.collect()
    out = OUT / "results"
    out.mkdir(exist_ok=True)
    label = f"{a.cohort}-{a.arm}-{a.label}"
    native = {id(f) for f in fs if f.line > 0}
    settings = Settings()
    queries = []
    for r in selected:
        f = fs[r["query"]]
        base = {fs[i].qualname for i, *_ in r["baseline"]}

        def allowed(other, f=f, base=base):
            return (
                id(other) in native
                and other.qualname != f.qualname
                and other.qualname not in base
                and not why_skipped(f, other, settings)
            )

        queries.append((f, allowed))
    prof = cProfile.Profile() if a.profile else None
    start_rss = rss()
    load_before = os.getloadavg()
    cpu = time.process_time()
    start = time.perf_counter()
    if prof:
        prof.enable()
    c = OperationBlocksComparer()
    c.index(fs)
    if prof:
        prof.disable()
        prof.dump_stats(str(out / (label + "-construction.prof")))
        with (out / (label + "-construction.txt")).open("w") as stream:
            pstats.Stats(prof, stream=stream).sort_stats("cumulative").print_stats(45)
    cold = time.perf_counter() - start
    cold_cpu = time.process_time() - cpu
    cold_rss = rss()
    positions = {id(f): i for i, f in enumerate(fs)}

    def query():
        return [
            [[positions[id(other)], score.hex()] for other, score in c.neighbours(f, 1, allowed)]
            for f, allowed in queries
        ]

    start = time.perf_counter()
    first = query()
    first_s = time.perf_counter() - start
    if prof:
        prof = cProfile.Profile()
        prof.enable()
    cpu = time.process_time()
    start = time.perf_counter()
    second = query()
    warm = time.perf_counter() - start
    warm_cpu = time.process_time() - cpu
    assert first == second
    if prof:
        prof.disable()
        prof.dump_stats(str(out / (label + "-query.prof")))
        with (out / (label + "-query.txt")).open("w") as stream:
            pstats.Stats(prof, stream=stream).sort_stats("cumulative").print_stats(45)
    result = dict(
        arm=a.arm,
        cohort=a.cohort,
        documents=len(fs),
        native=len(native),
        queries=len(queries),
        query_ids=[r["query"] for r in selected],
        outputs=second,
        output_sha256=digest(json.dumps(second).encode()),
        profiled=a.profile,
        cold_seconds=cold,
        cold_cpu_seconds=cold_cpu,
        first_query_seconds=first_s,
        warm_seconds=warm,
        warm_cpu_seconds=warm_cpu,
        input_rss_kib=start_rss,
        cold_rss_kib=cold_rss,
        query_rss_kib=rss(),
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        load_before=load_before,
        load_after=os.getloadavg(),
        python=sys.version,
        executable=sys.executable,
        platform=platform.platform(),
        affinity=sorted(os.sched_getaffinity(0)),
        source_module=sys.modules[OperationBlocksComparer.__module__].__file__,
    )
    (out / (label + ".json")).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ["outputs", "query_ids", "affinity"]}), flush=True)


if __name__ == "__main__":
    main()
