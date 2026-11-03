"""Run the offline channel trial; outputs contain repository code, so keep them private.

    uv run --extra dryer python scripts/benchmark_channel_trial.py --root ../project --out /private/trial
    uv run --extra dryer python scripts/benchmark_channel_trial.py --root ../project --out /private/trial \
        --gold old.jsonl --gold fresh.jsonl

Every channel indexes the whole repository with the production extractor, rules and filtering. A variant is a set
of channels: `check` retains a pair when any of its channels proposes it in either direction, `scan` when it is
any channel's mutual-nearest pair. `sample.json` holds pairs for blind labelling: some from the baseline scan, some
proposed only by a trial channel, none already labelled in the given gold files.
"""

import argparse
import json
import platform
import random
import time
from collections.abc import Callable
from pathlib import Path

from channel_trial import (
    CslsComparer,
    Floored,
    LsiComparer,
    behaviour_only,
    calibrated_floor,
    experimental,
    fold_plurals,
    mutual_nearest,
    nearest,
    share_with_neighbour,
)

from dry_lint.bench import load_gold
from dry_lint.comparers import TfidfComparer
from dry_lint.detector import Detector, why_skipped
from dry_lint.git import git
from dry_lint.models import pair_key
from dry_lint.plugins import Comparer, identity
from dry_lint.settings import Settings

Transform = Callable[[list[str]], list[str]]


def dryer() -> Comparer:
    from dry_lint.dryer import DryerComparer  # optional extra; a missing install makes the channel unavailable

    return DryerComparer()


# name: (token transform, comparer factory, neighbour slots). Production TF-IDF runs first: `Floored` channels
# calibrate against it. A floor of zero leaves the inner TF-IDF comparer's own floors out of the way.
CHANNELS: dict[str, tuple[Transform | None, Callable[[], Comparer], int]] = {
    "tfidf": (None, TfidfComparer, 3),
    "plural": (fold_plurals, lambda: experimental(TfidfComparer(), "plural"), 3),
    "csls": (None, lambda: CslsComparer(TfidfComparer()), 3),
    "plural-csls": (fold_plurals, lambda: CslsComparer(experimental(TfidfComparer(), "plural")), 3),
    "behaviour": (behaviour_only, lambda: Floored(experimental(TfidfComparer(0.0, 0.0), "behaviour")), 1),
    "lsi": (None, lambda: Floored(LsiComparer()), 1),
    "dryer": (None, dryer, 1),
}
VARIANTS = {
    "baseline": ("tfidf",),
    "plural": ("plural",),
    "csls": ("csls",),
    "plural-csls": ("plural-csls",),
    "behaviour": ("tfidf", "behaviour"),
    "lsi": ("tfidf", "lsi"),
    "dryer": ("tfidf", "dryer"),
    "channels": ("tfidf", "behaviour", "lsi", "dryer"),
    "combined": ("plural-csls", "behaviour", "lsi", "dryer"),
}
# Pairs to label per stratum: the baseline scan, then each trial channel's scan pairs that the baseline lacks.
SAMPLE = {"tfidf": 8, "plural": 4, "csls": 4, "behaviour": 4, "lsi": 4, "dryer": 4}


