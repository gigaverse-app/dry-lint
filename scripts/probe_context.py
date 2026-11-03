"""Compare pinned function-only and contextual Jev judging on reviewed snapshot pairs."""

import argparse
import hashlib
import json
import time
from pathlib import Path

import httpx

from dry_lint.comparers import TfidfComparer
from dry_lint.detector import Detector
from dry_lint.git import git
from dry_lint.judges.jev import JevJudge
from dry_lint.models import Run
from dry_lint.settings import Settings
from dry_lint.typescript import TypeScriptExtractor


class Meter(httpx.BaseTransport):
    def __init__(self):
        self.transport = httpx.HTTPTransport(retries=2)
        self.responses = []

    def handle_request(self, request):
        response = self.transport.handle_request(request)
        response.read()
        if response.is_success:
            data = response.json()
            self.responses.append({"model": data.get("model"), "usage": data.get("usage"),
                                   "request_bytes": len(request.content), "answers": data.get("answers")})
        return response

    def close(self):
        self.transport.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--repo", action="append", required=True, metavar="OWNER/NAME=PATH")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    roots = {name: Path(path) for name, path in (spec.split("=", 1) for spec in args.repo)}
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    extractor, files = TypeScriptExtractor(), {}

    def function(side):
        key = (side["repository"], side["revision"], side["path"])
        if key not in files:
            source = git(roots[key[0]], "show", f"{key[1]}:{key[2]}")
            files[key] = extractor.functions(key[2], source)
        found = [f for f in files[key] if f.name == side["name"] and f.owner == side["owner"]]
        if len(found) != 1 or hashlib.sha256(found[0].code.encode()).hexdigest() != side["code_hash"]:
            raise ValueError(f"Snapshot no longer matches labelled source: {key}::{side['name']}")
        return found[0].model_copy(update={"origin": Run(repository=key[0], head=key[1])})

    sides = [(function(case["new"]), function(case["existing"])) for case in cases]
    settings = Settings.load(args.root)
    detector = Detector([f for pair in sides for f in pair], settings, TfidfComparer(), [extractor])
    candidates = [detector.pair(a, b, case["similarity"]) for (a, b), case in zip(sides, cases, strict=True)]
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "candidates.json").write_text(json.dumps([p.model_dump() for p in candidates], indent=2), encoding="utf-8")
    if args.prepare_only:
        print(f"Prepared {len(candidates)} unchanged labelled pairs with source context")
        return
    results = {}
    for arm in ["baseline", "context"]:
        meter = Meter()
        judge = JevJudge(model="jev-1.14.0", context=arm == "context", workers=4, transport=meter)
        start = time.perf_counter()
        verdicts = judge.judge(candidates, settings)
        rows = [{"id": case["id"], "label": case["label"], "regression": case["regression"],
                 "reported": verdict.label != "separate" and verdict.score >= settings.report_at,
                 "verdict": verdict.model_dump()} for case, verdict in zip(cases, verdicts, strict=True)]
        results[arm] = {"seconds": time.perf_counter() - start, "version": judge.version, "rows": rows,
                        "responses": meter.responses,
                        "true_positives": sum(r["reported"] and r["label"] == "duplicate" for r in rows),
                        "false_positives": sum(r["reported"] and r["label"] == "separate" for r in rows),
                        "regression_false_positives": sum(r["reported"] and r["regression"] for r in rows)}
        (args.output / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(arm, json.dumps({k: v for k, v in results[arm].items() if k not in {"rows", "responses"}}), flush=True)
    improved = results["context"]
    if improved["regression_false_positives"] or improved["true_positives"] < 8:
        raise SystemExit("Context probe did not meet the five-negative / eight-positive acceptance criteria")
    if improved["false_positives"] >= results["baseline"]["false_positives"]:
        raise SystemExit("Context probe did not reduce false positives")


if __name__ == "__main__":
    main()
