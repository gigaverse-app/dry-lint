"""Provider-free replay of frozen native admission, exact recordings and source join.

Python 3.11+, pydantic 2 and httpx. No SDK clients, credential lookup or provider calls.
The bundled canonical runtime is the one used for the study, not the installed package.
"""

# ruff: noqa: E402
# Runtime import must follow the bundled archive path, never the checkout.
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

sys.dont_write_bytecode = True
HOME = Path(__file__).resolve().parent
sys.path.insert(0, str(HOME / "runtime.zip"))
from dry_lint.costs import PRICES, estimate, usage_cost
from dry_lint.discovery import CampaignStore, reservation_cost
from dry_lint.judges.command import PROMPT_POLICIES, parse_verdict, prompt
from dry_lint.judges.jev import JevJudge
from dry_lint.models import Candidate, Run, evidence
from dry_lint.models import Verdict as Verdict
from dry_lint.report import Finding, Report
from dry_lint.settings import Settings


def canonical(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()


def sha(b):
    return hashlib.sha256(b).hexdigest()


def load():
    return json.loads(gzip.decompress((HOME / "recordings.json.gz").read_bytes()))


def descriptor():
    return SimpleNamespace(
        name="anthropic-operations",
        model="claude-haiku-5-5",
        version=PROMPT_POLICIES["shared-operations"][0] + ":claude-haiku-5-5:output=2048",
        prompt_policy="shared-operations",
        max_tokens=2048,
    )


def pair(packet):
    c = Candidate.model_validate(packet["candidate"])
    return sha(canonical([packet["repository"], packet["revision"], sorted([c.new.qualname, c.existing.qualname])]))


def reported(candidate, verdict, settings):
    return Report.build([Finding(candidate=candidate, verdict=verdict)], settings).findings[0].reported


def verify_review(entry, review):
    p = entry["packet"]
    assert review["packet_id"] == entry["blind_id"]
    assert (p["repository"], p["revision"]) == (review["repository"], review["revision"])
    assert review["accepted_gold"] is False
    c = Candidate.model_validate(p["candidate"])
    endpoints = {x["source_id"]: x for x in review["endpoints"]}
    proofs = {x["source_id"]: x for x in entry["binding"]["source_files"]}
    for f in (c.new, c.existing):
        e, proof = endpoints[f.qualname], proofs[f.qualname]
        assert e["exact_body"] == f.code and e["body_sha256"] == sha(f.code.encode()) == proof["body_sha256"]
        assert e["file_sha256"] == proof["file_sha256"]
        assert (e["path"], e["line"], e["end_line"]) == (f.path, f.line, f.end_line)


def verify_request(request, entry, obs):
    ident = request["identity"]
    assert sha(canonical(ident)) == request["request_key"] == obs["request_key"]
    assert obs["identity"] == ident and obs["error"] is None and obs["verdict"] is not None
    c = Candidate.model_validate(entry["packet"]["candidate"])
    assert ident["candidate_sha256"] == sha(canonical(c.model_dump(mode="json")))
    assert ident["context_hash"] == c.context_hash and ident["source_evidence"] == evidence(c)
    assert all(ident[k] == value for k, value in entry["binding"].items())
    raw = obs["raw_responses"]
    assert len(raw) == 1 and raw[0]["http_status"] == 200
    response = raw[0]["json"]
    assert response["model"] == ident["model"]
    assert response["usage"] == obs["usage"]
    settings = Settings(**ident["settings"])
    if ident["kind"] == "claude":
        d = descriptor()
        assert ident["model"] == d.model and ident["version"] == d.version
        assert ident["max_output_tokens"] == 2048
        assert ident["settings"] == dict(report_at=0.5, drop_below=0.5, drift_at=0.8)
        assert ident["request_options"] == dict(
            prompt_policy="shared-operations",
            effort=None,
            max_retries=0,
            retry_malformed=False,
            server_side_fallbacks="disabled",
        )
        assert ident["execution_profile"] == "balanced-shadow-haiku55-v1"
        assert ident["rendered_input"] == prompt(c, policy="shared-operations")
        text = "\n".join(x["text"] for x in response["content"] if x["type"] == "text")
        verdict = parse_verdict(text, ident["judge"], ident["version"])
        rates = PRICES[d.model]
    else:
        judge = JevJudge(api_key="offline", model="jev-1.14.0", context=True, workers=1)
        assert ident["rendered_input"] == judge.input_text(c)
        assert ident["version"] == judge.version
        verdict = judge.verdict(response["answers"], settings)
        rates = PRICES["jev"]
    assert verdict.model_dump(mode="json") == obs["verdict"]
    usage = obs["usage"]
    actual = usage_cost(
        dict(
            input=usage["input_tokens"],
            output=usage["output_tokens"],
            cache_creation_input_tokens=usage.get("cache_creation_input_tokens", 0),
            cache_read_input_tokens=usage.get("cache_read_input_tokens", 0),
        ),
        rates,
    )
    assert abs(actual - obs["usd"]) < 1e-12
    assert actual <= request["reservation_usd"]
    return verdict


def replay_native(data, directory):
    settings = Settings.model_validate(data["settings"])
    d = descriptor()
    assert settings.prices == {} and settings.escalate.use == "none"
    assert settings.budget.usd == 0.04 and settings.judge.model_dump()["max_tokens"] == 2048
    pools = defaultdict(list)
    for p in data["pools"]:
        pools[p["campaign"], p["arm"]].append(p)
    with zipfile.ZipFile(HOME / "native-snapshots.zip") as z:
        for n, recorded in enumerate(data["native"]):
            pool = pools[recorded["campaign"], recorded["arm"]]
            dbbytes = z.read(Path(recorded["database"]["path"]).name)
            assert sha(dbbytes) == recorded["database"]["sha256"]
            frozen = directory / f"proof-{n}.sqlite"
            frozen.write_bytes(dbbytes)
            with sqlite3.connect(frozen.as_uri() + "?mode=ro&immutable=1", uri=True) as db:
                states = db.execute("SELECT state FROM campaigns").fetchall()
                assert len(states) == 1 and json.loads(states[0][0]) == recorded["state"]
            store = CampaignStore(directory / f"replay-{n}.sqlite", Run.model_validate(recorded["run"]))
            store.advance(settings)
            candidates = [Candidate.model_validate(p["candidate"]) for p in pool]
            ordered = store.order(candidates)
            assert len(ordered) == len(recorded["events"])
            normal_total = 0.0
            for p, c in zip(pool, candidates, strict=True):
                charge = estimate(d, [c], settings)
                admitted = normal_total + charge <= 0.04 + 1e-12
                if admitted:
                    normal_total += charge
                assert admitted == p["admitted"]
                assert abs(charge - p["normal_charge_usd"]) < 1e-12
                assert abs(normal_total - p["cumulative_usd"]) < 1e-12
            for c, e in zip(ordered, recorded["events"], strict=True):
                assert sha(canonical(c.model_dump(mode="json"))) == e["candidate_sha256"]
                hold = reservation_cost(d, c, settings)
                result = store.reserve(c, d, settings, hold)
                assert (type(result) is int) == e["admitted"]
                assert (result if type(result) is int else None) == e["attempt_index"]
                assert abs(hold - e["considered_reservation_usd"]) < 1e-12
            assert store.snapshot().model_dump(mode="json") == recorded["state"]


def calculate(data):
    entries = {e["id"]: e for e in data["entries"]}
    reviews = {r["packet_id"]: r for r in data["reviews"]}
    settings = Settings.model_validate(data["settings"])
    answers = defaultdict(dict)
    for req in data["requests"]:
        e = entries[req["case_id"]]
        answers[e["id"]][req["identity"]["kind"]] = verify_request(req, e, data["observations"][req["request_key"]])
    cases, truncation = {}, []
    for id, e in entries.items():
        review = reviews[e["blind_id"]]
        verify_review(e, review)
        c = Candidate.model_validate(e["packet"]["candidate"])
        h = answers[id]["claude"]
        row = dict(
            id=id,
            source_pair=pair(e["packet"]),
            role=e["packet"]["role"],
            haiku_label=h.label,
            haiku_score=h.score,
            reported=reported(c, h, settings),
            source_label=review["label"],
            source_utility=review["utility"],
            accepted_gold=False,
            source_reason=review["reason"],
            boundary=review["proposed_extraction_or_counterexample"],
        )
        cases[row["source_pair"]] = row
        req = next(r for r in data["requests"] if r["case_id"] == id and r["identity"]["kind"] == "jev")
        state = json.loads(req["identity"]["rendered_input"])["state"]
        for name, f in [("new_function", c.new), ("existing_function", c.existing)]:
            actual = state[name]["code"]
            if state[name]["code_truncated"]:
                truncation.append(
                    dict(
                        id=id,
                        side=name,
                        path=f.path,
                        line=f.line,
                        full_chars=len(f.code),
                        rendered_chars=len(actual),
                        full_sha256=sha(f.code.encode()),
                        rendered_sha256=sha(actual.encode()),
                        omitted_suffix_sha256=sha(f.code[len(actual) :].encode()),
                        source_label=review["label"],
                        source_utility=review["utility"],
                        haiku_reported=row["reported"],
                        jev_score=answers[id]["jev"].score,
                        canonical_answer_scope="partial_function_with_file_prefix_context",
                    )
                )
    arms = defaultdict(dict)
    for n in data["native"]:
        arms[n["campaign"]][n["arm"]] = {e["source_pair"]: e for e in n["events"] if e["admitted"]}
    by_admission = {p["id"]: p for p in data["pools"]}
    delta, retained = [], 0
    for campaign, a in arms.items():
        old, new = a["original"], a["treatment"]
        for p in old.keys() & new.keys():
            c1 = Candidate.model_validate(by_admission[old[p]["admission_id"]]["candidate"])
            c2 = Candidate.model_validate(by_admission[new[p]["admission_id"]]["candidate"])
            # Ranking/comparer can change; exact source and the deployed question must not.
            assert c1.new == c2.new and c1.existing == c2.existing
            assert prompt(c1, policy="shared-operations") == prompt(c2, policy="shared-operations")
            assert c1.lane == c2.lane
            retained += 1
        for sign, pairs in [("gain", new.keys() - old.keys()), ("loss", old.keys() - new.keys())]:
            for p in sorted(pairs):
                delta.append(
                    dict(
                        cases[p],
                        change=sign,
                        campaign=campaign,
                        admission_id=(new if sign == "gain" else old)[p]["admission_id"],
                    )
                )
    counts = {}
    for sign in ["gain", "loss"]:
        selected = [d for d in delta if d["change"] == sign]
        reports = [d for d in selected if d["reported"]]
        counts[sign] = dict(
            native=len(selected),
            reported=len(reports),
            bounded=sum(
                d["source_label"] == "useful-extractable" and d["source_utility"] == "bounded" for d in reports
            ),
            tiny=sum(d["source_label"] == "useful-extractable" and d["source_utility"] == "tiny" for d in reports),
            nonuseful=sum(d["source_label"] != "useful-extractable" for d in reports),
            source_unknown=sum(d["source_label"] == "unknown" for d in selected),
        )
    counts["net"] = {k: counts["gain"][k] - counts["loss"][k] for k in counts["gain"]}
    paid = {o["request_key"]: o for f in data["feedback"] for o in f["observations"] if o["newly_paid_here"]}
    assert len(cases) == 72 and len(delta) == 66 and retained == 139
    totals = {
        arm: sum(n["native_admitted"] for n in data["native"] if n["arm"] == arm) for arm in ["original", "treatment"]
    }
    monetary = {
        arm: dict(
            normal_estimate_usd=sum(p["normal_charge_usd"] for p in data["pools"] if p["arm"] == arm and p["admitted"]),
            native_held_usd=sum(n["native_held_usd"] for n in data["native"] if n["arm"] == arm),
            normal_admitted=sum(p["admitted"] for p in data["pools"] if p["arm"] == arm),
        )
        for arm in totals
    }
    summary = dict(
        schema=1,
        counts=counts,
        native_admitted=totals,
        retained=retained,
        selected_cases=len(cases),
        original_queries=len(arms),
        source_known=len(cases),
        unknown_assessments=0,
        unknown_usage=0,
        shared_account_paid_usd=round(sum(r["usd"] for r in data["account_responses"] if r["event"] == "response"), 8),
        prior_separate_agentic_unknown_allocation_usd=0.127882,
        incremental_physical_usd=round(sum(o["new_usd"] for o in paid.values()), 8),
        new_calls=len(paid),
        new_calls_by_kind=dict(Counter(o["kind"] for o in paid.values())),
        unique_exact_reused_keys=len(data["requests"]) - len(paid),
        logical=monetary,
        partial_jev_cases=len({t["id"] for t in truncation}),
        full_body_jev_successor_required=False,
        decision="keep opt-in; positive bounded-report delta with source precision caveat; development replay only",
    )
    return summary, sorted(delta, key=lambda d: (d["change"], d["campaign"], d["id"])), truncation, list(cases.values())


def check_git(data):
    configs = {c["repository"]: c for c in data["source_configs"]}
    checked = {}
    for e in data["entries"]:
        c = Candidate.model_validate(e["packet"]["candidate"])
        for f, proof in zip((c.new, c.existing), e["binding"]["source_files"], strict=True):
            key = (e["packet"]["repository"], e["packet"]["revision"], proof["path"])
            if key not in checked:
                blob = subprocess.check_output(
                    ["git", "-C", configs[key[0]]["git"], "cat-file", "blob", key[1] + ":" + key[2]]
                )
                assert sha(blob) == proof["file_sha256"]
                checked[key] = blob
            blob = checked[key]
            assert sha(blob) == proof["file_sha256"]
            assert "\n".join(blob.decode().splitlines()[f.line - 1 : f.end_line]) == f.code
            if f.context.startswith("Owning file source prefix (may be truncated; full file in source proof):\n"):
                assert (
                    f.context
                    == "Owning file source prefix (may be truncated; full file in source proof):\n"
                    + blob.decode()[:6000]
                )
                assert f.context_digest == sha(blob)
    return len(checked)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--verify-local-git", action="store_true", help="Requires original local pinned source repositories"
    )
    args = parser.parse_args()
    manifest = HOME / "MANIFEST.json"
    if manifest.exists():
        for name, digest in json.loads(manifest.read_text())["files"].items():
            assert sha((HOME / name).read_bytes()) == digest, name
    data = load()
    with tempfile.TemporaryDirectory(
        prefix="balanced-replay-", dir=args.output.parent if args.output else None
    ) as temp:
        replay_native(data, Path(temp))
    summary, delta, truncation, cases = calculate(data)
    if args.verify_local_git:
        print("Verified immutable Git files:", check_git(data))
    expected = HOME / "summary.json"
    if expected.exists() and manifest.exists():
        assert summary == json.loads(expected.read_text())
    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
        for name, value in [
            ("summary.json", summary),
            ("native-deltas.json", delta),
            ("jev-truncation.json", truncation),
            ("selected-cases.json", cases),
        ]:
            (args.output / name).write_text(json.dumps(value, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
