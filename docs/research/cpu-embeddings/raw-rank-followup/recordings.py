# ruff: noqa: E401, E402, E741, F401, F403, F405, I001, B007
# Frozen experiment adapters intentionally preserve import order and shared wildcard exports.
"""Reparse recorded answer text with the immutable runtime parser, without provider clients."""

from collections import Counter
from dry_lint.judges.command import parse_verdict
from dry_lint.models import Verdict


def reparse_observations(observations):
    counts = Counter()
    for record in observations:
        identity = record["identity"]
        if identity["kind"] != "claude":
            continue
        answers = record["recorded_answers"]
        assert len(answers) == 1, (record["request_key"], "unexpected retry count")
        assert answers[0]["stop_reason"] != "refusal"
        text = "".join(answers[0]["text"])
        verdict = parse_verdict(text, identity["judge"], identity["version"])
        assert verdict.model_dump(mode="json") == Verdict.model_validate(record["verdict"]).model_dump(mode="json"), (
            record["request_key"]
        )
        counts[
            "reparsed_primary_answers" if identity["model"] == "claude-haiku-5-5" else "reparsed_diagnostic_answers"
        ] += 1
    return counts
