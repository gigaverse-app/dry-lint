"""Independent integration regressions: native shared admission and no live providers."""

import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from test_discovery import setup as setup
from test_family_discovery import configured
from test_family_judging import family_answer
from test_operation_families import OPERATION

from dry_lint import family_discovery as family_module
from dry_lint import judging as judging_module
from dry_lint.baseline import require_complete
from dry_lint.cli import main
from dry_lint.discovery import CampaignStore
from dry_lint.family_models import FamilyAnswer, FamilyResponse, MemberAssessment
from dry_lint.judging import Judging
from dry_lint.plugins import identity, load
from dry_lint.report import Report, as_check_run, as_markdown, as_text, render
from dry_lint.settings import PluginChoice, Settings
from dry_lint.store import DirectoryStore, VerdictStore

from conftest import claude, coverage_pair


def test_cache_read_failure_is_unconfirmed_without_call_or_new_charge(setup, tmp_path, monkeypatch):
    _, judging, discovery, judge, _, run = configured(setup, tmp_path, monkeypatch)
    with patch.object(family_module.FamilyBackend, "get", side_effect=OSError("private cache detail")):
        prefix = judging.findings([coverage_pair(1)], run)
    assert prefix[0].verdict is not None
    assert discovery.findings[0].status == "failed"
    assert discovery.findings[0].error == "OSError"
    assert not judge.calls and len(judging.campaign.snapshot().attempts) == 1


def test_cache_write_failure_settles_actual_usage_and_blocks_retry(setup, tmp_path, monkeypatch):
    _, judging, discovery, judge, _, run = configured(setup, tmp_path, monkeypatch)
    with patch.object(family_module.FamilyBackend, "put", side_effect=OSError("private cache detail")):
        judging.findings([], run)
    first = judging.campaign.snapshot()
    assert first.attempts[0].status == "failed" and first.usd == pytest.approx(0.000035)
    assert discovery.findings[0].status == "failed" and discovery.findings[0].response is not None
    judging.findings([], run)
    assert judging.campaign.snapshot() == first and len(judge.calls) == 1


def test_cached_only_run_identifies_family_judge_and_zero_charge(setup, tmp_path, monkeypatch):
    settings, judging, discovery, judge, _, run = configured(setup, tmp_path, monkeypatch)
    judging.findings([], run)
    again = Judging(settings, judging.judge, None, judging.store)
    again.campaign = judging.campaign
    again.family_recovery = discovery
    settings.budget.usd = judging.campaign.snapshot().usd
    again.findings([], run)
    assert discovery.findings[0].status == "cached" and len(judge.calls) == 1
    spend = next(s for s in again.summary().spend if s.judge == identity(judge))
    assert spend.calls == 0 and spend.usd == 0
    assert identity(judge) in again.summary().line()


def test_family_clients_close_after_success_and_cache_error(setup, tmp_path, monkeypatch):
    _, judging, _, judge, _, run = configured(setup, tmp_path, monkeypatch)
    closed = []
    monkeypatch.setattr(judge, "close", lambda: closed.append(True), raising=False)
    judging.findings([], run)
    assert closed == [True]
    with patch.object(family_module.FamilyBackend, "get", side_effect=OSError("cache")):
        judging.findings([], run)
    assert closed == [True, True]


def test_unknown_sibling_is_unresolved_even_in_separate_answer(setup, tmp_path, monkeypatch):
    settings, judging, discovery, judge, _, run = configured(setup, tmp_path, monkeypatch)

    def answer(request):
        payload = FamilyAnswer(
            decision="separate",
            reason="No established common policy",
            members=[
                MemberAssessment(
                    owner_id=m.owner_id, status="unknown" if i == 0 else "rejected", reason="Limited evidence"
                )
                for i, m in enumerate(request.members)
            ],
        )
        return FamilyResponse(text=payload.model_dump_json(), stop_reason="end_turn")

    monkeypatch.setattr(judge, "judge_family", answer)
    judging.findings([], run)
    report = Report(judge=judging.name, families=discovery.findings)
    body = json.loads(as_check_run(report))
    assert body["conclusion"] == "neutral" and "1 unresolved" in body["output"]["title"]
    with pytest.raises(ValueError, match="Operation-family judging is incomplete"):
        require_complete(report)


