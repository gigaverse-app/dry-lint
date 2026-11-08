"""Strict recorded Judge plugin extracted from the validated v2 adapter.

Only change: original-receipt paths resolve through the supplied content-addressed
corpus. Immutable receipt bytes and their original identities are never rewritten.
"""

import hashlib
import json
from pathlib import Path

from dry_lint.costs import price, usage_cost
from dry_lint.judges.command import PROMPT_POLICIES, parse_verdict, prompt
from dry_lint.models import Verdict, evidence


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def canonical(value):
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=True))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def original_candidate(candidate):
    data = candidate.model_dump(mode="json")
    data.pop("residual", None)  # The ONLY allowed normalization: scheduling metadata never enters the question.
    return data


class MissingObservation(BaseException):
    """Stop the run at its real reserved frontier; production finally retains its conservative hold."""


class RecordedJudge:
    name = "anthropic-operations"
    strict_version = True
    subscription = False

    def __init__(self, source, settings, observations, resolve_observation):
        expected = {
            "model": "claude-haiku-5-5",
            "max_tokens": 2048,
            "max_retries": 0,
            "prompt_policy": "shared-operations",
        }
        assert settings.judge.use == "anthropic" and settings.judge.options() == expected
        self.model, self.max_tokens, self.prompt_policy = (
            expected["model"],
            expected["max_tokens"],
            expected["prompt_policy"],
        )
        self.version = f"{PROMPT_POLICIES[self.prompt_policy][0]}:{self.model}:output={self.max_tokens}"
        self.source, self.settings, self.observations = source, settings, observations
        self.resolve_observation = resolve_observation
        self.tokens = {"input": 0, "output": 0}
        self.events = []

    def expected(self, candidate):
        return dict(
            repository=self.source["repository"],
            revision=self.source["revision"],
            background_sha256=self.source["background_sha256"],
            scope=self.source["scope"],
            candidate_sha256=canonical(original_candidate(candidate)),
            context_hash=candidate.context_hash,
            model=self.model,
            judge=self.name,
            version=self.version,
            max_output_tokens=self.max_tokens,
            rendered_input=prompt(candidate, policy=self.prompt_policy),
            source_evidence=evidence(candidate),
            execution_profile="balanced-shadow-haiku55-v1",
            kind="claude",
            request_options={
                "effort": None,
                "max_retries": 0,
                "prompt_policy": self.prompt_policy,
                "retry_malformed": False,
                "server_side_fallbacks": "disabled",
            },
            settings={
                "report_at": self.settings.report_at,
                "drop_below": self.settings.drop_below,
                "drift_at": self.settings.drift_at,
            },
        )

    def lookup(self, candidate):
        expected = self.expected(candidate)
        matches, mismatches = [], []
        for entry in self.observations.get(expected["candidate_sha256"], []):
            row = entry["row"]
            fields = [k for k, value in expected.items() if row["identity"].get(k) != value]
            if fields:
                mismatches.append({"path": entry["path"], "fields": fields})
            else:
                matches.append(entry)
        # Duplicate snapshot aliases are fine only for the exact same result and charge.
        results = {canonical({k: e["row"].get(k) for k in ("verdict", "error", "usage", "usd")}) for e in matches}
        if len(results) > 1:
            raise AssertionError("Conflicting exact observations; root must reconcile them")
        return (matches[0] if matches else None), mismatches

    def verify_physical_source(self, row, candidate):
        expected = self.expected(candidate)
        endpoints = sorted((f.qualname, digest(f.code)) for f in (candidate.new, candidate.existing))
        chain, seen = [], set()
        while True:
            assert sorted((f["source_id"], f["body_sha256"]) for f in row["identity"]["source_files"]) == endpoints
            for field in (
                "repository",
                "revision",
                "scope",
                "context_hash",
                "source_evidence",
                "execution_profile",
                "kind",
                "rendered_input",
                "model",
                "judge",
                "version",
                "max_output_tokens",
                "request_options",
                "settings",
            ):
                assert row["identity"].get(field) == expected[field], ("physical question differs", field)
            alias = row.get("question_equivalence")
            if not alias:
                return chain
            path = alias["original_observation"]
            assert path not in seen, "Observation alias cycle"
            seen.add(path)
            resolved = self.resolve_observation(path, alias["original_observation_sha256"])
            assert sha(resolved) == alias["original_observation_sha256"]
            original = json.loads(resolved.read_text())
            assert canonical(original["identity"]) == original["request_key"]
            for field in ("raw_responses", "verdict", "error", "usage", "usd"):
                assert original.get(field) == row.get(field), ("Alias changed physical observation", field)
            chain.append({"path": path, "sha256": sha(resolved), "request_key": original["request_key"]})
            row = original

    def judge(self, candidates, settings):
        assert settings is self.settings and len(candidates) == 1
        candidate = candidates[0]
        entry, mismatches = self.lookup(candidate)
        event = {
            "key": candidate.key,
            "candidate": candidate.model_dump(mode="json"),
            "expected_identity": self.expected(candidate),
            "mismatches": mismatches,
            "observation": {k: entry[k] for k in ("path", "sha256")} if entry else None,
        }
        self.events.append(event)
        if entry is None:
            event["unknown"] = "missing_exact_recording"
            raise MissingObservation(candidate.key)
        row = entry["row"]
        event["verified_physical_chain"] = self.verify_physical_source(row, candidate)
        usage = row.get("usage")
        if usage:
            tokens = {
                "input": usage.get("input_tokens", 0),
                "output": usage.get("output_tokens", 0),
                "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
                "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
            }
            assert all(isinstance(n, (int, float)) and n >= 0 for n in tokens.values())
            actual = usage_cost(tokens, price(self, settings))
            assert abs(actual - row["usd"]) < 1e-12
            for key, value in tokens.items():
                self.tokens[key] = self.tokens.get(key, 0) + value
            event["recorded_actual_usd"] = actual
        if not usage or row.get("error") or row.get("verdict") is None:
            event["unknown"] = row.get("error") or "recorded_usage_or_verdict_unknown"
            raise ValueError("Recorded failure: " + event["unknown"])
        verdict = Verdict.model_validate(row["verdict"])
        assert verdict.judge == self.name and verdict.judge_version == self.version
        responses = row.get("raw_responses", [])
        assert len(responses) == 1, "Exactly one physical response required; no retry pooling"
        raw = responses[0]["json"]
        assert responses[0]["http_status"] == 200 and raw["model"] == self.model
        assert raw.get("stop_reason") != "refusal" and raw["usage"] == usage
        text = "".join(block["text"] for block in raw["content"] if block["type"] == "text")
        assert parse_verdict(text, self.name, self.version) == verdict, "Recorded verdict differs from native parser"
        event["unknown"] = None
        event["request_key"] = row["request_key"]
        event["physical_provenance"] = row.get("question_equivalence") or row.get("source_physical_request_key")
        return [verdict]