def run(root: Path, out: Path, gold_paths: list[Path] = (), seed: int = 20261106,
        channels: dict[str, tuple[Transform | None, Callable[[], Comparer], int]] = CHANNELS) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    base = Detector.for_repository(root, Settings())
    by_name = {f.qualname: f for f in base.functions}
    near, scans, report, unavailable = {}, {}, {}, {}
    for name, (transform, factory, slots) in channels.items():
        try:
            comparer = factory()
        except ValueError as error:
            unavailable[name] = str(error)
            continue
        functions = [f.model_copy(update={"tokens": transform(f.tokens)}) for f in base.functions] if transform else base.functions
        start = time.perf_counter()
        detector = Detector(functions, Settings(neighbours=slots), comparer, base.extractors)
        indexed = time.perf_counter() - start
        if isinstance(comparer, Floored):
            # Label-free calibration: as many functions keep a neighbour as with production TF-IDF.
            comparer.floor = calibrated_floor(nearest(detector), share_with_neighbour(near["tfidf"]))
        start = time.perf_counter()
        near[name] = nearest(detector)
        queried = time.perf_counter() - start
        scans[name] = mutual_nearest(detector, near[name])
        if name == "tfidf" and scans[name] != {frozenset((c.new.qualname, c.existing.qualname)) for c in detector.scan()}:
            raise AssertionError("The trial's scan must reproduce Detector.scan for production TF-IDF")
        pairs = sorted(scans[name], key=sorted)
        (out / f"{name}-scan.json").write_text(json.dumps([
            detector.pair(by_name[a], by_name[b], detector.comparer.similarity(by_name[a], by_name[b])).model_dump()
            for a, b in map(sorted, pairs)]), encoding="utf-8")
        report[name] = {"comparer": identity(comparer), "slots": slots, "index_seconds": round(indexed, 3),
                        "query_ms": round(1000 * queried / max(len(functions), 1), 3), "scan_pairs": len(pairs),
                        "floor": comparer.floor if isinstance(comparer, Floored) else None,
                        "share_with_neighbour": round(share_with_neighbour(near[name]), 4)}
    gold = [(path.stem, pair) for path in gold_paths for pair in load_gold(path) if pair.label != "borderline"]
    for _, pair in gold:
        if pair.new.id not in by_name or pair.existing.id not in by_name:
            raise ValueError(f"Gold pair missing from corpus: {pair.new.id}, {pair.existing.id}")
    baseline_candidates = sum(len(found) for found in near["tfidf"].values())
    variants = {}
    for variant, members in VARIANTS.items():
        if missing := [m for m in members if m not in near]:
            variants[variant] = {"unavailable": missing}
            continue
        scan = set().union(*(scans[m] for m in members))
        proposed = {name: {o for m in members for o, _ in near[m][name]} for name in by_name}
        scored = []
        for group, pair in gold:
            a, b = by_name[pair.new.id], by_name[pair.existing.id]
            settled = why_skipped(a, b, base.settings)
            scored.append({"group": group, "key": pair_key(a.qualname, b.qualname), "positive": pair.label == "duplicate",
                           "check": settled is None and (b.qualname in proposed[a.qualname] or a.qualname in proposed[b.qualname]),
                           "scan": frozenset((a.qualname, b.qualname)) in scan})
        total = sum(len(found) for found in proposed.values())
        variants[variant] = {"channels": list(members), "scan_pairs": len(scan),
                             "novel_scan_pairs": len(scan - scans["tfidf"]),
                             "candidates_per_function": round(total / len(by_name), 3),
                             "extra_candidates_per_function": round((total - baseline_candidates) / len(by_name), 3),
                             "scan_keys": sorted(pair_key(*p) for p in scan), "gold": scored}
    sample = draw(scans, {pair_key(p.new.id, p.existing.id) for _, p in gold}, random.Random(seed))
    rows = []
    for number, (stratum, pair) in enumerate(sample, 1):
        a, b = sorted(pair)
        rows.append({"id": number, "stratum": stratum, "key": pair_key(a, b),
                     "new": {"id": a, "code": by_name[a].code}, "existing": {"id": b, "code": by_name[b].code}})
    (out / "sample.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    results = {"schema": 1, "python": platform.python_version(), "head": git(root, "rev-parse", "HEAD"),
               "dirty": bool(git(root, "status", "--porcelain")), "functions": len(base.functions), "seed": seed,
               "channels": report, "unavailable": unavailable, "variants": variants}
    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


def draw(scans: dict[str, set[frozenset[str]]], labelled: set[str], rng: random.Random) -> list[tuple[str, frozenset[str]]]:
    """A fixed number per stratum, sorted then sampled with one RNG so the draw reproduces; no pair twice."""
    chosen: list[tuple[str, frozenset[str]]] = []
    taken = set(labelled)
    for stratum, size in SAMPLE.items():
        if stratum not in scans:
            continue
        pool = scans[stratum] - (scans["tfidf"] if stratum != "tfidf" else set())
        pool = sorted((p for p in pool if pair_key(*p) not in taken), key=sorted)
        for pair in rng.sample(pool, min(size, len(pool))):
            taken.add(pair_key(*pair))
            chosen.append((stratum, pair))
    rng.shuffle(chosen)
    return chosen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--gold", type=Path, action="append", default=[], help="GoldPair JSON lines; repeatable.")
    parser.add_argument("--seed", type=int, default=20261106)
    args = parser.parse_args()
    run(args.root.resolve(), args.out.resolve(), args.gold, args.seed)


if __name__ == "__main__":
    main()