def test_excluded_family_is_visible_and_cannot_claim_complete():
    report = Report(
        judge="test", family_exclusions=[{"nomination_id": "oversized", "reason": "Full source exceeds bound <script>"}]
    )
    assert "oversized" in as_text(report) and "Full source exceeds bound" in as_markdown(report)
    assert "<script>" not in as_markdown(report)
    body = json.loads(as_check_run(report))
    assert body["conclusion"] == "neutral" and "1 unresolved" in body["output"]["title"]
    with pytest.raises(ValueError, match="Operation-family judging is incomplete"):
        require_complete(report)


@pytest.mark.parametrize("mode", ["github", "sarif"])
def test_unsupported_family_renderer_rejected_before_any_plugin(repo, monkeypatch, mode):
    repo.write(
        ".dry-lint.toml",
        'preset="balanced"\n[discovery.families]\njudge={use="anthropic-family",model="claude-haiku-5-5"}\n',
    )
    repo.commit("family opt-in")
    with patch.object(judging_module, "make_judge", side_effect=AssertionError("must validate before plugin")):
        assert main(["check", "--root", str(repo.root), "--base", "main", "--format", mode]) == 2


@pytest.mark.parametrize("policy", ["ignore", "distinct", "pattern"])
def test_cli_family_preserves_applicable_human_suppressions(repo, tmp_path, monkeypatch, policy):
    config = 'preset="none"\n[discovery]\nenabled=true\n[discovery.families]\njudge={use="anthropic-family",model="claude-haiku-5-5"}\n'
    if policy == "pattern":
        config += '\n[[patterns]]\nmembers="jobs/*.py::*"\nreason="separate lifecycles"\n'
    repo.write(".dry-lint.toml", config)
    for i in range(3):
        comment = ""
        if i == 0 and policy == "ignore":
            comment = "    # dry-lint: ignore\n"
        if i == 0 and policy == "distinct":
            comment = "    # dry-lint: distinct-from jobs/1.py::job1\n"
        repo.write(f"jobs/{i}.py", f"def job{i}(codec, payload):\n{comment}{OPERATION}")
    repo.commit("family with human suppression")
    target = tmp_path / "report.json"
    with patch.object(family_module, "load", side_effect=AssertionError("no main judge")):
        assert main(["check", "--root", str(repo.root), "--base", "main", "--report", str(target)]) == 0
    report = Report.model_validate_json(target.read_text())
    assert not report.families
    assert report.family_exclusions and "rule" in report.family_exclusions[0]["reason"]


def test_concurrent_pair_and_family_reservations_share_last_dollars(setup, tmp_path, monkeypatch):
    settings, judging, discovery, judge, _, run = configured(setup, tmp_path, monkeypatch)
    settings.budget.usd = 0.0015
    judging.campaign.advance(settings)
    path = judging.campaign.path
    request = discovery.requests[0][1]

    def reserve(family):
        campaign = CampaignStore(path, run)
        if family:
            return campaign.reserve_family("family-key", request.key, "owner", settings, 0.001)
        return campaign.reserve(coverage_pair(1), judging.judge, settings, 0.001)

    with ThreadPoolExecutor(2) as pool:
        result = list(pool.map(reserve, [False, True]))
    assert sum(isinstance(a, int) for a in result) == 1
    assert judging.campaign.snapshot().usd == 0.001


@pytest.mark.parametrize("limit", ["revision", "campaign", "exploration", "max", "subscription"])
def test_family_obeys_all_shared_call_limits(setup, tmp_path, monkeypatch, limit):
    settings, judging, discovery, judge, _, run = configured(setup, tmp_path, monkeypatch)
    judging.campaign.advance(settings)
    if limit == "revision":
        settings.discovery.calls_per_revision = 1
    elif limit == "campaign":
        settings.discovery.calls = 1
    elif limit == "exploration":
        settings.discovery.exploration_calls_per_revision = 1
    elif limit == "max":
        settings.max_judgements = 1
    else:
        settings.budget.subscription_calls = 1
    first = judging.campaign.reserve_family("one", "source1", "owner", settings, 0.001, subscription=True)
    assert isinstance(first, int)
    judging.campaign.settle(first, 0.000035, True)
    assert judging.campaign.reserve_family("two", "source2", "other", settings, 0.001, subscription=True) is None
    assert len(judging.campaign.snapshot().attempts) == 1


