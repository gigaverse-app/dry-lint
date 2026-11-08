"""Execute real Judging/CampaignStore over frozen candidates without providers or source stores."""

import argparse
import collections
import json
import re
import sys
import time
from pathlib import Path

from recorded_judge import MissingObservation, RecordedJudge, canonical, sha, write

import dry_lint
from dry_lint.discovery import CampaignStore
from dry_lint.judging import Judging
from dry_lint.models import Candidate, Run
from dry_lint.report import Finding, Report
from dry_lint.settings import Settings
from dry_lint.store import DirectoryStore, VerdictStore


class Corpus:
    def __init__(self, root):
        self.root = root.resolve()
        self.manifest = json.loads((self.root / "manifest.json").read_text())
        assert self.manifest["schema"] == 1

    def path(self, digest):
        assert re.fullmatch(r"[a-f0-9]{64}", digest), "Invalid object digest"
        path = self.root / "objects" / (digest + ".json")
        assert path.resolve().is_relative_to(self.root), "Object escapes corpus"
        assert sha(path) == digest, "Corrupt corpus object"
        return path

    def read(self, digest):
        return json.loads(self.path(digest).read_text())

    def original(self, old_path, digest):
        assert self.manifest["original_receipt_locations"][old_path] == digest
        return self.path(digest)  # Never open the historical absolute path.

    def observations(self):
        result = collections.defaultdict(list)
        for digest in self.manifest["observations"]:
            row = self.read(digest)
            assert canonical(row["identity"]) == row["request_key"]
            result[row["identity"].get("candidate_sha256")].append(
                {"path": "objects/" + digest + ".json", "sha256": digest, "row": row}
            )
        return result


def run_case(case, corpus, output, observations):
    settings = Settings.model_validate(case["settings"])
    assert settings.budget.usd == 0.04 and settings.escalate is None
    candidates = [Candidate.model_validate(row) for row in corpus.read(case["candidates"])]
    source = Run.model_validate(case["run"])
    folder = output / case["id"]
    judge = RecordedJudge(case["source"], settings, observations, corpus.original)
    store = VerdictStore(DirectoryStore(folder / "verdicts"))
    campaign = CampaignStore(folder / "campaign.sqlite3", source)
    judging = Judging(settings, judge, None, store)
    judging.campaign = campaign
    frontier = None
    try:
        findings = judging.findings(candidates, source)
    except MissingObservation as error:
        frontier = str(error)
        findings = []
        for candidate in candidates:
            if not candidate.filtered and candidate.lane != "relative":
                verdict = store.lookup(
                    candidate, judge.name, settings.reopen_margin, judge.version, exact_source=True
                ).verdict
                findings.append(Finding(candidate=candidate, verdict=verdict, deferred=verdict is None))
    report = Report.build(
        findings,
        settings,
        run=source,
        changed=1,
        judge=judge.name,
        filtered=[c for c in candidates if c.filtered],
        judging=judging.summary(),
    )
    state = campaign.snapshot()
    unknowns = [{"key": e["key"], "reason": e["unknown"]} for e in judge.events if e.get("unknown")]
    actual = {
        "id": case["id"],
        "arm": case["arm"],
        "complete": not unknowns,
        "emitted_by_scheduler": frontier is None,
        "missing_frontier": frontier,
        "unknowns": unknowns,
        "logical_usd": state.usd,
        "reported_pairs": [f.candidate.key for f in report.findings if f.reported],
    }
    assert state.usd <= 0.04 + 1e-12
    for field, expected in case["expected"].items():
        if field == "ledger":
            assert state.model_dump(mode="json") == corpus.read(expected), (case["id"], "ledger differs")
        else:
            assert actual[field] == expected, (case["id"], field, actual[field], expected)
    write(folder / "report.json", report.model_dump(mode="json"))
    write(folder / "ledger.json", state.model_dump(mode="json"))
    write(folder / "events.json", judge.events)
    actual["report_sha256"] = sha(folder / "report.json")
    return actual


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus", type=Path, required=True, help="Relocatable directory containing manifest.json and objects/"
    )
    parser.add_argument("--runtime", type=Path, required=True, help="Exact unchanged or patched source checkout")
    parser.add_argument("--arm", choices=["balanced", "residual"], required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    assert Path(dry_lint.__file__).resolve().is_relative_to(runtime), "Set PYTHONPATH to the selected runtime/src"
    sys.dont_write_bytecode = True
    corpus = Corpus(args.corpus)
    sources = {str(p.relative_to(runtime)): sha(p) for p in (runtime / "src/dry_lint").rglob("*.py")}
    assert sources == corpus.manifest["runtime_files"][args.arm], "Runtime differs from measured source"
    assert not args.out.exists(), "Use a new output directory"
    args.out.mkdir(parents=True)
    start = time.monotonic()
    observations = corpus.observations()
    results = [run_case(c, corpus, args.out, observations) for c in corpus.manifest["cases"] if c["arm"] == args.arm]
    write(args.out / "results.json", results)
    summary = {
        "arm": args.arm,
        "campaigns": len(results),
        "complete": sum(r["complete"] for r in results),
        "provider_calls": 0,
        "physical_usd": 0,
        "normal_phase_implemented": False,
        "wall_seconds": time.monotonic() - start,
        "exact_expected_ledgers_and_reports": True,
        "corpus_sha256": sha(args.corpus / "manifest.json"),
        "runtime_files": sources,
    }
    write(args.out / "SUMMARY.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "runtime_files"}))


if __name__ == "__main__":
    main()
