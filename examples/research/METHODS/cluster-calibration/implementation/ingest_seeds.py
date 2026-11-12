# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, E402, E741, F841, I001
"""Audit existing paid recordings offline. Never instantiate providers or read keys."""

from _recovery_paths import recovery_path
import os, sys

for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[k] = "2"
sys.dont_write_bytecode = True
import pathlib, json, hashlib, collections

H = pathlib.Path(__file__).resolve().parent
R = pathlib.Path(recovery_path(""))
sys.path.insert(0, str(R / "jobs/encoder-corpus-evaluation/.lab-results/runtime/src"))
from dry_lint.models import Candidate, evidence
from dry_lint.judges.command import prompt


def sha(p):
    with open(p, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def digest(s):
    return hashlib.sha256(s.encode()).hexdigest()


def canonical(v):
    return digest(json.dumps(v, sort_keys=True, ensure_ascii=True))


def jl(p):
    with open(p) as f:
        for l in f:
            if l.strip():
                yield json.loads(l)


def bad(repo):
    return any(t in repo.lower() for t in ["opencode", "firecrawl", "curator"])


def main():
    contract = json.loads((H / "EXPERIMENT-CONTRACT.json").read_text())
    panels = {p["source"]["background_sha256"]: p for p in contract["inputs"]}
    cache = {}
    packets = {}
    records = []
    counts = collections.Counter()
    skip = []
    frozen = H / "OBSERVATION-INPUTS.json"
    if not frozen.exists():
        paths = [
            p
            for folder in ("encoder-judging", "combined-judging", "enablement-judging")
            for p in sorted((R / ".lab-results" / folder / "physical-account/observations").glob("*.json"))
        ]
        frozen.write_text(json.dumps([{"path": str(p), "sha256": sha(p)} for p in paths], indent=2) + "\n")
    for ref in json.loads(frozen.read_text()):
        path = pathlib.Path(ref["path"])
        assert sha(path) == ref["sha256"]
        if True:
            obs = json.loads(path.read_text())
            i = obs.get("identity", {})
            # Outcome, request, source body and packet are not inspected for excluded repositories.
            if bad(i.get("repository", "")):
                counts["reserved_skipped_before_outcome_access"] += 1
                continue
            p = panels.get(i.get("background_sha256"))
            if (
                p is None
                or i.get("repository") != p["repository"]
                or i.get("revision") != p["revision"]
                or i.get("scope") != p["source"]["scope"]
            ):
                counts["no_exact_allowed_cohort_scope"] += 1
                continue
            assert canonical(i) == obs["request_key"]
            cid = p["cohort_id"]
            if cid not in cache:
                fp = p["source"]["functions_path"]
                assert sha(fp) == p["source"]["functions_sha256"]
                fs = list(jl(fp))
                by = {}
                for pos, f in enumerate(fs):
                    ident = f["path"] + "::" + ((f.get("owner") + ".") if f.get("owner") else "") + f["name"]
                    by.setdefault((ident, digest(f["code"])), []).append(pos)
                cache[cid] = (fs, by)
            fs, by = cache[cid]
            src = i.get("source_files", [])
            positions = [by.get((s["source_id"], s["body_sha256"]), []) for s in src]
            if len(positions) != 2 or any(len(x) != 1 for x in positions):
                counts["endpoint_mismatch_or_ambiguous"] += 1
                continue
            packet = pathlib.Path(obs["packet_file"])
            if not packet.exists() or sha(packet) != obs["packet_file_sha256"]:
                counts["missing_or_changed_packet"] += 1
                continue
            if str(packet) not in packets:
                if packet.suffix == ".jsonl":
                    entries = list(jl(packet))
                else:
                    data = json.loads(packet.read_text())
                    entries = data if isinstance(data, list) else [data]
                packets[str(packet)] = [e for e in entries if not bad(e.get("repository", ""))]
            candidates = []
            for row in packets[str(packet)]:
                raw = row.get("candidate")
                if not raw:
                    continue
                candidate = Candidate.model_validate(raw)
                if evidence(candidate) != i.get("source_evidence") or candidate.context_hash != i.get("context_hash"):
                    continue
                if i.get("candidate_sha256") and canonical(candidate.model_dump(mode="json")) != i["candidate_sha256"]:
                    continue
                if {digest(candidate.new.code), digest(candidate.existing.code)} != {s["body_sha256"] for s in src}:
                    continue
                candidates.append(candidate)
            if not candidates:
                counts["packet_candidate_binding_failed"] += 1
                continue
            candidate = candidates[0]
            regenerated = False
            if i.get("kind") == "claude":
                regenerated = prompt(
                    candidate, policy=i.get("request_options", {}).get("prompt_policy", "shared-operations")
                ) == i.get("rendered_input")
            if not regenerated:
                counts["rendered_prompt_not_regenerated"] += 1
                continue
            v = obs.get("verdict")
            valid = bool(v and not obs.get("error") and obs.get("usage"))
            threshold = i["settings"]["report_at"]
            positive = bool(
                valid and v["label"] != "separate" and v["score"] >= threshold and not v.get("model_assessment")
            )
            record = {
                "schema": 1,
                "seed_id": obs["request_key"],
                "cohort_id": cid,
                "repository": p["repository"],
                "revision": p["revision"],
                "positions": [z[0] for z in positions],
                "identity": i,
                "recording_path": str(path),
                "recording_sha256": sha(path),
                "packet_path": str(packet),
                "packet_sha256": obs["packet_file_sha256"],
                "candidate": candidate.model_dump(mode="json"),
                "verdict": v,
                "reported_by_recorded_threshold": positive,
                "valid_recorded_answer": valid,
                "usage": obs.get("usage"),
                "usd": obs.get("usd"),
                "rendered_prompt_regenerated": regenerated,
                "temporal_status": "recorded answer existed before current experiment; actual native chronological seed availability not yet established",
                "seed_authority": "recorded-provider-positive" if positive else "recorded-provider-negative-or-unknown",
                "source_positive_authority": "not inferred from provider score",
            }
            records.append(record)
            counts["exact_request_bound_records"] += 1
            counts["provider_positive" if positive else "provider_other"] += 1
    with (H / "recorded-seeds.jsonl").open("w") as f:
        for r in records:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    (H / "SEED-INGESTION.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "counts": dict(counts),
                "actual_native_chronological_seed_count": None,
                "actual_native_chronological_seed_status": "Not authenticated by request recording alone. These are real recorded provider answers, not newly executed or independent source truth.",
                "supported_prompt": "Pinned command shared-operations renderer; other judge protocols excluded pending equivalent verification.",
                "script_sha256": sha(__file__),
            },
            indent=2,
        )
        + "\n"
    )
    print(dict(counts))


if __name__ == "__main__":
    main()