def test_complete_protected_requests_and_reservations_match_without_family(setup, tmp_path, monkeypatch):
    settings, treatment, _, family_judge, calls, run = configured(setup, tmp_path, monkeypatch)
    control = Judging(settings, treatment.judge, None, VerdictStore(DirectoryStore(tmp_path / "control-store")))
    control.campaign = CampaignStore(tmp_path / "control.sqlite3", run)
    pairs = [coverage_pair(1), coverage_pair(2).model_copy(update={"lane": "exploration"}), coverage_pair(3)]
    original = control.findings(pairs, run)
    prefix_attempts = control.campaign.snapshot().attempts
    prefix_requests = [call.content for call in calls]
    calls.clear()
    protected = treatment.findings(pairs, run)
    assert protected == original
    assert [call.content for call in calls] == prefix_requests
    assert treatment.campaign.snapshot().attempts[: len(prefix_attempts)] == prefix_attempts
    assert len(family_judge.calls) == 1


@pytest.mark.parametrize("command", ["detect", "judge", "scan", "sweep"])
def test_unsupported_campaign_modes_reject_before_loading_judge(repo, command):
    repo.write(
        ".dry-lint.toml",
        'preset="balanced"\n[discovery.families]\njudge={use="anthropic-family",model="claude-haiku-5-5"}\n',
    )
    repo.commit("family opt-in")
    args = [command, "--root", str(repo.root)]
    if command == "judge":
        args += ["--candidates", "missing.json"]
    with patch.object(judging_module, "make_judge", side_effect=AssertionError("unsupported before plugin")):
        assert main(args) == 2


@pytest.mark.parametrize("has_key", [False, True])
def test_native_family_uses_actual_plugin_contract_without_provider(setup, tmp_path, monkeypatch, has_key):
    settings, judging, discovery, _, _, run = configured(setup, tmp_path, monkeypatch)
    request = discovery.requests[0][1]
    requests = []
    settings.discovery.families.judge = PluginChoice(
        use="anthropic-family",
        model="claude-haiku-5-5",
        max_tokens=2048,
        api_key="test" if has_key else "",
        http_client=claude(
            {
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": family_answer(request).model_dump_json()}],
            },
            requests,
        ),
    )
    monkeypatch.setattr(family_module, "load", load)
    judging.findings([], run)
    if has_key:
        assert discovery.findings[0].reported and len(requests) == 1
        assert discovery.findings[0].charged_usd == pytest.approx(0.00015)
        body = json.loads(requests[0].content)
        assert body["max_tokens"] == 2048 and "fallbacks" not in body
    else:
        assert discovery.findings[0].status == "no_key" and not requests
        assert not judging.campaign.snapshot().attempts
    assert "anthropic-family" in judging.summary().line()


def test_family_opt_in_without_native_discovery_is_rejected_before_any_plugin(repo, capsys):
    repo.write(".dry-lint.toml", '[discovery.families]\njudge={use="anthropic-family",model="claude-haiku-5-5"}\n')
    repo.commit("family opt-in without discovery")
    with patch.object(judging_module, "make_judge", side_effect=AssertionError("must validate before plugin")):
        assert main(["check", "--root", str(repo.root), "--base", "main"]) == 2
    assert "requires discovery.enabled = true" in capsys.readouterr().err


@pytest.mark.parametrize("form", ["github", "sarif"])
def test_a_report_with_families_refuses_formats_that_cannot_show_them(form):
    report = Report(judge="test", family_exclusions=[{"nomination_id": "n", "reason": "oversized"}])
    with pytest.raises(ValueError, match="Operation families support"):
        render(report, form, Settings())
