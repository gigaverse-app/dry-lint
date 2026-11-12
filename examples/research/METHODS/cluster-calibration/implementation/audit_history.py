# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, E402, E731, E741, I001
"""Bind recorded seeds to existing settled native replay evidence; no label transfer."""

from _recovery_paths import recovery_path
import sys, json, pathlib, hashlib, collections

sys.dont_write_bytecode = True
H = pathlib.Path(__file__).resolve().parent
R = pathlib.Path(recovery_path(""))
sys.path.insert(0, str(R / "jobs/encoder-corpus-evaluation/.lab-results/runtime/src"))
from dry_lint.models import Candidate

sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    seeds = [json.loads(l) for l in (H / "recorded-seeds.jsonl").open()]
    byrequest = {s["seed_id"]: s for s in seeds}
    idx = collections.defaultdict(list)
    for s in seeds:
        idx[Candidate.model_validate(s["candidate"]).key, s["revision"], s["identity"]["source_evidence"]].append(s)
    base = R / "jobs/adaptive-judge-budget/.lab-results/historical-novelty-v3"
    direct = []
    native = []
    inputs = {}
    for p in sorted((base / "normal").glob("*/*/rows.jsonl")):
        if any(t in str(p).lower() for t in ["opencode", "firecrawl", "curator"]):
            continue
        inputs[str(p)] = sha(p)
        for line in p.open():
            r = json.loads(line)
            if r["key"] in byrequest:
                direct.append(
                    {
                        "seed_id": r["key"],
                        "path": str(p),
                        "ordinal": r["ordinal"],
                        "cached": r["cached"],
                        "pair": r["pair"],
                    }
                )
    p = base / "native-results.json"
    inputs[str(p)] = sha(p)
    for r in json.loads(p.read_text()):
        if any(t in r["history"].lower() for t in ["opencode", "firecrawl", "curator"]):
            continue
        for question, v in r["reported_questions"].items():
            for s in idx[v["pair"], v["head"], v["evidence"]]:
                native.append(
                    {
                        "seed_id": s["seed_id"],
                        "history": r["history"],
                        "arm": r["arm"],
                        "ordering_arm": r["ordering_arm"],
                        "native_question": question,
                        "source_evidence": v["evidence"],
                        "revision": v["head"],
                        "pair": v["pair"],
                        "provider_positive": s["reported_by_recorded_threshold"],
                    }
                )
    for name, obj in [
        ("HISTORICAL-SEED-LINKS.json", {"direct_request_key_links": direct, "inputs": inputs}),
        ("NATIVE-SEED-LINKS.json", {"matches": native, "inputs": inputs}),
    ]:
        obj["interpretation"] = (
            "Only exact request or pair/head/source-evidence links count. No match establishes an ingestion coverage limit, not absence of prior reported seeds in all historical data."
        )
        (H / name).write_text(json.dumps(obj, indent=2) + "\n")
    print("direct", len(direct), "native", len(native))


if __name__ == "__main__":
    main()
