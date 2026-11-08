"""A family is paid and cached once after the protected pass, never as a clique of pairs."""

import json

import pytest

from dry_lint.baseline import require_complete
from dry_lint.discovery import CampaignStore
from dry_lint.family_discovery import FamilyBackend, FamilyDiscovery
from dry_lint.family_models import FamilyResponse, FamilyUsage
from dry_lint.judges.anthropic_family import family_prompt
from dry_lint.judging import Judging
from dry_lint.models import Run
from dry_lint.report import Report, as_check_run, as_json, as_markdown, as_text
from dry_lint.settings import FamilyDiscovery as FamilyConfiguration

from conftest import coverage_pair
from test_discovery import setup  # noqa: F401
from test_family_judging import family_answer
from test_operation_families import owners


class RecordedFamily:
    name = "test-family"
    version = "grounded-test-v1"
    model = "claude-haiku-5-5"
    max_tokens = 256
    available = True

    def __init__(self, *, fail=False):
        self.calls = []
        self.fail = fail

    def input_text(self, request):
        return family_prompt(request)

    def judge_family(self, request):
        self.calls.append(request.key)
        return FamilyResponse(
            text="bad json" if self.fail else family_answer(request).model_dump_json(),
            usage=FamilyUsage(input=100, output=50),
        )


def configured(setup, tmp_path, monkeypatch, *, fail=False):
    settings, primary, store, primary_calls = setup
    settings.discovery.families = FamilyConfiguration(judge="test-family")
    functions = owners()
    run = Run(repository="owner/repo", session="family-feature", revision="tree1")
    discovery = FamilyDiscovery(functions, [functions[0]], run, settings.discovery.families)
    assert len(discovery.requests) == 1
    family_judge = RecordedFamily(fail=fail)
    monkeypatch.setattr("dry_lint.family_discovery.load", lambda *_: family_judge)
    judging = Judging(settings, primary, None, store)
    judging.campaign = CampaignStore(tmp_path / "campaign.sqlite3", run)
    judging.family_recovery = discovery
    return settings, judging, discovery, family_judge, primary_calls, run


def test_real_protected_pass_then_one_family_question_and_exact_cache(setup, tmp_path, monkeypatch):
    settings, judging, discovery, judge, primary_calls, run = configured(setup, tmp_path, monkeypatch)
    pair = coverage_pair(1)
    findings = judging.findings([pair], run)
    state = judging.campaign.snapshot()
    assert findings[0].verdict is not None and len(primary_calls) == 1
    assert len(judge.calls) == 1 and len(state.attempts) == 2
    assert not state.attempts[0].residual and state.attempts[1].residual
    assert state.attempts[1].source_evidence.startswith("family:")
    assert state.attempts[1].usd == pytest.approx(0.000035)
    assert state.credit == pytest.approx(settings.discovery.exploration_per_revision)
    assert discovery.findings[0].reported
    # Family bytes have a separate physical namespace; pair enumeration cannot parse them as pair verdicts.
    assert len(list(judging.store.records())) == 1
    assert len(list(FamilyBackend(judging.store).keys())) == 1
    repeated = judging.findings([pair], run)
    assert repeated[0].cached and discovery.findings[0].status == "cached"
    assert len(judge.calls) == 1 and len(primary_calls) == 1
    assert judging.campaign.snapshot().usd == state.usd


def test_failure_accounts_usage_and_blocks_following_recovery(setup, tmp_path, monkeypatch):
    _, judging, discovery, judge, _, run = configured(setup, tmp_path, monkeypatch, fail=True)
    judging.findings([coverage_pair(1)], run)
    state = judging.campaign.snapshot()
    assert state.attempts[-1].status == "failed"
    assert state.attempts[-1].usd == pytest.approx(0.000035)
    assert discovery.findings[0].status == "failed" and not discovery.findings[0].reported
    judging.findings([coverage_pair(1)], run)
    assert len(judge.calls) == 1 and discovery.findings[0].status == "deferred"


@pytest.mark.parametrize("barrier", ["dollars", "calls", "exploration", "inflight"])
def test_cold_blocked_phase_does_not_construct_family_plugin(setup, tmp_path, monkeypatch, barrier):
    settings, judging, discovery, judge, _, run = configured(setup, tmp_path, monkeypatch)
    judging.campaign.advance(settings)
    if barrier == "dollars":
        judging.campaign.advance(settings, settings.budget.usd)
    elif barrier == "calls":
        settings.discovery.calls = 1
        judging.family_recovery = None
        judging.findings([coverage_pair(1)], run)
    elif barrier == "exploration":
        settings.discovery.exploration_calls_per_revision = 0
    else:
        from dry_lint.discovery import Attempt

        with judging.campaign.transaction() as state:
            state.attempts.append(Attempt(revision=run.revision, evidence="pending", lane="exploration", query="q", usd=0.001))
    monkeypatch.setattr("dry_lint.family_discovery.load", lambda *_: pytest.fail("Blocked phase loaded a plugin"))
    discovery(judging, [], run)
    assert not judge.calls
    assert discovery.findings[0].status in {"budget", "deferred"}


def test_no_primary_judge_lists_unconfirmed_families_without_provider(setup, tmp_path, monkeypatch):
    _, judging, discovery, _, _, run = configured(setup, tmp_path, monkeypatch)
    judging.judge = None
    monkeypatch.setattr("dry_lint.family_discovery.load", lambda *_: pytest.fail("No-judge path loaded plugin"))
    judging.findings([coverage_pair(1)], run)
    assert discovery.findings[0].status == "unjudged" and not discovery.findings[0].reported
    assert not judging.campaign.snapshot().attempts


def test_family_output_is_one_proposal_with_unknown_sibling_and_neutral_check(setup, tmp_path, monkeypatch):
    settings, judging, discovery, _, _, run = configured(setup, tmp_path, monkeypatch)
    judging.findings([], run)
    report = Report(run=run, judge=judging.name, judging=judging.summary(), families=discovery.findings)
    output = json.loads(as_check_run(report))
    assert output["conclusion"] == "neutral" and "1 family proposal(s)" in output["output"]["title"]
    assert "Additional unconfirmed siblings" in as_markdown(report)
    assert "Operation families" in as_text(report)
    assert Report.model_validate_json(as_json(report)).families[0].reported
    assert not report.findings
    with pytest.raises(ValueError, match="Operation-family judging is incomplete"):
        require_complete(report)


@pytest.mark.parametrize("cost", [-1, float("inf"), float("nan")])
def test_family_reservation_rejects_invalid_cost_without_touching_ledger(setup, tmp_path, monkeypatch, cost):
    settings, judging, _, _, _, _ = configured(setup, tmp_path, monkeypatch)
    judging.campaign.advance(settings)
    with pytest.raises(ValueError, match="finite nonnegative"):
        judging.campaign.reserve_family("key", "source", "owner", settings, cost)
    assert not judging.campaign.snapshot().attempts
