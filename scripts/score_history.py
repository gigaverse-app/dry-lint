"""Score exact historical evidence against independent reference labels; missing labels are never negatives.

Inputs are private capture/live/reference directories. Output is aggregate JSON without function source or names.
Recall is conditional on the reviewed retrieval pool, not all duplication in a repository.
"""

import argparse
import json
from pathlib import Path

from capture_history import History, tree_sources
from judge_history import Observation, judge_for_result, key_for_result
from replay_coverage import ReplayInput, pool

from dry_lint.comparers import TfidfComparer
from dry_lint.detector import Detector, changed_lines, touched
from dry_lint.extractors import PythonExtractor
from dry_lint.settings import Settings


def retrieval_ablation(directory: Path, positives: set[str]) -> dict:
    """Final-tree retrieval only; positives come from the independently reviewed pool, not an exhaustive oracle."""
    history = History.model_validate(json.loads((directory / "manifest.json").read_text(encoding="utf-8"))["history"])
    step = ReplayInput.model_validate_json((directory / "replay.json").read_text(encoding="utf-8")).steps[-1]
    run = next(iter(step.sources.values())).run

    def counts(candidates) -> dict:
        keys = {c.key for c in candidates if c.filtered is None}
        return {"pairs": len(keys), "known_positives": len(keys & positives)}

    results = {name: counts(source.candidates) for name, source in step.sources.items()}
    settings, extractor = Settings(extractors=["python"]), PythonExtractor()
    sources = tree_sources(history.root, run.head, settings)
    functions = [f for path, code in sources.items() for f in extractor.functions(path, code)]
    queries = touched(functions, changed_lines(history.root, history.base, head=run.head))
    for depth in (3, 20):
        detector = Detector(
            functions,
            settings.model_copy(update={"neighbours": depth}),
            TfidfComparer(min_similarity=0.35, min_similarity_small=0.2),
            [extractor],
        )
        results[f"lexical-relaxed-{depth}"] = counts(detector.candidates(queries))
    return results


def score(payload: ReplayInput, result: dict, labels: dict[str, str], observations: dict[str, Observation]) -> dict:
    if len(payload.steps) != len(result["curves"]):
        raise ValueError("Capture and live result have different revision counts")
    curves, seen_positive, found_positive, reported_positive, selected_answers = [], set(), set(), set(), set()
    thresholds = {}
    for ordinal, (step, curve) in enumerate(zip(payload.steps, result["curves"], strict=True), 1):
        if step.run_id != curve["run_id"]:
            raise ValueError("Capture and live result have different revision identities")
        candidates, ranks = pool(step)
        keys = {k: key_for_result(c, ranks[k], result) for k, c in candidates.items()}
        thresholds.update(
            {v: judge_for_result(ranks[k], result).get("report_at", result["report_at"]) for k, v in keys.items()}
        )
        if any(keys.get(k) != v for k, v in curve["covered"].items()):
            raise ValueError("A verdict was credited against stale or absent evidence")
        positives = {k for k, v in keys.items() if labels.get(v) == "duplicate"}
        negatives = {k for k, v in keys.items() if labels.get(v) == "separate"}
        covered, reported = set(curve["covered"]), set(curve["reported"])
        if not reported <= covered:
            raise ValueError("A report has no current judgment")
        seen_positive.update(positives)
        found_positive.update(positives & covered)
        reported_positive.update(positives & reported)
        selected_answers.update(s["answer"] for s in curve["selected"])
        curves.append(
            {
                "commit": ordinal,
                "head": curve["head"],
                "pool": len(keys),
                "positives": len(positives),
                "baseline_positives": sum("baseline" in ranks[k] for k in positives),
                "judged_positives": len(positives & covered),
                "reported_positives": len(positives & reported),
                "false_reports": len(negatives & reported),
                "unresolved_reports": len(reported - positives - negatives),
                "unlabelled_pool": sum(v not in labels for v in keys.values()),
                "ever_available_positives": len(seen_positive),
                "ever_judged_positives": len(found_positive),
                "ever_reported_positives": len(reported_positive),
                "new_answers": len(curve["selected"]),
                "cumulative_attempts": curve["cumulative_attempts"],
                "cumulative_usd": curve["cumulative_usd"],
                "serial_api_seconds": curve["serial_api_seconds"],
            }
        )
    reports = {
        key
        for key in selected_answers
        if observations[key].verdict is not None
        and observations[key].verdict.label != "separate"
        and observations[key].verdict.score >= thresholds[key]
    }
    valid_answers = {k for k in selected_answers if observations[k].verdict is not None}
    return {
        "policy": result["policy"],
        "curves": curves,
        "unique_judged_evidence": len(valid_answers),
        "unique_failed_evidence": len(selected_answers - valid_answers),
        "unique_judged_positive_evidence": sum(labels.get(k) == "duplicate" for k in valid_answers),
        "unique_true_reports": sum(labels.get(k) == "duplicate" for k in reports),
        "unique_false_reports": sum(labels.get(k) == "separate" for k in reports),
        "unique_unresolved_reports": sum(labels.get(k) not in ("duplicate", "separate") for k in reports),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--ablate", action="store_true", help="Rebuild final-tree lexical controls at matching floors")
    args = parser.parse_args()
    root = args.root
    rows = json.loads((root / "reference/labels.json").read_text(encoding="utf-8"))
    labels = {r["answer"]: r["label"] for r in rows}
    observations = {
        p.stem: Observation.model_validate_json(p.read_text(encoding="utf-8"))
        for p in (root / "live/answers").glob("*.json")
    }
    results = {}
    ablations = {}
    for path in sorted((root / "captures").glob("*/replay.json")):
        payload = ReplayInput.model_validate_json(path.read_text(encoding="utf-8"))
        results[path.parent.name] = {
            policy: score(
                payload,
                json.loads((root / "live" / f"{path.parent.name}-{policy}.json").read_text()),
                labels,
                observations,
            )
            for policy in ("fixed", "refill")
        }
        if args.ablate:
            positives = {r["pair"] for r in rows if r["cohort"] == path.parent.name and r["label"] == "duplicate"}
            ablations[path.parent.name] = retrieval_ablation(path.parent, positives)
    totals = {"requests": len(observations), "usd": sum(o.usd for o in observations.values())}
    for field in ("input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens", "seconds"):
        totals[field] = sum(getattr(o, field) for o in observations.values())
    (root / "scored.json").write_text(
        json.dumps({"physical_usage": totals, "cohorts": results}, indent=2), encoding="utf-8"
    )
    if args.ablate:
        (root / "ablation.json").write_text(json.dumps(ablations, indent=2), encoding="utf-8")
    print(json.dumps(totals))
    for cohort, policies in results.items():
        for policy, result in policies.items():
            print(
                cohort,
                policy,
                json.dumps(result["curves"][-1]),
                "reports",
                result["unique_true_reports"],
                result["unique_false_reports"],
                result["unique_unresolved_reports"],
            )


if __name__ == "__main__":
    main()
