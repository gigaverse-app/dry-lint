"""Opt-in prompt policy uses the canonical SDK and cannot inherit a legacy cached answer."""

import json

import pytest

from dry_lint.costs import estimate
from dry_lint.judges.anthropic import AnthropicJudge
from dry_lint.judges.command import prompt
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
    assert judge.version.startswith("dry-operations-v1:")
    assert "output=1024" in judge.version
    assert Judging(Settings(escalate=None), judge, None, store).findings([candidate])[0].cached
    legacy = AnthropicJudge(api_key="test", http_client=claude(reply, []))
    assert estimate(judge, [candidate], Settings()) > estimate(legacy, [candidate], Settings())


def test_default_prompt_remains_legacy() -> None:
    candidate = coverage_pair()
    judge = AnthropicJudge(api_key="test")
    assert judge.name == "anthropic"
    assert judge.version == "dry-v1:claude-sonnet-5-5"
    assert prompt(candidate) == prompt(candidate, policy="concept")


@pytest.mark.parametrize("options", [{"prompt_policy": "unknown"}, {"max_tokens": 0}])
def test_invalid_prompt_configuration_fails_before_provider_request(options) -> None:
    with pytest.raises(ValueError):
        AnthropicJudge(api_key="test", **options)
