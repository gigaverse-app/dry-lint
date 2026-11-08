"""A family is paid and cached once after the protected pass, never as a clique of pairs."""

import json
from types import SimpleNamespace

import pytest
from test_discovery import setup as setup
from test_family_judging import family_answer, family_request
from test_operation_families import OPERATION, owners

from dry_lint.baseline import require_complete
from dry_lint.costs import Ledger
from dry_lint.discovery import CampaignStore
from dry_lint.family_discovery import (
    BudgetFamilyAdmission,
    CampaignFamilyAdmission,
    FamilyBackend,
    FamilyDiscovery,
)
from dry_lint.family_models import FamilyResponse, FamilyUsage
from dry_lint.judges.anthropic_family import family_prompt
from dry_lint.judging import Judging
from dry_lint.models import Run
from dry_lint.plugins import identity
from dry_lint.report import Report, as_check_run, as_json, as_markdown, as_text
from dry_lint.settings import FamilyDiscovery as FamilyConfiguration

from conftest import coverage_pair


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
            stop_reason="end_turn",
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
            state.attempts.append(
                Attempt(revision=run.revision, evidence="pending", lane="exploration", query="q", usd=0.001)
            )
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


def test_a_campaign_budget_refusal_counts_as_skipped():
    request = family_request()
    judge = RecordedFamily()
    campaign = SimpleNamespace(reserve_family=lambda *args, **kwargs: "budget")
    judging = SimpleNamespace(campaign=campaign, settings=None, ledger=SimpleNamespace(spend={}))
    assert CampaignFamilyAdmission(judging).reserve(request, judge, 0.01) == "budget"
    assert judging.ledger.spend[identity(judge)].skipped == 1


def test_scan_admission_holds_each_question_against_the_pair_budget_and_settles_actual_usage(setup):
    settings, *_ = setup
    settings.budget.usd, settings.budget.subscription_calls = 0.30, 1
    judging = SimpleNamespace(settings=settings, ledger=Ledger(settings, spent=0.05))
    admission = BudgetFamilyAdmission(judging)
    request, judge = family_request(), RecordedFamily()
    first = admission.reserve(request, judge, 0.20)
    # The held reservation counts: a second 0.20 question no longer fits 0.30 - 0.05 spent.
    assert admission.reserve(request, judge, 0.20) == "budget"
    assert admission.settle(first, 0.12, True) == 0.12
    assert admission.reserve(request, judge, 0.10) is not None
    unknown = admission.reserve(request, judge, 0.01)
    assert admission.settle(unknown, None, False) == 0.01  # unknown usage keeps the reservation charged
    spend = judging.ledger.spend[identity(judge)]
    assert (spend.calls, spend.skipped, spend.failed) == (2, 1, 1)
    subscription = RecordedFamily()
    subscription.subscription = True
    assert BudgetFamilyAdmission(judging).reserve(request, subscription, 0.0) is not None
    capped = BudgetFamilyAdmission(judging)
    capped.held[1] = 0.0
    assert capped.reserve(request, subscription, 0.0) is None  # the subscription call cap is shared too


def test_an_unrepresentable_nomination_is_a_visible_exclusion(setup, monkeypatch):
    settings, *_ = setup
    settings.discovery.families = FamilyConfiguration(judge="test-family")
    functions = owners()

    def oversized(nomination):
        raise ValueError("Owner source exceeds the bounded full-function contract")

    monkeypatch.setattr("dry_lint.family_discovery.request_from_nomination", oversized)
    discovery = FamilyDiscovery(functions, [functions[0]], Run(), settings.discovery.families)
    assert not discovery.requests and not discovery.findings
    assert discovery.rejected[0]["reason"] == "Owner source exceeds the bounded full-function contract"
    discovery(SimpleNamespace(judge=object()), [], Run())
    assert not discovery.findings


def test_a_deferred_protected_baseline_question_runs_no_family(setup, tmp_path, monkeypatch):
    _, judging, discovery, judge, _, run = configured(setup, tmp_path, monkeypatch)
    deferred = SimpleNamespace(deferred=True, candidate=SimpleNamespace(lane="baseline"))
    monkeypatch.setattr("dry_lint.family_discovery.load", lambda *_: pytest.fail("Deferred baseline loaded a plugin"))
    discovery(judging, [deferred], run)
    assert not judge.calls and discovery.findings[0].status == "unjudged"


def test_an_unloadable_family_judge_fails_every_question_without_a_call(setup, tmp_path, monkeypatch):
    settings, judging, discovery, judge, _, run = configured(setup, tmp_path, monkeypatch)
    judging.campaign.advance(settings)

    def missing(*_):
        raise ImportError("anthropic is not installed")

    monkeypatch.setattr("dry_lint.family_discovery.load", missing)
    discovery(judging, [], run)
    assert [(finding.status, finding.error) for finding in discovery.findings] == [("failed", "ImportError")]


