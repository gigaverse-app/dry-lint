# ruff: noqa: E402, E731
# Frozen experiment harness; imports follow runtime selection; predicates close over the current query.
"""Executable edits inside indented methods; reuse only parity-proven index state."""

import json
import time
from pathlib import Path

import parity
from dry_lint.operation_blocks import OperationBlocksComparer

from dry_lint.detector import why_skipped
from dry_lint.functions import _function_node, behaviour_tokens, function_calls
from dry_lint.settings import Settings

OUT = Path(__file__).resolve().parent


def edit(f):
    q = f.model_copy(deep=True)
    node = _function_node(q.code)
    assert node is not None and node.body
    lines = q.code.splitlines()
    indent = min((len(line) - len(line.lstrip()) for line in lines if line.strip()), default=0)
    q.code = (
        "\n".join(line[indent:] for line in lines) + "\n" + " " * node.body[0].col_offset + "audit_operation_packet()"
    )
    q.end_line += 1
    q.tokens = behaviour_tokens(q)
    q.calls = function_calls(q)
    assert "call:audit_operation_packet" in q.tokens
    assert "audit_operation_packet" in q.calls
    return q


def run(cid):
    start = time.perf_counter()
    fs, native = parity.load(cid)
    c = OperationBlocksComparer()
    c.index(fs)
    previous = json.loads((OUT / "results" / f"{cid}-parity.json").read_text())
    assert parity.representations(c)[0] == previous["all_representations_sha256"]
    # The entire index (including ordered vectors) was compared independently.
    # Share that proven read-only state; the frozen module still independently
    # parses, prepares, ranks and scores every standalone edited source below.
    b = parity.frozen.OperationBlocksComparer.__new__(parity.frozen.OperationBlocksComparer)
    b.__dict__ = dict(c.__dict__)
    b._full_vectors = {}
    qs = {r["source_query"]: r["bucket"] for r in previous["novel"] if r["kind"] == "edited"}
    records = {r["query"]: r for r in parity.lines(OUT / "inputs" / cid / "queries.jsonl") if r["query"] in qs}
    native_ids = {id(f) for f in native.values()}
    positions = {id(f): i for i, f in enumerate(fs)}
    settings = Settings()
    results = []
    for q, bucket in sorted(qs.items()):
        f = edit(fs[q])
        base = {fs[i].qualname for i, *_ in records[q]["baseline"]}
        allowed = lambda other, f=f, base=base: (
            id(other) in native_ids
            and other.qualname != f.qualname
            and other.qualname not in base
            and not why_skipped(f, other, settings)
        )
        left = b.neighbours(f, 64, allowed)
        right = c.neighbours(f, 64, allowed)
        a = [(positions[id(o)], s.hex()) for o, s in left]
        z = [(positions[id(o)], s.hex()) for o, s in right]
        assert a == z and all(x is y for (x, _), (y, _) in zip(left, right, strict=True))
        for target, _ in left:
            assert b.similarity(f, target).hex() == c.similarity(f, target).hex()
            assert b.shared(f, target) == c.shared(f, target)
        results.append(
            {
                "query": q,
                "qualname": f.qualname,
                "bucket": bucket,
                "new_source_sha256": parity.sha(f.code.encode()),
                "added_executable_call_verified": True,
                "before": a,
                "after": z,
                "native_names": [target.qualname for target, _ in left],
            }
        )
    result = {
        "cohort": cid,
        "protocol": "All candidate index representations/postings were independently matched to frozen baseline first; frozen/current query methods share that proven immutable index state and independently prepare/score edited sources. Every edit is asserted to add a call inside the function, including indented methods.",
        "queries": results,
        "elapsed_seconds": time.perf_counter() - start,
    }
    (OUT / "results" / f"{cid}-executable-edits.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "cohort": cid,
                "verified_executable_edits": len(results),
                "winners": sum(bool(r["after"]) for r in results),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    for cid in ["bg-7489aa1946c16153", "bg-ebd0031534c954e5", "bg-b989dc3a47d648a0"]:
        run(cid)
