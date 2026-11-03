"""Frozen-repository coverage probe, with no model calls. Outputs contain function identities; keep them private.

    uv run python scripts/probe_coverage.py --root ../project --gold /private/gold.jsonl --out /private/probe

Gold endpoints select queries, so this is a diagnostic experiment, not a population estimate or held-out result.
Without gold, query all extracted functions. Repeated steps are discovery opportunities on one frozen tree,
not historical commits. Cost is unit attempts, not tokens, dollars or live latency.
"""

import argparse
import json
import platform
import textwrap
from pathlib import Path

from replay_coverage import SCHEDULES, ReplayStep, replay
from semantic_signals import Signals

from dry_lint.bench import GoldPair, load_gold
from dry_lint.comparers import TfidfComparer
from dry_lint.detector import Detector
from dry_lint.git import git
from dry_lint.models import CandidatesFile, Run, pair_key
from dry_lint.settings import Settings


def capture(root: Path, gold: list[GoldPair], depth: int) -> tuple[ReplayStep, dict]:
    # This experiment matches the earlier Python semantic trial; it makes no TypeScript signal claim.
    settings = Settings(extractors=["python"])
    base = Detector.for_repository(root, settings)
    names = sorted({f.id for g in gold for f in (g.new, g.existing)}) if gold else sorted(base.position)
    queries = [base.find(name) for name in names if name in base.position]
    signals = Signals({path: (root / path).read_text(encoding="utf-8") for path in {f.path for f in base.functions}})
    functions = [
        f.model_copy(
            update={
                "tokens": f.tokens
                + [token for feature in ("api", "binding", "flow") for token in signals.tokens(f.qualname, feature)]
            }
        )
        for f in base.functions
    ]
    broad = settings.model_copy(update={"neighbours": depth})
    semantic_comparer = TfidfComparer(min_similarity=0.35, min_similarity_small=0.2)
    semantic_comparer.name, semantic_comparer.version = "trial-combined-tfidf", "1"
    semantic_comparer.similarity_reusable = False
    semantic = Detector(functions, broad, semantic_comparer, base.extractors)
    deep = Detector(base.functions, broad, TfidfComparer(), base.extractors)
    run = Run(repository=root.name, head=git(root, "rev-parse", "HEAD"))
    sources = {
        name: CandidatesFile(
            run=run,
            changed=len(queries),
            functions=len(base.functions),
            candidates=detector.candidates([detector.find(f.qualname) for f in queries]),
        )
        for name, detector in (("baseline", base), ("semantic", semantic), ("deep", deep))
    }
    positive, negative, stale, missing, borderline = set(), set(), 0, 0, 0
    for label in gold:
        if label.label == "borderline":
            borderline += 1
        elif any(f.id not in base.position for f in (label.new, label.existing)):
            missing += 1
        elif any(
            textwrap.dedent(f.code).strip() != textwrap.dedent(base.find(f.id).code).strip()
            for f in (label.new, label.existing)
        ):
            stale += 1
        else:
            target = positive if label.label == "duplicate" else negative
            target.add(pair_key(label.new.id, label.existing.id))
    if positive & negative:
        raise ValueError("conflicting gold labels for an unchanged pair")
    metadata = {
        "schema": 1,
        "head": run.head,
        "dirty": bool(git(root, "status", "--porcelain")),
        "python": platform.python_version(),
        "functions": len(base.functions),
        "queries": len(queries),
        "depth": depth,
        "semantic_floors": [0.35, 0.2],
        "positive_keys": sorted(positive),
        "negative_keys": sorted(negative),
        "stale_labels": stale,
        "missing_labels": missing,
        "borderline_labels": borderline,
    }
    return ReplayStep(run_id="capture", sources=sources), metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--gold", type=Path, nargs="*", default=[])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--passes", type=int, default=5)
    parser.add_argument("--per-run", type=int, default=100)
    parser.add_argument("--total", type=int, default=500)
    parser.add_argument("--depth", type=int, default=20)
    args = parser.parse_args()
    if args.passes < 1 or args.depth < 3:
        parser.error("passes must be positive and depth must be at least 3")
    frozen, metadata = capture(args.root.resolve(), [g for path in args.gold for g in load_gold(path)], args.depth)
    steps = [frozen.model_copy(update={"run_id": f"opportunity-{n + 1}"}) for n in range(args.passes)]
    args.out.mkdir(parents=True, exist_ok=True)
    metadata.update(
        {
            "passes": args.passes,
            "per_run": args.per_run,
            "total": args.total,
            "experiment": "Frozen tree; gold-selected queries; simulated unit-cost attempts.",
        }
    )
    results = {}
    positives, negatives = set(metadata["positive_keys"]), set(metadata["negative_keys"])
    for policy in SCHEDULES:
        result = replay(steps, policy, args.per_run, args.total)
        (args.out / f"{policy}.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
        examined = set()
        curve = []
        for step in result.steps:
            examined.update(s.key for s in step.selected if s.success)
            curve.append(
                {
                    "run": step.run_id,
                    "attempts": step.cumulative_attempts,
                    "covered": step.covered,
                    "pool": step.pool,
                    "deferred": step.deferred,
                    "positive_examined": len(positives & examined),
                    "negative_examined": len(negatives & examined),
                    "unlabelled_examined": len(examined - positives - negatives),
                }
            )
        results[policy] = curve
        print(policy, json.dumps(curve[-1]), flush=True)
    (args.out / "summary.json").write_text(json.dumps({**metadata, "policies": results}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
