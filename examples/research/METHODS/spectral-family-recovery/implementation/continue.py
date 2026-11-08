# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, E741, I001
"""Consume a deterministic prefix of producer caches; never construct or wait for graphs."""

from _recovery_paths import recovery_path
import argparse, pathlib, json, hashlib, shutil, subprocess, sys

sys.dont_write_bytecode = True
H = pathlib.Path(__file__).resolve().parent
G = pathlib.Path(recovery_path("jobs/confirmed-cluster-expansion/.lab-results"))
SCI = recovery_path("reports/encoder-comparison/runtime/gemma/bin/python")


def sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


ap = argparse.ArgumentParser()
ap.add_argument("--max-cohorts", type=int, default=12)
ap.add_argument("--execute", action="store_true")
args = ap.parse_args()
plan = json.loads((H / "CONTINUATION.json").read_text())
allrows = [r for r in plan["cohorts"] if r["bank_available"]]
assert len(allrows) == 56
wanted = allrows[: args.max_cohorts]
ready = [r for r in wanted if (G / "graphs" / r["cohort_id"] / "RECEIPT.json").exists()]
D = H / "continuation"
D.mkdir(exist_ok=True)
receipt = {
    "schema": 1,
    "requested_prefix": args.max_cohorts,
    "graph_owner": "confirmed-cluster-expansion",
    "graph_construction": False,
    "ready": [r["cohort_id"] for r in ready],
    "missing": [r["cohort_id"] for r in wanted if r not in ready],
    "canonical_order": [r["cohort_id"] for r in allrows],
    "corrected_scenarios": str(H / "SEED-AVAILABILITY.json"),
    "interpretation": "Producer common-seed replay; corrected calibration scenarios remain a distinct seed-selection contract. Never pool orientations or revise corpus order from outcomes.",
}
(D / "AVAILABILITY.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps({k: v for k, v in receipt.items() if k not in ["canonical_order"]}))
if args.execute and ready:
    I = D / "inputs"
    I.mkdir(exist_ok=True)
    cids = {r["cohort_id"] for r in ready}
    for name in [
        "seed-exposures.jsonl",
        "proposals.jsonl",
        "outcomes.jsonl",
        "metrics.jsonl",
        "CONTROL-INVENTORY.jsonl",
    ]:
        source = G / name
        before = sha(source)
        rows = [json.loads(l) for l in source.read_text().splitlines()]
        assert before == sha(source), "producer is updating; rerun later"
        if name == "outcomes.jsonl":
            seeds = {r["seed_id"] for r in map(json.loads, (I / "seed-exposures.jsonl").read_text().splitlines())}
            rows = [r for r in rows if r["seed_id"] in seeds]
        else:
            rows = [r for r in rows if r.get("cohort_id") in cids]
        (I / name).write_text("".join(json.dumps(r) + "\n" for r in rows))
    for cid in cids:
        target = I / "graphs" / cid
        target.mkdir(parents=True, exist_ok=True)
        for name in ["RECEIPT.json", "nodes.jsonl", "adjacency.jsonl"]:
            shutil.copyfile(G / "graphs" / cid / name, target / name)
    for name in ["SPECTRAL-CONTRACT.json", "CONTINUATION.json"]:
        shutil.copyfile(H / name, D / name)
    subprocess.run([SCI, str(H / "spectral.py"), "--graph-root", str(I), "--output-dir", str(D)], check=True)
