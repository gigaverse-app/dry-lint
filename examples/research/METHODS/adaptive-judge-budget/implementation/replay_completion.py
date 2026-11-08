# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: F403, F405, I001
"""Replay the frozen outcome-blind completion core from exact recordings only."""

from replay_captures import *
import argparse

ap = argparse.ArgumentParser()
ap.add_argument("--out", type=Path, required=True)
ap.add_argument("--snapshot", type=Path, required=True)
ap.add_argument(
    "--screen",
    action="store_true",
    help="Replay all frozen original captures directly, without regenerating candidate banks or proposing a new frontier",
)
a = ap.parse_args()
out = a.out.resolve()
out.mkdir(exist_ok=False, parents=True)
start = time.perf_counter()
cpu = time.process_time()
core = json.loads((HERE / "returned-wave-v1/COMPLETION-CORE.json").read_text())
old = HERE / "matched-captures"
inputs = json.loads((old / "INPUTS.json").read_text())
snapshot = json.loads(a.snapshot.read_text())["observations"]
for r in snapshot:
    assert sha(r["path"]) == r["sha256"]
cache = recordings([Path(r["path"]) for r in snapshot], include_default=False)
original = {(r["cohort_id"], r["query"]): r for r in jl(old / "results.jsonl")}
results = []
packets = []
campaigns = [dict(cohort_id=cid, query=q) for cid, q in original] if a.screen else core["campaigns"]
for anchor in campaigns:
    cid, q = anchor["cohort_id"], anchor["query"]
    p = inputs["banks"][cid]["source"]
    payload = json.loads((old / cid / str(q) / "candidates.json").read_text())
    write(out / cid / str(q) / "candidates.json", payload)
    record = dict(cohort_id=cid, query=q, arms={})
    current = [Candidate.model_validate(x) for x in payload["current"]]
    pool = current + [Candidate.model_validate(x) for x in payload["extra"]]
    proofs = {(r["id"], r["source_sha256"]): r for r in jl(p["source_proof_path"])}
    for arm in core["arms"]:
        before = original[cid, q]["arms"][arm]["native"]
        s = Settings.model_validate(before["settings"])
        run = Run.model_validate(before["run"])
        cs = current if arm == "fixed" else pool
        sig = payload["signals"]
        if arm == "cost":
            sig = {k: v | {"family_proxy": k} for k, v in sig.items()}
        actual = "adaptive" if arm == "cost" else arm
        folder = out / cid / str(q) / arm
        nr = normal(cs, sig, s, run, folder, actual, p, cache)
        native = native_replay(cs, sig, s, run, folder, actual, p, cache)
        record["arms"][arm] = dict(normal=nr, native=native)
        key = native["censored"]
        if a.screen or not key or key.startswith("known_paid_failure:"):
            continue
        c = next(c for c in cs if c.key == key)
        ev = next(e for e in native["events"] if e["key"] == key and e["admitted"])
        packets.append(
            dict(
                id="AB-" + canonical(c.model_dump(mode="json"))[:20],
                cohort_id=cid,
                query=q,
                arm=arm,
                repository=p["repository"],
                revision=p["revision"],
                candidate=c.model_dump(mode="json"),
                source_proofs=[proofs[f.qualname, digest(f.code)] for f in [c.new, c.existing]],
                background_proof={"path": p["background_path"], "sha256": p["background_sha256"]},
                settings=s.model_dump(mode="json"),
                run=run.model_dump(mode="json"),
                rendered_prompt=JUDGE.input_text(c),
                prompt_sha256=digest(JUDGE.input_text(c)),
                funding=dict(
                    event=ev,
                    actually_reserved=True,
                    database=native["database"],
                    database_sha256=sha(native["database"]),
                ),
                novel_vs_current=c.key not in {c.key for c in current},
                normal_estimated_funded=any(e["key"] == key and e["admitted"] for e in nr["events"]),
                transport_role="control" if arm == "fixed" else "candidate",
                anchor_role=anchor["role"],
            )
        )
    results.append(record)
    if len(results) % 50 == 0:
        print(len(results), "campaigns", round(time.perf_counter() - start, 2), "seconds", flush=True)
# Dedup actual identical first-missing requests, prefer fixed role for shared controls.
selected = {}
for r in sorted(packets, key=lambda r: ({"fixed": 0, "adaptive": 1, "cost": 2, "uniform": 3}[r["arm"]], r["id"])):
    selected.setdefault(r["id"], r)
write(out / "frontier-all-arms.jsonl", packets)
write(out / "frontier.jsonl", list(selected.values()))
write(out / "results.jsonl", results)
write(out / "INPUTS.json", inputs)
keys = {(r["cohort_id"], r["query"]) for r in results}
write(out / "deltas.jsonl", [r for r in jl(old / "deltas.jsonl") if (r["cohort_id"], r["query"]) in keys])
write(
    out / "SUMMARY.json",
    dict(
        campaigns=len(results),
        arms=4 * len(results),
        frontier_questions=len(selected),
        completed_native_arms=sum(not x["native"]["censored"] for r in results for x in r["arms"].values()),
        wall_seconds=time.perf_counter() - start,
        cpu_seconds=time.process_time() - cpu,
        provider_calls=0,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        core_manifest_sha256=None if a.screen else sha(HERE / "returned-wave-v1/COMPLETION-CORE.json"),
        snapshot_sha256=sha(a.snapshot),
        scope="Frozen550 capture screen" if a.screen else "Frozen4 completion core",
    ),
)
print((out / "SUMMARY.json").read_text())
