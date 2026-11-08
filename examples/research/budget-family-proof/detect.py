"""Run the pinned balanced Detector from portable frozen native functions; no judges."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import dry_lint
from dry_lint.bench_background import BenchBackground
from dry_lint.detector import Detector
from dry_lint.models import Function
from dry_lint.plugins import load
from dry_lint.settings import Settings


def run(root, output, query=None):
    retrieval = root / "retrieval"
    runtime = retrieval / "runtime"
    pin = json.loads((runtime / "PIN.json").read_text())
    for name, digest in pin["files"].items():
        assert hashlib.sha256((runtime / name).read_bytes()).hexdigest() == digest
    assert Path(dry_lint.__file__).resolve().is_relative_to((runtime / "src").resolve())
    inventory = json.loads((root / "proof/inventory.json").read_text())
    owners = {r["source_id"]: r for r in inventory["eligible"]}
    background = BenchBackground.decode((retrieval / "background.json.gz").read_bytes())
    functions = [
        Function.model_validate_json(line)
        for line in gzip.decompress((retrieval / "functions.jsonl.gz").read_bytes()).decode().splitlines()
    ]
    assert background.revision == inventory["revision"]
    for function, document in zip(functions, background.documents, strict=True):
        assert (function.qualname, hashlib.sha256(function.code.encode()).hexdigest()) == (
            document.id,
            document.source_sha256,
        )
        function.tokens = document.tokens()
    queries = [f for f in functions if f.qualname in owners and (query is None or f.qualname == query)]
    assert len(queries) == (10 if query is None else 1)
    settings = Settings.model_validate_json((retrieval / "settings.json").read_text())
    detector = Detector(
        functions, settings, load("comparers", settings.comparer), [load("extractors", c) for c in settings.extractors]
    )
    candidates = detector.candidates(queries)
    rows = [
        dict(
            query=c.new.qualname,
            target=c.existing.qualname,
            target_in_family=c.existing.qualname in owners,
            key=c.key,
            lane=c.lane,
            comparer=c.comparer,
            similarity=c.similarity,
            filtered=c.filtered,
        )
        for c in candidates
    ]
    expected_dir = "budget-family-current-detection" if query is None else "budget-family-current-detection-single"
    expected = [json.loads(line) for line in (retrieval / expected_dir / "candidates.jsonl").read_text().splitlines()]
    assert rows == expected
    output.mkdir(parents=True, exist_ok=False)
    (output / "candidates.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    result = dict(
        queries=len(queries),
        candidates=len(rows),
        direct_family_candidates=sum(r["target_in_family"] for r in rows),
        exact_recorded_candidates=True,
        provider_calls=0,
    )
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--query")
    args = parser.parse_args()
    run(args.fixture.resolve(), args.out, args.query)