@pytest.mark.parametrize("defect", ["not a family judge", "unpriced"])
def test_a_misconfigured_family_judge_is_rejected_and_closed(setup, tmp_path, monkeypatch, defect):
    settings, judging, discovery, judge, _, run = configured(setup, tmp_path, monkeypatch)
    judging.campaign.advance(settings)
    closed = []
    plugin = SimpleNamespace(close=lambda: closed.append(True))
    if defect == "unpriced":
        plugin = judge
        judge.close = lambda: closed.append(True)
        monkeypatch.setattr("dry_lint.family_discovery.price", lambda *_: None)
    monkeypatch.setattr("dry_lint.family_discovery.load", lambda *_: plugin)
    with pytest.raises(ValueError, match="family judging|model prices"):
        discovery(judging, [], run)
    assert closed == [True] and not judge.calls


def test_an_unpriceable_prompt_is_deferred_and_questions_beyond_the_cap_wait(setup, tmp_path, monkeypatch):
    settings, judging, _, judge, _, run = configured(setup, tmp_path, monkeypatch)
    settings.discovery.families = FamilyConfiguration(judge="test-family", max_questions=1)
    functions = owners() + owners(OPERATION.replace("decode", "parse"), prefix="parser")
    discovery = FamilyDiscovery(functions, [functions[0], functions[3]], run, settings.discovery.families)
    assert len(discovery.requests) == 2
    judging.family_recovery = discovery
    judging.campaign.advance(settings)
    discovery(judging, [], run)
    assert sorted(finding.status for finding in discovery.findings) == ["answered", "deferred"]
    judge.max_tokens = 0
    discovery(judging, [], run)
    assert {finding.error for finding in discovery.findings} == {
        "Family prompt exceeds the configured complete-source bound"
    }


@pytest.mark.parametrize("barrier", ["no opt-in", "unadvanced", "inflight", "repeat", "budget"])
def test_family_reservation_obeys_opt_in_phase_repeat_and_budget(setup, tmp_path, monkeypatch, barrier):
    settings, judging, _, _, _, _ = configured(setup, tmp_path, monkeypatch)
    campaign = judging.campaign
    if barrier == "no opt-in":
        settings.discovery.families = None
        with pytest.raises(ValueError, match="explicit native discovery opt-in"):
            campaign.reserve_family("key", "source", "owner", settings, 0.0)
        return
    if barrier == "unadvanced":
        with pytest.raises(ValueError, match="protected campaign phase"):
            campaign.reserve_family("key", "source", "owner", settings, 0.0)
        return
    campaign.advance(settings)
    if barrier == "inflight":
        from dry_lint.discovery import Attempt

        with campaign.transaction() as state:
            state.attempts.append(
                Attempt(revision=campaign.revision, evidence="pending", lane="exploration", query="q", usd=0.001)
            )
        assert campaign.reserve_family("key", "source", "owner", settings, 0.0) is None
    elif barrier == "repeat":
        reservation = campaign.reserve_family("key", "source", "owner", settings, 0.0)
        campaign.settle(reservation, 0.0, True)
        assert campaign.reserve_family("other", "source", "owner", settings, 0.0) is None
    else:
        assert campaign.reserve_family("key", "source", "owner", settings, settings.budget.usd * 2) == "budget"


@pytest.mark.parametrize("budget", [0.04, 0.0])
def test_scan_judges_families_after_the_pair_pass_within_the_same_budget(setup, tmp_path, monkeypatch, budget):
    settings, judging, discovery, judge, _, run = configured(setup, tmp_path, monkeypatch)
    judging.campaign = None  # `scan`: no change campaign
    settings.budget.usd = budget
    judging.findings([], run)
    if budget:
        assert [finding.status for finding in discovery.findings] == ["answered"] and len(judge.calls) == 1
        assert judging.ledger.spend[f"{judge.name}:{judge.version}"].calls == 1
    else:
        assert [finding.status for finding in discovery.findings] == ["budget"] and not judge.calls


def test_scan_runs_no_family_when_the_budget_deferred_a_pair(setup, tmp_path, monkeypatch):
    _, judging, discovery, judge, _, run = configured(setup, tmp_path, monkeypatch)
    judging.campaign = None
    deferred = SimpleNamespace(budget_deferred=True)
    monkeypatch.setattr("dry_lint.family_discovery.load", lambda *_: pytest.fail("Deferred pairs loaded a plugin"))
    discovery(judging, [deferred], run)
    assert [finding.status for finding in discovery.findings] == ["budget"] and not judge.calls
