"""Recovery-only policies through native plugins, real storage and offline provider transport."""

import hashlib
import json
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest
from test_discovery import check
from test_discovery import setup as setup

from dry_lint import judging as judging_module
from dry_lint.costs import judging_input, usage_cost
from dry_lint.discovery import Attempt, Campaign, CampaignStore, reservation_cost
from dry_lint.judges.anthropic import AnthropicJudge
from dry_lint.judges.command import PROMPT_POLICIES, prompt
from dry_lint.judges.grounded import DIGEST, POLICY, PROMPT_VERSION, TEMPLATE
from dry_lint.judging import Judging
from dry_lint.models import Run, evidence
from dry_lint.plugins import identity, load
from dry_lint.presets import resolve
from dry_lint.report import Report
from dry_lint.settings import ExplorationComparer, PluginChoice, Settings
from dry_lint.store import DirectoryStore, VerdictStore

from conftest import claude, coverage_pair, residual_pair

MEASURED_DIGEST = "bcec108a5d1c316c1557a12434b14c209fb1899b277da83b26ac5de5346933a1"
MEASURED_VERSION = "dry-grounded-claim-v1-bcec108a5d1c316c:claude-haiku-5-5:output=2048"
ANSWER = {"stop_reason": "end_turn", "content": [{"type": "text", "text": '{"label":"duplicate","score":0.8}'}]}


def recovery_choice(**options):
    return PluginChoice(
        use="anthropic",
        **{
            "model": "claude-haiku-5-5",
            "prompt_policy": POLICY,
            "max_tokens": 2048,
            "max_retries": 0,
            "retry_malformed": False,
            **options,
        },
    )


@pytest.fixture
def configured(setup):
    settings, judge, store, calls = setup
    settings.discovery.residual_comparers = [ExplorationComparer(use="tfidf", neighbours=100)]
    settings.discovery.residual_judge = recovery_choice()
    return settings, judge, store, calls


@pytest.fixture
def recovery_http(monkeypatch):
    """Inject only the external SDK client; production plugin loading stays real."""
    requests = []
    client = claude(ANSWER, requests)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    original = AnthropicJudge.__init__

    def initialize(self, **kwargs):
        original(self, http_client=client, **kwargs)

    with patch.object(AnthropicJudge, "__init__", initialize):
        yield requests


def test_frozen_policy_and_real_plugin_identity():
    assert hashlib.sha256(TEMPLATE.encode()).hexdigest() == DIGEST == MEASURED_DIGEST
    assert POLICY == "shared-operations-grounded-claim-v1"
    assert PROMPT_POLICIES[POLICY] == (PROMPT_VERSION, TEMPLATE)
    requests = []
    judge = load("judges", recovery_choice(api_key="test", http_client=claude(ANSWER, requests)))
    assert judge.version == MEASURED_VERSION and judge.strict_version
    pair = coverage_pair(1)
    verdict = judge.judge([pair], Settings())[0]
    body = json.loads(requests[0].content)
    assert len(requests) == 1 and "fallbacks" not in body
    assert body["max_tokens"] == 2048 and body["model"] == "claude-haiku-5-5"
    assert body["messages"][0]["content"] == judging_input(judge, pair) == prompt(pair, policy=POLICY)
    assert verdict.judge_version == MEASURED_VERSION


