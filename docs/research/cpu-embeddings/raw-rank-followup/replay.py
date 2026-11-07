# ruff: noqa: E401, E402, E741, F401, F403, F405, I001, B007
# Frozen experiment adapters intentionally preserve import order and shared wildcard exports.
#!/usr/bin/env python3
"""Provider-free public-pin experiment replay against an external frozen data directory."""

import argparse, os, sys, zipfile, tempfile, json, hashlib, gzip, time
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--data-dir", type=Path, required=True)
p.add_argument("--output-dir", type=Path, required=True)
p.add_argument(
    "--retrieval",
    action="store_true",
    help="Also recompute all selected pools from full backgrounds and frozen vectors; slower",
)
a = p.parse_args()
D = a.data_dir.resolve()
O = a.output_dir.resolve()
O.mkdir(parents=True, exist_ok=True)
os.environ["RECALL_REPLAY_DATA"] = str(D)
sys.dont_write_bytecode = True
# Fail rather than overwrite a previous run's native ledgers.
assert not (O / "native").exists(), "Use a fresh output directory"
with zipfile.ZipFile(D / "runtime.zip") as z:
    z.extractall(O / "runtime")
sys.path.insert(0, str(O / "runtime/src"))
from common import *
import hybrid
from hybrid import Hybrid, normal, settings, JUDGE
from dry_lint.models import Candidate, Run
from dry_lint.discovery import CampaignStore, reservation_cost
from dry_lint.judges.command import prompt
from collections import Counter, defaultdict

start = time.monotonic()
counts = Counter()
manifest = json.loads((D / "MANIFEST.json").read_text())
for name, proof in manifest["files"].items():
    with (D / name).open("rb") as f:
        assert hashlib.file_digest(f, "sha256").hexdigest() == proof["sha256"], name
    counts["hashed_files"] += 1
campaigns = read(D / "campaigns.jsonl.gz")
cases = read(D / "cases.jsonl.gz")
observations = read(D / "observations.jsonl.gz")
requests = read(D / "requests.jsonl.gz")
from recordings import reparse_observations

counts.update(reparse_observations(observations))
for seal in json.loads((D / "source-seals/receipts.json").read_text()):
    assert sha((D / seal["decisions_file"]).read_bytes()) == seal["decisions_sha256"]
    counts["source_decision_seals"] += 1
# Replay unmodified native order and reserve, and the separate normal ledger.
for r in campaigns:
    s = settings()
    s.include = r["scope"]["include"]
    s.exclude = r["scope"]["exclude"]
    for arm, raw in r["arms"].items():
        cs = [Candidate.model_validate(c) for c in raw]
        assert normal(cs, s) == r["normal"][arm], (r["id"], arm, "normal")
        out = O / "native" / r["id"] / arm
        out.mkdir(parents=True, exist_ok=True)
        n = r["native"][arm]
        store = CampaignStore(out / "campaign.sqlite", Run.model_validate(n["run"]))
        store.advance(s)
        ordered = store.order([c for c in cs if not c.filtered and min(c.new.line, c.existing.line) >= 1])
        assert len(ordered) == len(n["events"])
        for c, e in zip(ordered, n["events"], strict=True):
            hold = reservation_cost(JUDGE, c, s)
            result = store.reserve(c, JUDGE, s, hold)
            assert c.key == e["key"] and result == e["reserve_result"], (r["id"], arm, c.key)
            assert abs(hold - e["considered_reservation_usd"]) < 1e-12
            assert sha(canonical(c.model_dump(mode="json"))) == e["candidate_sha256"]
            counts["reservation_events"] += 1
        assert store.snapshot().model_dump(mode="json") == n["state"], (r["id"], arm, "state")
        counts["arm_ledgers"] += 1
# Verify complete source files and exact body proofs, independent of provider labels.
from dry_lint.extractors import PythonExtractor
from dry_lint.typescript import TypeScriptExtractor

extractors = {"python": PythonExtractor(), "typescript": TypeScriptExtractor()}
extracted = {}
for r in cases:
    c = Candidate.model_validate(r["candidate"])
    for f, proof in zip((c.new, c.existing), r["source_proofs"], strict=True):
        raw = (D / "sources" / r["repository"].replace("/", "__") / r["revision"] / proof["path"]).read_bytes()
        assert sha(raw) == proof["file_sha256"] and sha(f.code.encode()) == proof["body_sha256"]
        key = (r["repository"], r["revision"], f.path)
        if key not in extracted:
            ex = extractors["python" if f.path.endswith(".py") else "typescript"]
            ex.validate_source(f.path, raw.decode())
            extracted[key] = ex.functions(f.path, raw.decode())
        found = [
            g for g in extracted[key] if g.qualname == f.qualname and g.line == f.line and g.end_line == f.end_line
        ]
        assert len(found) == 1 and found[0].code == f.code, (r["id"], f.qualname, "canonical extraction")
    counts["source_bound_candidate_versions"] += 1


