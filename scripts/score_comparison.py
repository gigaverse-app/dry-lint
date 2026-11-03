"""Score paired prompt/scheduler replays against blinded, prompt-independent evidence labels.

Labels are JSON rows with evidence=answer_key(candidate, "reference-v1") and label.
Output contains aggregate metrics and commit identities, never captured source or function names.
"""

import argparse
import json
from pathlib import Path

from judge_history import Observation, answer_key
from replay_coverage import ReplayInput, pool
from score_history import score


def score_comparison(captures: Path, results: Path, labels: Path, answers: Path) -> dict:
    reference = {}
    for row in json.loads(labels.read_text(encoding="utf-8")):
        identity = row["evidence"]
        if identity in reference and reference[identity] != row["label"]:
            raise ValueError("Conflicting labels for identical evidence")
        reference[identity] = row["label"]
    observations = {
        p.stem: Observation.model_validate_json(p.read_text(encoding="utf-8")) for p in answers.glob("*.json")
    }
    cohorts = {}
    for path in sorted(captures.glob("*/replay.json")):
        payload = ReplayInput.model_validate_json(path.read_text(encoding="utf-8"))
        arms = {}
        for result_path in sorted(results.glob(f"{path.parent.name}-*.json")):
            if result_path.name.endswith("-packets.json"):
                continue
            result = json.loads(result_path.read_text(encoding="utf-8"))
            policy = result["prompt_policy"]
            translated = {}
            for step in payload.steps:
                for candidate in pool(step)[0].values():
                    identity = answer_key(candidate, "reference-v1")
                    if identity in reference:
                        translated[
                            answer_key(candidate, result["judge"], policy, template=result.get("prompt_template"))
                        ] = reference[identity]
            arms[f"{policy}/{result['policy']}"] = score(payload, result, translated, observations)
        cohorts[path.parent.name] = arms
    return {
        "physical_usage": {
            "scope": "entire answer directory, including development, retries and failed paid answers",
            "requests": len(observations),
            "failures": sum(o.error is not None for o in observations.values()),
            **{
                field: sum(getattr(o, field) for o in observations.values())
                for field in ("usd", "input_tokens", "output_tokens", "seconds")
            },
        },
        "cohorts": cohorts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("captures", "results", "labels", "answers", "out"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    result = score_comparison(args.captures, args.results, args.labels, args.answers)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["physical_usage"]))


if __name__ == "__main__":
    main()