def test_complete_prefix_then_grounded_recovery_repeats_without_second_call(configured, recovery_http, tmp_path):
    settings, judge, store, original_calls = configured
    baseline = coverage_pair(1)
    exploration = coverage_pair(2).model_copy(update={"lane": "exploration"})
    pending = coverage_pair(4).model_copy(update={"lane": "exploration"})
    settings.discovery.exploration_per_revision = reservation_cost(judge, exploration, settings)
    control = settings.model_copy(deep=True)
    control.discovery.residual_comparers = []
    control.discovery.residual_judge = None
    protected, before = check(
        (control, judge, VerdictStore(DirectoryStore(tmp_path / "control-verdicts")), original_calls),
        tmp_path / "control",
        [baseline, exploration, pending],
    )
    control_requests = [r.content for r in original_calls]
    original_calls.clear()
    pairs = [residual_pair(3), pending, exploration, baseline]
    report, state = check(configured, tmp_path / "treatment", pairs)
    assert [r.content for r in original_calls] == control_requests
    assert state.attempts[: len(before.attempts)] == before.attempts
    assert len(original_calls) == 2 and len(recovery_http) == 2
    assert report.deferred == 0
    by_key = {f.candidate.key: f for f in report.findings}
    for finding in protected.findings:
        if finding.verdict:
            # Family counts describe the expanded report; protected questions/verdicts and decisions stay exact.
            assert by_key[finding.candidate.key].model_dump(exclude={"family"}) == finding.model_dump(
                exclude={"family"}
            )
    assert {s.judge for s in report.judging.spend} == {identity(judge), f"anthropic-operations:{MEASURED_VERSION}"}
    assert Report.model_validate_json(report.model_dump_json()).model_dump() == report.model_dump()
    assert MEASURED_VERSION in report.judging.line() and judge.version in report.judging.line()
    assert Campaign.model_validate_json(state.model_dump_json()) == state
    again, repeated = check(configured, tmp_path / "treatment", pairs)
    assert all(f.cached for f in again.findings)
    assert len(original_calls) == len(recovery_http) == 2 and repeated == state
    # A new revision can fund its own protected pass; grounded cached output cannot answer it.
    settings.discovery.exploration_per_revision = 0.04
    later, _ = check(configured, tmp_path / "treatment", pairs, "tree2")
    assert next(f for f in later.findings if f.candidate.key == pending.key).verdict.judge_version == judge.version
    assert len(original_calls) == 3


def test_same_name_versions_keep_both_cache_slots_and_rollback(configured, recovery_http, tmp_path):
    settings, judge, store, calls = configured
    pair = residual_pair(3)
    # Original-policy answer already exists; it must neither satisfy nor be overwritten by recovery.
    original = judge.judge([pair], settings)[0]
    store.remember(pair, original)
    report, _ = check(configured, tmp_path, [pair])
    found = report.findings[0]
    assert found.verdict.judge == original.judge
    assert found.verdict.judge_version != original.judge_version and not found.cached
    assert store.lookup(pair, judge.name, 0, frozenset({judge.version}), exact_source=True).verdict == original
    scoped = store.scoped(f"residual:anthropic-operations:{MEASURED_VERSION}")
    assert scoped.lookup(pair, judge.name, 0, frozenset({MEASURED_VERSION}), exact_source=True).verdict == found.verdict
    assert scoped.lookup(pair, judge.name, 0, frozenset({judge.version}), exact_source=True).verdict is None
    assert [r.verdict for r in store.records()] == [original]
    assert [r.verdict for r in scoped.records()] == [found.verdict]
    # Removing only the optional judge retains PR #122's original cache identity.
    settings.discovery.residual_judge = None
    rollback, _ = check(configured, tmp_path, [pair])
    assert rollback.findings[0].cached and rollback.findings[0].verdict == original
    assert len(calls) == len(recovery_http) == 1