# Exact source + rendered question + model + settings reuse, only Candidate SHA excluded.
def identity(i):
    return {k: v for k, v in i.items() if k != "candidate_sha256"}


obs_by = {o["request_key"]: o for o in observations}
req_by = {r["request_key"]: r for r in requests}
for m in read(D / "successor-root-reuse.jsonl"):
    old = obs_by[m["observation_request_key"]]
    new = req_by[m["request_key"]]
    assert identity(old["identity"]) == identity(new["identity"]), m["id"]
    assert m["not_a_new_provider_observation"] and m["physical_new_usd"] == 0
    counts["verified_successor_question_reuses"] += 1
assert counts["verified_successor_question_reuses"] == 64
# Regenerate Haiku rendered prompts from canonical fullCandidate. Jev keeps its original bounded input.
for r in cases:
    c = Candidate.model_validate(r["candidate"])
    rendered = prompt(c, policy="shared-operations")
    matches = [
        q
        for q in requests
        if q["identity"]["kind"] == "claude"
        and q["identity"]["repository"] == r["repository"]
        and q["identity"]["rendered_input"] == rendered
    ]
    assert matches, (r["id"], "exact rendered prompt")
    assert c.new.code in rendered and c.existing.code in rendered
    counts["fullsource_prompt_matches"] += 1
# Recompute source/report joins from actual recordings; exact-equivalent questions may differ in Candidate identity.
truth = {r["blind_id"]: r for r in read(D / "source-decisions.jsonl")}
by_question = defaultdict(list)
for o in observations:
    by_question[canonical(identity(o["identity"]))].append(o)
joined = []
summary = []
for r in cases:
    b = r["batch"]
    vm = {x["variant"]: x for x in read(D / "equivalence" / b / "variant-map.jsonl")}
    q = req_by[vm[r["id"]]["request_keys"]["claude"]]
    matches = by_question[canonical(identity(q["identity"]))]
    assert matches, (b, r["id"])
    values = {(o["verdict"]["label"], o["verdict"]["score"]) for o in matches}
    assert len(values) == 1
    label, score = next(iter(values))
    t = truth[r["source_join"]["blind_id"]]
    joined.append(
        dict(
            batch=b,
            id=r["id"],
            pair=pair_id(r["repository"], r["candidate"]),
            reported=label in ("duplicate", "drifted") and score >= 0.5,
            source_decision=t["decision"],
            operation_family=t["repository"] + ":" + t["operation_family"]["description"],
            occurrences=r["source_join"]["occurrences"],
        )
    )
for b in sorted({r["batch"] for r in cases}):
    ds = read(D / "equivalence" / b / "actual-deltas.jsonl")
    local = [r for r in joined if r["batch"] == b]
    for arm in sorted({d["arm"] for d in ds}):
        gains = {}
        losses = {}
        for delta in [d for d in ds if d["arm"] == arm]:
            scopes = defaultdict(dict)
            for r in local:
                for oc in r["occurrences"]:
                    if oc["campaign"] == delta["campaign"] and oc["arm"] in ("current109", arm):
                        scopes[oc["arm"]][r["pair"]] = r
            old = scopes["current109"]
            new = scopes[arm]
            gains.update({k: new[k] for k in new.keys() - old.keys()})
            losses.update({k: old[k] for k in old.keys() - new.keys()})
        row = dict(batch=b, arm=arm)
        for k, rs in [("gained", gains), ("lost", losses)]:
            row[k] = dict(
                canonical_pairs=len(rs),
                reported_by_source=dict(Counter(r["source_decision"] for r in rs.values() if r["reported"])),
            )
        expected = next(
            x
            for x in json.loads((D / "MATCHED-SUMMARY.json").read_text())["summaries"]
            if x["batch"] == b and x["arm"] == arm
        )
        for k in ("gained", "lost"):
            assert (
                row[k]["canonical_pairs"] == expected[k]["canonical_pairs"]
                and row[k]["reported_by_source"] == expected[k]["reported_by_source"]
            ), row
        summary.append(row)
dump(O / "matched-results.json", summary)
if a.retrieval:
    from retrieval import replay_retrieval

    counts.update(replay_retrieval(campaigns, D, O))
result = dict(
    passed=True,
    counts=dict(counts),
    seconds=time.monotonic() - start,
    provider_calls=0,
    retrieval_recomputed=a.retrieval,
    scope="Selected public-pin cold held campaigns; private30 matrices and fresh model encoding unavailable here",
)
dump(O / "REPLAY-RESULT.json", result)
print(json.dumps(result, indent=2))
