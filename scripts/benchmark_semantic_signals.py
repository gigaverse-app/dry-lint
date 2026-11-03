"""Run the offline semantic trial; outputs contain repository code, so keep them private.

    uv run python scripts/benchmark_semantic_signals.py --root ../project --out /private/trial
    uv run python scripts/benchmark_semantic_signals.py --root ../project --out /private/trial --gold gold.jsonl

The three features are independent, additive, unweighted probes. Production thresholds and filtering stay fixed.
"""

import argparse
import json
import platform
import time
from pathlib import Path

from semantic_signals import Signals

from dry_lint.bench import load_gold
from dry_lint.comparers import TfidfComparer
from dry_lint.detector import Detector
from dry_lint.git import git
from dry_lint.settings import Settings

VARIANTS = {"baseline": (), "api": ("api",), "binding": ("binding",), "flow": ("flow",),
            "combined": ("api", "binding", "flow")}


def run(root: Path, out: Path, gold_path: Path | None = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    base = Detector.for_repository(root, Settings())
    signals = Signals({path: (root / path).read_text(encoding="utf-8") for path in {f.path for f in base.functions}})
    features = {f.qualname: {feature: signals.tokens(f.qualname, feature) for feature in ("api", "binding", "flow")}
                for f in base.functions}
    gold = load_gold(gold_path) if gold_path else []
    metadata = {"schema": 1, "python": platform.python_version(),
                "head": git(root, "rev-parse", "HEAD"), "dirty": bool(git(root, "status", "--porcelain")),
                "functions": len(base.functions), "coverage": {
                    feature: sum(bool(tokens[feature]) for tokens in features.values()) for feature in ("api", "binding", "flow")}}
    results = {}
    for variant, selected in VARIANTS.items():
        start = time.perf_counter()
        functions = [f.model_copy(update={"tokens": f.tokens + [t for s in selected for t in features[f.qualname][s]]})
                     for f in base.functions]
        comparer = TfidfComparer()
        if selected:
            # Experimental similarities must never masquerade as the production scale in a verdict cache.
            comparer.name, comparer.version = f"trial-{variant}-tfidf", "1"
            comparer.similarity_reusable = False
        detector = Detector(functions, Settings(), comparer, base.extractors)
        scan = detector.scan()
        scan_keys = {p.key for p in scan}
        (out / f"{variant}-scan.json").write_text(json.dumps([p.model_dump() for p in scan]), encoding="utf-8")
        scored = []
        for pair in gold:
            if pair.new.id not in detector.position or pair.existing.id not in detector.position:
                raise ValueError(f"Gold pair missing from corpus: {pair.new.id}, {pair.existing.id}")
            a, b = detector.find(pair.new.id), detector.find(pair.existing.id)
            target = detector.pair(a, b, detector.comparer.similarity(a, b))
            candidates = detector.candidates([a, b])
            scored.append({"key": target.key, "label": pair.label, "score": round(detector.comparer.similarity(a, b), 12),
                           "check": any(p.key == target.key and p.filtered is None for p in candidates),
                           "scan": target.key in scan_keys})
        results[variant] = {"comparer": detector.comparer_id, "seconds": round(time.perf_counter() - start, 2),
                            "scan_pairs": len(scan), "gold": scored}
        print(f"{root.name}: {variant} complete", flush=True)
    (out / "results.json").write_text(json.dumps({**metadata, "variants": results}, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--gold", type=Path)
    args = parser.parse_args()
    run(args.root.resolve(), args.out.resolve(), args.gold)


if __name__ == "__main__":
    main()
