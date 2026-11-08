# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, F403, F405, I001
"""Deduplicate physical recordings independently of repeated per-arm logical charges."""

from policy import *
import argparse, importlib.util

ap = argparse.ArgumentParser()
ap.add_argument("--run", type=Path, required=True)
ap.add_argument("--snapshot", type=Path, required=True)
a = ap.parse_args()
out = a.run.resolve()
refs = json.loads(a.snapshot.read_text())["observations"]
bykey = {}
for ref in refs:
    assert sha(ref["path"]) == ref["sha256"]
    obs = json.loads(Path(ref["path"]).read_text())
    bykey.setdefault(obs["request_key"], (ref, obs))
spec = importlib.util.spec_from_file_location("wave", ROOT / ".lab-results/encoder-judging/wave_v3.py")
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
rows = []
for q in jl(out / "question-outcomes.jsonl"):
    cached = q["normal_recording"]
    if not cached:
        continue
    identity = cached["identity"]
    binding = {
        k: identity[k]
        for k in [
            "repository",
            "revision",
            "scope",
            "background_sha256",
            "candidate_sha256",
            "candidate_kind",
            "source_files",
        ]
    }
    c = Candidate.model_validate(q["candidate"])
    for kind in ["claude", "jev"]:
        req = w.request(c, kind, binding)
        found = bykey.get(req["request_key"])
        ref, obs = found if found else (None, None)
        if obs:
            assert obs["identity"] == req["identity"]
        rows.append(
            dict(
                id=q["id"],
                role=q["role"],
                kind=kind,
                request_key=req["request_key"],
                receipt=ref,
                recorded_usd=obs.get("usd") if obs else None,
                error=obs.get("error") if obs else "missing",
                conservative_physical_reservation_usd=req["reservation_usd"],
            )
        )
assert len({r["request_key"] for r in rows}) == len(rows)
write(out / "physical-receipt-rows.jsonl", rows)
write(
    out / "PHYSICAL-COSTS.json",
    dict(
        distinct_requests=len(rows),
        distinct_questions=len({r["id"] for r in rows}),
        recorded_requests=sum(r["receipt"] is not None for r in rows),
        distinct_recorded_usage_usd=sum(r["recorded_usd"] or 0 for r in rows),
        by_kind={
            kind: dict(
                requests=sum(r["kind"] == kind for r in rows),
                recorded_usage_usd=sum(r["recorded_usd"] or 0 for r in rows if r["kind"] == kind),
            )
            for kind in ["claude", "jev"]
        },
        note="Deduplicated recorded usage of exact core requests. Per-arm normal/native ledgers charge independently. Reexported retained controls reuse these same receipts and add no distinct request. Root owns execution-account attribution; worker provider spend0.",
        worker_provider_calls=0,
    ),
)
print((out / "PHYSICAL-COSTS.json").read_text())