@pytest.mark.parametrize("main", ["none", "auto"])
def test_no_main_judge_does_not_load_recovery(configured, monkeypatch, main):
    settings, _, store, _ = configured
    monkeypatch.delenv("TYPESAFE_AI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    settings.judge = PluginChoice(use=main)
    with patch.object(judging_module, "load", side_effect=AssertionError("must stay lazy")):
        judging = Judging.configured(settings, store)
        assert judging.findings([residual_pair(3)])[0].verdict is None


@pytest.mark.parametrize(
    "barrier", ["empty", "dollars", "revision", "campaign", "max", "exploration", "pending", "failed", "reserved"]
)
def test_unrunnable_recovery_never_loads_plugin(configured, tmp_path, barrier):
    settings, judge, store, calls = configured
    run = Run(session="feature", revision="tree1")
    judging = Judging(settings, judge, None, store)
    judging.campaign = CampaignStore(tmp_path / "campaign.sqlite3", run)
    pairs = [] if barrier == "empty" else [residual_pair(3)]
    if barrier in {"dollars", "pending"}:
        settings.budget.usd = 0
        if barrier == "pending":
            pairs.insert(0, coverage_pair(1))
    elif barrier == "exploration":
        settings.discovery.exploration_calls_per_revision = 0
    elif barrier != "empty":
        reservation = judging.campaign.reserve(coverage_pair(1), judge, settings, 0.001)
        if barrier != "reserved":
            judging.campaign.settle(reservation, None, barrier != "failed")
        if barrier == "revision":
            settings.discovery.calls_per_revision = 1
        elif barrier == "campaign":
            settings.discovery.calls = 1
        elif barrier == "max":
            settings.max_judgements = 1
    with patch.object(judging_module, "load", side_effect=AssertionError("must stay lazy")):
        findings = judging.findings(pairs, run)
    assert all(f.deferred for f in findings) and not calls


def test_selected_prices_prompt_output_and_usage_own_the_charge(configured, recovery_http, tmp_path):
    settings, judge, _, _ = configured
    settings.discovery.residual_judge = recovery_choice(model="custom-priced-model", max_tokens=317)
    settings.prices["custom-priced-model"] = (2.3, 4.7)
    pair = residual_pair(3)
    report, state = check(configured, tmp_path, [pair])
    request = json.loads(recovery_http[0].content)
    assert request["max_tokens"] == 317
    expected = usage_cost({"input": 900, "output": 120}, (2.3, 4.7))
    assert state.usd == report.judging.spend[-1].usd == pytest.approx(expected)
    actual = load("judges", settings.discovery.residual_judge)
    hold = usage_cost({"input": len(prompt(pair, policy=POLICY).encode()) + 1024, "output": 317}, (2.3, 4.7))
    assert reservation_cost(actual, pair, settings) == hold
    assert reservation_cost(judge, pair, settings) != hold
    settings.budget.usd = hold - 0.000001
    blocked, empty = check(configured, tmp_path / "unaffordable", [residual_pair(9)])
    assert blocked.deferred == 1 and not empty.attempts and len(recovery_http) == 1


@pytest.mark.parametrize("failure", ["provider", "malformed"])
def test_recovery_failure_holds_selected_charge_and_stops_retry(configured, tmp_path, monkeypatch, failure):
    settings, _, _, _ = configured
    calls = []
    response = (
        {"error": {"type": "overloaded_error", "message": "unavailable"}}
        if failure == "provider"
        else {"stop_reason": "end_turn", "content": [{"type": "text", "text": "not JSON"}]}
    )
    settings.discovery.residual_judge = recovery_choice(
        api_key="test", http_client=claude(response, calls, status=529 if failure == "provider" else 200)
    )
    pair = residual_pair(3)
    report, state = check(configured, tmp_path, [pair, residual_pair(4)])
    actual = load("judges", settings.discovery.residual_judge)
    expected = reservation_cost(actual, pair, settings) if failure == "provider" else 0.00015
    assert len(calls) == 1 and state.attempts[0].status == "failed"
    assert state.usd == pytest.approx(expected)
    assert report.judging.spend[-1].failed == 1 and report.deferred == 2
    again, repeated = check(configured, tmp_path, [pair, residual_pair(4)])
    assert len(calls) == 1 and repeated == state and again.deferred == 2


def test_cross_policy_concurrent_attempts_cannot_charge_same_source_twice(configured, tmp_path):
    settings, original, _, _ = configured
    recovery = load("judges", recovery_choice(api_key="test", http_client=claude(ANSWER, [])))
    run = Run(session="feature", revision="tree")
    path = tmp_path / "campaign.sqlite3"
    campaign = CampaignStore(path, run)
    pair = coverage_pair(1).model_copy(update={"lane": "exploration"})

    def reserve(item):
        judge, residual = item
        return CampaignStore(path, run).reserve(pair, judge, settings, 0.001, residual=residual)

    with ThreadPoolExecutor(2) as pool:
        attempts = list(pool.map(reserve, [(original, False), (recovery, True)]))
    assert sum(isinstance(a, int) for a in attempts) == 1
    assert campaign.snapshot().usd == 0.001
    attempt = next(a for a in attempts if isinstance(a, int))
    campaign.settle(attempt, None, True)
    assert campaign.reserve(pair, recovery, settings, 0.001, residual=True) is None
    assert campaign.snapshot().attempts[0].source_evidence == evidence(pair)
    assert campaign.snapshot().schema_version == 3


def test_config_round_trip_and_absent_defaults():
    old = resolve(Settings(preset="balanced"), {})
    assert old.discovery.residual_judge is None
    example = Path(__file__).resolve().parents[1] / "examples/grounded-residual-discovery.toml"
    settings = resolve(Settings.model_validate(tomllib.loads(example.read_text())), {})
    assert settings.discovery.comparers == old.discovery.comparers
    assert settings.judge == old.judge
    assert settings.discovery.residual_judge == recovery_choice()
    assert Settings.model_validate_json(settings.model_dump_json()) == settings
    for bad in ["auto", "none"]:
        with pytest.raises(ValueError, match="explicit judge"):
            Settings(discovery={"residual_comparers": ["tfidf"], "residual_judge": bad})
    with pytest.raises(ValueError, match="requires discovery.residual_comparers"):
        Settings(discovery={"residual_judge": "anthropic"})


def test_successful_recovery_cache_survives_later_failure_and_exhaustion(configured, tmp_path):
    settings, _, _, _ = configured
    calls = []
    settings.discovery.residual_judge = recovery_choice(
        api_key="test",
        http_client=claude([ANSWER, {"stop_reason": "end_turn", "content": [{"type": "text", "text": "bad"}]}], calls),
    )
    pairs = [residual_pair(3), residual_pair(4)]
    first, state = check(configured, tmp_path, pairs)
    answered = next(f for f in first.findings if f.verdict)
    assert len(calls) == 2 and first.deferred == 1
    settings.budget.usd = state.usd
    again, same = check(configured, tmp_path, pairs)
    assert next(f for f in again.findings if f.candidate.key == answered.candidate.key).cached
    assert again.deferred == 1 and same == state and len(calls) == 2


def test_selected_subscription_judge_shares_call_limit(configured, tmp_path):
    settings, judge, _, _ = configured
    settings.budget.subscription_calls = 1
    judge.subscription = True
    campaign = CampaignStore(tmp_path / "state.sqlite3", Run(session="branch", revision="tree"))
    first = campaign.reserve(coverage_pair(1), judge, settings, 0.001)
    campaign.settle(first, None, True)
    other = load("judges", recovery_choice(api_key="test", http_client=claude(ANSWER, [])))
    other.subscription = True
    assert campaign.reserve(residual_pair(3), other, settings, 0.001, residual=True) == "limit"
    assert campaign.snapshot().usd == 0.001 and len(campaign.snapshot().attempts) == 1


def test_old_attempt_without_source_evidence_still_blocks_cross_policy_recovery(configured, tmp_path):
    settings, judge, _, calls = configured
    pair = residual_pair(3)
    campaign = CampaignStore(
        tmp_path / "campaign.sqlite3", Run(repository="owner/repo", session="feature", revision="tree1")
    )
    # Schema 2 had the original judge in every attempt, but no judge-independent evidence field.
    with campaign.transaction() as state:
        state.attempts.append(
            Attempt(
                revision="tree1",
                evidence=evidence(pair, identity(judge)),
                lane="exploration",
                query=pair.new.qualname,
                usd=0.001,
                status="answered",
                residual=True,
            )
        )
    # No optional judge should ask the same old question again on this revision.
    with patch.object(judging_module, "load", side_effect=AssertionError("already attempted")):
        findings = Judging(settings, judge, None, configured[2])
        findings.campaign = campaign
        assert findings.findings([pair])[0].deferred


def test_explicit_same_judge_identity_reuses_its_recovery_cache(configured, recovery_http, tmp_path):
    settings, judge, _, calls = configured
    settings.discovery.residual_judge = settings.judge.model_copy(deep=True)
    settings.discovery.exploration_per_revision = 0
    pair = coverage_pair(1).model_copy(update={"lane": "exploration"})
    first, state = check(configured, tmp_path, [pair, residual_pair(3)])
    again, repeated = check(configured, tmp_path, [pair, residual_pair(3)])
    assert first.deferred == again.deferred == 0
    assert all(f.cached for f in again.findings)
    assert len(recovery_http) == 2 and not calls and repeated == state
