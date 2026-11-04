"""Paid discovery journeys use production admission and the real SDK with an HTTP fake."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from dry_lint.cli import main
from dry_lint.detector import Detector, changed_lines, touched
from dry_lint.discovery import CampaignStore, reservation_cost
from dry_lint.feedback import FILENAME, Feedback
from dry_lint.judges.anthropic import AnthropicJudge
from dry_lint.judging import Judging
from dry_lint.models import Run
from dry_lint.presets import resolve
from dry_lint.report import Report
from dry_lint.settings import Settings
from dry_lint.store import DirectoryStore, VerdictStore

from conftest import TWIN, claude, coverage_pair


@pytest.fixture
def setup(tmp_path):
    settings = resolve(Settings(preset="balanced"))
    requests = []
    judge = AnthropicJudge(api_key="test", http_client=claude({"stop_reason": "end_turn", "content": [
        {"type": "text", "text": '{"label":"duplicate","score":0.8}'}]}, requests), **settings.judge.options())
    store = VerdictStore(DirectoryStore(tmp_path / "verdicts"))
    return settings, judge, store, requests


def check(setup, tmp_path, candidates, revision="tree1"):
    settings, judge, store, _ = setup
    run = Run(repository="owner/repo", session="feature", revision=revision)
    judging = Judging(settings, judge, None, store)
    judging.campaign = CampaignStore(tmp_path / "campaign.sqlite3", run)
    findings = judging.findings(candidates, run)
    return Report.build(findings, settings, run=run, judging=judging.summary()), judging.campaign.snapshot()


def test_repeated_evidence_costs_nothing_but_changed_evidence_reopens(setup, tmp_path):
    pair = coverage_pair(1)
    first, state = check(setup, tmp_path, [pair])
    again, same = check(setup, tmp_path, [pair])
    assert first.findings[0].blocking and again.findings[0].cached
    assert state.usd == same.usd == pytest.approx(0.00015)
    edited = pair.model_copy(update={"new": pair.new.model_copy(update={"code": pair.new.code + "\n# new contract"})})
    changed, later = check(setup, tmp_path, [edited], "tree2")
    assert not changed.findings[0].cached and len(later.attempts) == 2
    assert later.usd == pytest.approx(state.usd * 2)


def test_exploration_is_paced_and_preserves_later_baseline(setup, tmp_path):
    settings, judge, store, calls = setup
    settings.discovery.exploration_calls_per_revision = 1
    settings.discovery.calls = 4
    pool = [coverage_pair(n).model_copy(update={"lane": "exploration"}) for n in range(6)]
    _, first = check(setup, tmp_path, pool)
    _, repeat = check(setup, tmp_path, pool)
    assert len(first.attempts) == len(repeat.attempts) == 1
    assert first.credit == repeat.credit
    late = coverage_pair(10)
    report, state = check(setup, tmp_path, [*pool, late], "tree2")
    assert any(f.candidate.key == late.key and f.blocking for f in report.findings)
    assert sum(a.lane == "exploration" for a in state.attempts) == 1
    assert state.usd <= settings.budget.usd


def test_atomic_reservations_and_abandoned_calls_stay_charged(setup, tmp_path):
    settings, judge, _, _ = setup
    settings.budget.usd = 0.004
    path = tmp_path / "ledger.sqlite3"
    run = Run(session="feature", revision="tree")
    CampaignStore(path, run)
    def reserve(n):
        return CampaignStore(path, run).reserve(coverage_pair(n), judge, settings, 0.003)
    with ThreadPoolExecutor(4) as pool:
        reservations = list(pool.map(reserve, range(4)))
    assert sum(r is not None for r in reservations) == 1
    # Reopening the DB after an abandoned provider call cannot reset its reservation.
    assert CampaignStore(path, run).snapshot().usd == 0.003
    assert CampaignStore(path, Run(session="another", revision="tree")).snapshot().usd == 0


def test_failed_answers_remain_unresolved_and_do_not_get_free_retries(setup, tmp_path):
    settings, judge, store, requests = setup
    judge.client = AnthropicJudge(api_key="test", http_client=claude({"stop_reason": "end_turn", "content": [
        {"type": "text", "text": 'not json'}]}, requests)).client
    pair = coverage_pair(1)
    report, state = check(setup, tmp_path, [pair])
    assert report.deferred == 1 and state.usd > 0
    assert state.attempts[0].status == "failed"
    _, repeat = check(setup, tmp_path, [pair])
    assert len(requests) == len(repeat.attempts) == 1
    _, retry = check(setup, tmp_path, [pair], "tree2")
    assert len(requests) == len(retry.attempts) == 2


def test_wider_retrieval_keeps_every_baseline_pair_and_its_order(repo):
    baseline = Detector.for_repository(repo.root, Settings())
    changed = touched(baseline.functions, changed_lines(repo.root, "main"))
    before = baseline.candidates(changed)
    settings = resolve(Settings(preset="balanced"))
    wider = Detector.for_repository(repo.root, settings).candidates(changed)
    assert before
    assert [c.model_dump() for c in wider if c.lane == "baseline"] == [c.model_dump() for c in before]


def test_cli_feedback_must_be_staged_and_changes_reopen_dismissals(repo, setup, tmp_path):
    settings, judge, _, requests = setup
    report_path = tmp_path / "report.json"
    repo.git("reset", "--soft", "main")
    args = ["check", "--root", str(repo.root), "--staged", "--preset", "balanced", "--report", str(report_path)]
    with patch("dry_lint.judging.make_judge", return_value=judge):
        assert main(args) == 1
        report = Report.model_validate_json(report_path.read_bytes())
        pair = report.findings[0].candidate.key
        feedback_args = ["feedback", "--root", str(repo.root), "--from", str(report_path),
                         "--reason", "Reviewed separate lifetime contracts", "--reviewer", "test-agent"]
        assert main([*feedback_args, "fix", pair]) == 2  # unchanged code is not a fix
        assert main([*feedback_args, "dismiss", pair]) == 0
        assert main(args) == 1  # an unstaged dismissal cannot clear staged source
        repo.git("add", FILENAME)
        assert main(args) == 0
        dismissed = Report.model_validate_json(report_path.read_bytes())
        assert dismissed.filtered and not dismissed.visible
        repo.write("src/widgets/caption.py", TWIN.replace("max_len - 1", "max_len - 2"))
        repo.git("add", "src/widgets/caption.py")
        assert main(args) == 1
        edited = Report.model_validate_json(report_path.read_bytes())
        assert any(not f.cached and f.blocking for f in edited.findings)
        repo.write("src/widgets/caption.py", "from src.text import shorten_text as preview_caption_text\n")
        repo.git("add", "src/widgets/caption.py")
        assert main([*feedback_args, "fix", edited.findings[0].candidate.key]) == 0
        assert Feedback.read(repo.root / FILENAME).decisions[-1].action == "fix"
        assert main(args) == 0


def test_unpriced_discovery_fails_before_a_paid_attempt(setup):
    settings, judge, _, _ = setup
    judge.model = "unpriced"
    with pytest.raises(ValueError, match="priced judge"):
        reservation_cost(judge, coverage_pair(1), settings)
