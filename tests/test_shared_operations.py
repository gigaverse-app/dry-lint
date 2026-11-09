"""Opt-in prompt policy uses the canonical SDK and cannot inherit a legacy cached answer."""

import json

import pytest

from dry_lint.costs import estimate
from dry_lint.judges.anthropic import AnthropicJudge
from dry_lint.judges.command import OPERATIONS_VERSION, prompt
from dry_lint.judging import Judging
from dry_lint.models import Verdict
from dry_lint.settings import Settings
from dry_lint.store import DirectoryStore, VerdictStore

from conftest import claude, coverage_pair


def test_opt_in_operation_policy_reaches_provider_and_invalidates_legacy_cache(tmp_path) -> None:
    candidate = coverage_pair()
    store = VerdictStore(DirectoryStore(tmp_path))
    store.remember(
        candidate, Verdict(label="separate", score=0.1, judge="anthropic", judge_version="dry-v1:claude-sonnet-5-5")
    )
    requests = []
    reply = {"stop_reason": "end_turn", "content": [{"type": "text", "text": '{"label":"duplicate","score":0.8}'}]}
    judge = AnthropicJudge(
        api_key="test", prompt_policy="shared-operations", max_tokens=1024, http_client=claude(reply, requests)
    )
    findings = Judging(Settings(escalate=None), judge, None, store).findings([candidate])
    assert findings[0].verdict.label == "duplicate"
    assert not findings[0].cached
    body = json.loads(requests[0].content)
    assert body["max_tokens"] == 1024
    assert "shared sub-operation" in body["messages"][0]["content"]
    assert judge.version.startswith(OPERATIONS_VERSION + ":")
    assert "output=1024" in judge.version
    assert Judging(Settings(escalate=None), judge, None, store).findings([candidate])[0].cached
    revised = AnthropicJudge(
        api_key="test", prompt_policy="shared-operations", max_tokens=2048, http_client=claude(reply, requests)
    )
    assert not Judging(Settings(escalate=None), revised, None, store).findings([candidate])[0].cached
    assert len(requests) == 2
    default_requests = []
    default = AnthropicJudge(api_key="test", http_client=claude(reply, default_requests))
    assert not Judging(Settings(escalate=None), default, None, store).findings([candidate])[0].cached
    assert len(default_requests) == 1  # different response limit still invalidates cache
    assert estimate(default, [candidate], Settings()) > 0


def test_default_prompt_uses_the_shared_operation_policy() -> None:
    candidate = coverage_pair()
    judge = AnthropicJudge(api_key="test")
    assert judge.name == "anthropic-operations"
    assert judge.version == f"{OPERATIONS_VERSION}:claude-sonnet-5-5"
    assert judge.strict_version
    assert prompt(candidate) == prompt(candidate, policy="concept") == prompt(candidate, policy="shared-operations")
    assert "already delegate" in prompt(candidate)


def test_model_policy_reaches_provider_with_distinct_identity() -> None:
    requests = []
    reply = {"content": [{"type": "text", "text": '{"label":"separate","score":0.1}'}]}
    judge = AnthropicJudge(api_key="test", prompt_policy="model-contracts", http_client=claude(reply, requests))
    [verdict] = judge.judge([coverage_pair()], Settings())
    assert verdict.judge == "anthropic-models"
    assert verdict.judge_version.startswith("dry-model-contracts-v2:")
    assert "independent test oracles" in json.loads(requests[0].content)["messages"][0]["content"]


def test_compact_policy_uses_separate_evidence_and_bounded_response() -> None:
    requests = []
    reply = {"content": [{"type": "text", "text": '{"label":"duplicate","score":0.9,"why":"Shared cancellation."}'}]}
    judge = AnthropicJudge(
        api_key="test", prompt_policy="shared-operations-compact", max_tokens=512, http_client=claude(reply, requests)
    )
    [verdict] = judge.judge([coverage_pair()], Settings())
    assert verdict.judge_version.startswith(OPERATIONS_VERSION + ":")
    assert len(prompt(coverage_pair(), policy="shared-operations-compact")) == len(
        prompt(coverage_pair(), policy="shared-operations")
    )
    body = json.loads(requests[0].content)
    assert body["max_tokens"] == 512
    assert "shared sub-operation" in body["messages"][0]["content"]


@pytest.mark.parametrize("options", [{"prompt_policy": "unknown"}, {"max_tokens": 0}])
def test_invalid_prompt_configuration_fails_before_provider_request(options) -> None:
    with pytest.raises(ValueError):
        AnthropicJudge(api_key="test", **options)
