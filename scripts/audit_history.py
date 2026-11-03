"""Build a small, deterministic out-of-pool audit at each PR's final tree. Contains private source.

This is a nearest-excluded audit, not random sampling or a population recall estimate. It relaxes both
retrieval floors to zero, searches 50 neighbours, and takes one excluded partner per query per round.
"""

import argparse
import json
from pathlib import Path

from capture_history import History, tree_sources
from replay_coverage import ReplayInput, ReplayStep, pool
from semantic_signals import Signals

from dry_lint.comparers import TfidfComparer
from dry_lint.detector import Detector, changed_lines, touched
from dry_lint.extractors import PythonExtractor
from dry_lint.models import CandidatesFile
from dry_lint.settings import Settings


def audit(directory: Path, count: int = 2) -> ReplayInput:
    metadata = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    history = History.model_validate(metadata["history"])
    captured = ReplayInput.model_validate_json((directory / "replay.json").read_text(encoding="utf-8"))
    excluded = {key for step in captured.steps for key in pool(step)[0]}
    run = next(iter(captured.steps[-1].sources.values())).run
    settings = Settings(extractors=["python"], neighbours=50)
    sources = tree_sources(history.root, run.head, settings)
    extractor = PythonExtractor()
    signals = Signals(sources)
    functions = [f for path, code in sources.items() for f in extractor.functions(path, code)]
    functions = [
        f.model_copy(
            update={"tokens": f.tokens + [t for s in ("api", "binding", "flow") for t in signals.tokens(f.qualname, s)]}
        )
        for f in functions
    ]
    detector = Detector(functions, settings, TfidfComparer(min_similarity=0, min_similarity_small=0), [extractor])
    queries = touched(functions, changed_lines(history.root, history.base, head=run.head))
    queues = [
        [c for c in detector.candidates([q]) if c.key not in excluded and c.filtered is None]
        for q in sorted(queries, key=lambda q: q.qualname)
    ]
    chosen = {}
    while len(chosen) < count and any(queues):
        for queue in queues:
            if queue and len(chosen) < count:
                candidate = queue.pop(0)
                chosen.setdefault(candidate.key, candidate)
    snapshot = CandidatesFile(run=run, candidates=list(chosen.values()), changed=len(queries), functions=len(functions))
    return ReplayInput(steps=[ReplayStep(run_id=f"{run.head}/audit", sources={"semantic": snapshot})])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    for path in sorted(args.captures.glob("*/replay.json")):
        target = args.out / path.parent.name
        target.mkdir(parents=True, exist_ok=True)
        result = audit(path.parent)
        (target / "replay.json").write_text(result.model_dump_json(), encoding="utf-8")
        print(path.parent.name, len(pool(result.steps[0])[0]), "audit pairs", flush=True)


if __name__ == "__main__":
    main()
