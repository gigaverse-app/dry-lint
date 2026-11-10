"""Paid discovery journeys use production admission and the real SDK with an HTTP fake."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import anthropic
import httpx2
import pytest

from dry_lint.baseline import require_complete
from dry_lint.cli import main
from dry_lint.detector import Detector, changed_lines, touched
from dry_lint.discovery import CampaignStore, reservation_cost
from dry_lint.feedback import FILENAME, Feedback
from dry_lint.judges.anthropic import AnthropicJudge
from dry_lint.judging import Judging
from dry_lint.models import CandidatesFile, Run
from dry_lint.presets import resolve
from dry_lint.report import Report
from dry_lint.settings import Escalation, Settings

from conftest import TWIN, claude, coverage_pair, scheduled_judge


@pytest.fixture
def setup(tmp_path):
    requests: list = []
    reply = {"stop_reason": "end_turn", "content": [{"type": "text", "text": '{"label":"duplicate","score":0.8}'}]}
    return scheduled_judge(tmp_path, claude(reply, requests), requests)


def check(setup, tmp_path, candidates, revision="tree1"):
    settings, judge, store, _ = setup
    run = Run(repository="owner/repo", session="feature", revision=revision)
    judging = Judging(settings, judge, None, store)
    judging.campaign = CampaignStore(tmp_path / "campaign.sqlite3", run)
    findings = judging.findings(candidates, run)
    report = Report.build(findings, settings, run=run, judge=judging.name, judging=judging.summary())
    return report, judging.campaign.snapshot()


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
    settings.discovery.calls = 3  # one exploration call for the whole campaign: int(3 * (1 - baseline_fraction))
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


def test_a_reservation_settles_exactly_once(setup, tmp_path):
    settings, judge, _, _ = setup
    campaign = CampaignStore(tmp_path / "ledger.sqlite3", Run(session="feature", revision="tree"))
    reservation = campaign.reserve(coverage_pair(1), judge, settings, 0.003)
    assert campaign.settle(reservation, 0.001, True) == 0.001
    before = campaign.snapshot()
    # A second settle would refund exploration credit again and could turn an answered attempt into a failed one.
    with pytest.raises(ValueError, match="already settled"):
        campaign.settle(reservation, 0.0, False)
    assert campaign.snapshot() == before


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
    assert reservations.count(0) == 1 and reservations.count("budget") == 3
    # Reopening the DB after an abandoned provider call cannot reset its reservation.
    assert CampaignStore(path, run).snapshot().usd == 0.003
    assert CampaignStore(path, Run(session="another", revision="tree")).snapshot().usd == 0


def test_failed_answers_remain_unresolved_and_do_not_get_free_retries(setup, tmp_path):
    settings, judge, store, requests = setup
    judge.client = AnthropicJudge(
        api_key="test",
        http_client=claude({"stop_reason": "end_turn", "content": [{"type": "text", "text": "not json"}]}, requests),
    ).client
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


def test_same_file_duplicates_are_exploration_and_never_replace_baseline(repo):
    repo.write(
        "src/widgets/caption.py",
        TWIN + TWIN.replace("preview_caption_text", "preview_title_text").replace("register_widget", "register_title"),
    )
    settings = resolve(Settings(preset="balanced"))
    detector = Detector.for_repository(repo.root, settings)
    pairs = detector.candidates(touched(detector.functions, changed_lines(repo.root, "main")))
    same_file = [c for c in pairs if c.new.path == c.existing.path]
    assert same_file and all(c.lane == "exploration" for c in same_file)
    assert all(c.new.qualname != c.existing.qualname for c in pairs)


def test_cli_feedback_must_be_staged_and_changes_reopen_dismissals(repo, setup, tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)  # exercise local branch campaigns even inside PR CI
    settings, judge, _, requests = setup
    report_path = tmp_path / "report.json"
    repo.git("reset", "--soft", "main")
    args = ["check", "--root", str(repo.root), "--staged", "--preset", "balanced", "--report", str(report_path)]
    with patch("dry_lint.judging.make_judge", return_value=judge):
        assert main(args) == 1
        report = Report.model_validate_json(report_path.read_bytes())
        assert report.run.pull_request is None and report.run.session
        pair = report.findings[0].candidate.key
        feedback_args = [
            "feedback",
            "--root",
            str(repo.root),
            "--from",
            str(report_path),
            "--reason",
            "Reviewed separate lifetime contracts",
            "--reviewer",
            "test-agent",
        ]
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


@pytest.mark.parametrize("run", [Run(), Run(session="feature")])
def test_campaign_rejects_missing_identity_or_revision(tmp_path, run):
    with pytest.raises(ValueError, match="requires"):
        CampaignStore(tmp_path / "state.sqlite3", run)


def test_first_admission_credits_a_revision_and_pr_session_names_cannot_collide(setup, tmp_path):
    settings, judge, _, _ = setup
    path = tmp_path / "state.sqlite3"
    campaign = CampaignStore(path, Run(session="7", head="tree"))
    assert campaign.reserve(coverage_pair(1), judge, settings, 0.001) == 0
    assert campaign.snapshot().credit == settings.discovery.exploration_per_revision
    assert CampaignStore(path, Run(pull_request=7, head="tree")).snapshot().usd == 0


@pytest.mark.parametrize("limit", ["revision", "campaign", "explicit"])
def test_call_limits_apply_even_when_dollars_remain(setup, tmp_path, limit):
    settings, judge, _, _ = setup
    if limit == "revision":
        settings.discovery.calls_per_revision = 1
    elif limit == "campaign":
        settings.discovery.calls = 1
    else:
        settings.max_judgements = 1
    path = tmp_path / "state.sqlite3"
    first = CampaignStore(path, Run(session="feature", head="tree1"))
    assert first.reserve(coverage_pair(1), judge, settings, 0.001) == 0
    second = CampaignStore(path, Run(session="feature", head="tree2" if limit == "campaign" else "tree1"))
    assert second.reserve(coverage_pair(2), judge, settings, 0.001) == "limit"
    assert second.snapshot().usd == 0.001


def test_old_pr_spending_is_carried_into_the_campaign(setup, tmp_path):
    settings, judge, store, calls = setup
    run = Run(repository="org/repo", pull_request=7, head="tree")
    store.add_spent(run, 0.0399)
    judging = Judging(settings, judge, None, store)
    judging.campaign = CampaignStore(tmp_path / "state.sqlite3", run)
    findings = judging.findings([coverage_pair(1)], run)
    assert findings[0].deferred and not calls
    assert judging.campaign.snapshot().usd == 0.0399


def test_provider_failure_is_accounted_without_sdk_retry(setup, tmp_path):
    settings, _, store, calls = setup
    judge = AnthropicJudge(
        api_key="test",
        http_client=claude({"error": {"type": "overloaded_error", "message": "unavailable"}}, calls, status=529),
        **settings.judge.options(),
    )
    report, state = check((settings, judge, store, calls), tmp_path, [coverage_pair(1)])
    assert report.deferred == 1 and len(calls) == 1
    assert state.usd == reservation_cost(judge, coverage_pair(1), settings)
    assert report.judging.spend[0].failed == 1
    assert "deferred; accounted attempts can retry on a later tree" in report.judging.line()


def test_broken_plugin_response_cannot_clear_a_pair_or_refund_the_attempt(setup, tmp_path):
    settings, judge, _, _ = setup
    with patch.object(judge, "judge", return_value=[]):
        report, state = check(setup, tmp_path, [coverage_pair(1)])
    assert report.deferred == 1
    assert state.usd == reservation_cost(judge, coverage_pair(1), settings)


def test_cache_usage_is_included_in_the_settled_bill(setup, tmp_path):
    settings, _, store, calls = setup
    judge = AnthropicJudge(
        api_key="test",
        http_client=claude(
            {
                "stop_reason": "end_turn",
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 100,
                    "cache_creation_input_tokens": 200,
                    "cache_read_input_tokens": 300,
                },
                "content": [{"type": "text", "text": '{"label":"separate","score":0.1}'}],
            },
            calls,
        ),
        **settings.judge.options(),
    )
    _, state = check((settings, judge, store, calls), tmp_path, [coverage_pair(1)])
    assert state.usd == pytest.approx(0.000178)


def test_scheduler_rejects_unbudgeted_second_stage(setup, tmp_path):
    settings, judge, store, _ = setup
    settings.escalate = Escalation(use="anthropic")
    judging = Judging(settings, judge, judge, store)
    judging.campaign = CampaignStore(tmp_path / "state.sqlite3", Run(session="feature", head="tree"))
    with pytest.raises(ValueError, match="one judge"):
        judging.findings([coverage_pair(1)])


def test_split_cli_carries_baseline_lanes_and_reuses_campaign(repo, setup, tmp_path):
    settings, judge, _, calls = setup
    path = tmp_path / "candidates.json"
    report_path = tmp_path / "report.json"
    common = ["--root", str(repo.root), "--preset", "balanced", "--store", str(tmp_path / "store")]
    assert main(["detect", *common, "--base", "main", "--out", str(path)]) == 0
    snapshot = CandidatesFile.model_validate_json(path.read_bytes())
    assert snapshot.run.revision and any(c.lane == "baseline" for c in snapshot.candidates)
    with patch("dry_lint.judging.make_judge", return_value=judge):
        assert main(["judge", *common, "--candidates", str(path), "--report", str(report_path)]) == 1
        first = len(calls)
        assert main(["check", *common, "--base", "main"]) == 1
        assert len(calls) == first
        last = repo.root / ".git/dry-lint/last-report.json"
        assert last.exists()
        pair = Report.model_validate_json(last.read_bytes()).findings[0].candidate.key
        assert (
            main(
                [
                    "feedback",
                    "dismiss",
                    pair,
                    "--root",
                    str(repo.root),
                    "--reason",
                    "Reviewed distinct contracts",
                    "--reviewer",
                    "test-agent",
                ]
            )
            == 0
        )
        assert main(["check", *common, "--base", "main"]) == 1  # unstaged decision is absent from HEAD
        repo.commit("reviewed distinction")
        assert main(["check", *common, "--base", "main"]) == 0
        assert (
            main(
                [
                    "feedback",
                    "dismiss",
                    "missing",
                    "--root",
                    str(repo.root),
                    "--reason",
                    "not a report",
                    "--reviewer",
                    "test-agent",
                ]
            )
            == 2
        )


def test_spending_cap_leaves_baseline_and_waiting_exploration_advisory(setup, tmp_path):
    settings, _, _, calls = setup
    settings.budget.usd = 0
    pairs = [coverage_pair(1), coverage_pair(2).model_copy(update={"lane": "exploration"})]
    report, _ = check(setup, tmp_path, pairs)
    assert len(report.findings) == 2 and not calls
    assert all(f.budget_deferred and not f.blocking for f in report.findings)


def test_pairs_beyond_the_judging_budget_are_deferred_not_failed(setup, tmp_path):
    """A pull request with more look-alikes than its judging budget covers passes the check on what was judged."""
    settings, _, _, requests = setup
    settings.discovery.calls_per_revision = 2
    report, state = check(setup, tmp_path, [coverage_pair(n) for n in range(1, 6)])

    judged = [f for f in report.findings if f.verdict is not None]
    unjudged = [f for f in report.findings if f.verdict is None]
    assert len(judged) == len(requests) == 2 and len(unjudged) == 3
    assert all(f.budget_deferred and not f.blocking for f in unjudged)
    assert report.judging.spend[0].skipped == 3 and not report.judging.spend[0].failed
    require_complete(report, check=True)
    # Changing accepted debt still needs every pair assessed.
    with pytest.raises(ValueError, match="Judging is incomplete"):
        require_complete(report)


def test_a_failed_judge_is_still_incomplete_while_budget_gaps_are_not(setup, tmp_path):
    settings, _, store, _ = setup
    failing = AnthropicJudge(
        api_key="test", http_client=claude({}, [], status=500), **{**settings.judge.options(), "max_retries": 0}
    )
    report, _ = check((settings, failing, store, []), tmp_path, [coverage_pair(1)])

    assert report.findings[0].deferred and not report.findings[0].budget_deferred
    with pytest.raises(ValueError, match="Judging is incomplete"):
        require_complete(report, check=True)


def concurrency_probe(settings: Settings, workers: int) -> tuple[AnthropicJudge, list[int]]:
    """A judge whose transport holds each call briefly and records how many were in flight at once."""
    lock, in_flight, peaks = threading.Lock(), [0], []

    def answer(request: httpx2.Request) -> httpx2.Response:
        with lock:
            in_flight[0] += 1
            peaks.append(in_flight[0])
        time.sleep(0.05)
        with lock:
            in_flight[0] -= 1
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5-5",
                "stop_sequence": None,
                "usage": {"input_tokens": 900, "output_tokens": 120},
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": '{"label":"duplicate","score":0.8}'}],
            },
        )

    options = {**settings.judge.options(), "workers": workers}
    client = anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(answer))
    return AnthropicJudge(api_key="test", http_client=client, **options), peaks


def test_the_scheduler_judges_up_to_the_judges_workers_at_once(setup, tmp_path):
    settings, _, store, _ = setup
    judge, peaks = concurrency_probe(settings, workers=4)
    pairs = [coverage_pair(n) for n in range(1, 9)]
    report, state = check((settings, judge, store, []), tmp_path, pairs)

    assert 1 < max(peaks) <= 4
    assert all(f.verdict is not None for f in report.findings) and len(report.findings) == 8
    # Every reservation settled exactly once, as answered, and billed from the SDK usage.
    assert len(state.attempts) == 8 and all(a.status == "answered" for a in state.attempts)
    assert state.usd == pytest.approx(8 * 0.00015)


def test_a_single_worker_judge_keeps_one_call_in_flight(setup, tmp_path):
    settings, _, store, _ = setup
    judge, peaks = concurrency_probe(settings, workers=1)
    check((settings, judge, store, []), tmp_path, [coverage_pair(n) for n in range(1, 4)])

    assert max(peaks) == 1


def test_parallel_reservations_do_not_strand_the_exploration_credit(setup, tmp_path):
    """
    Reservations hold a conservative bound; real answers cost a fraction of it. A batch in flight must not make
    the scheduler refuse the next pair for a budget it would have again the moment the batch settled.
    """
    settings, _, store, _ = setup
    judge, peaks = concurrency_probe(settings, workers=4)
    pool = [coverage_pair(n).model_copy(update={"lane": "exploration"}) for n in range(1, 41)]
    reserved = reservation_cost(judge, pool[0], settings)
    credit = settings.discovery.exploration_per_revision
    # The premise: fewer bounds than the call cap fit in one revision's credit, though every real answer does.
    assert int(credit / reserved) < settings.discovery.exploration_calls_per_revision < len(pool)
    assert settings.discovery.exploration_calls_per_revision * 0.00015 < credit

    report, state = check((settings, judge, store, []), tmp_path, pool)

    judged = [f for f in report.findings if f.verdict is not None]
    # INVARIANT: with money left, the call cap decides how many pairs are asked, not the size of a batch.
    assert len(judged) == len(state.attempts) == settings.discovery.exploration_calls_per_revision
    assert all(a.status == "answered" for a in state.attempts)
    assert max(peaks) > 1  # still asked several at a time
    unasked = [f for f in report.findings if f.verdict is None]
    assert unasked and all(f.deferred and f.budget_deferred for f in unasked)
    assert state.usd == pytest.approx(len(judged) * 0.00015) and state.usd <= settings.budget.usd
    assert 0 <= state.credit <= credit


def test_a_budget_that_is_really_spent_still_refuses_after_the_batch_settles(setup, tmp_path):
    settings, _, store, _ = setup
    judge, _ = concurrency_probe(settings, workers=4)
    # Room for two real answers and no more: settling the batch frees nothing the third pair could use.
    settings.budget.usd = 2 * 0.00015 + reservation_cost(judge, coverage_pair(1), settings)
    pool = [coverage_pair(n) for n in range(1, 7)]

    report, state = check((settings, judge, store, []), tmp_path, pool)

    asked = [f for f in report.findings if f.verdict is not None]
    assert 2 <= len(asked) < len(pool)
    assert state.usd <= settings.budget.usd
    unasked = [f for f in report.findings if f.verdict is None]
    assert all(f.deferred and f.budget_deferred for f in unasked)
    assert all(a.status == "answered" for a in state.attempts)


def test_settling_early_keeps_every_baseline_answer_ahead_of_exploration(setup, tmp_path):
    settings, _, store, requests = setup
    judge, _ = concurrency_probe(settings, workers=4)
    baseline = [coverage_pair(n) for n in range(1, 4)]
    exploration = [coverage_pair(n).model_copy(update={"lane": "exploration"}) for n in range(10, 50)]

    report, state = check((settings, judge, store, requests), tmp_path, [*exploration, *baseline])

    lanes = [a.lane for a in state.attempts]
    assert lanes == sorted(lanes)  # "baseline" sorts before "exploration": no exploration reserved earlier
    assert (
        lanes.count("baseline") == 3 and lanes.count("exploration") == settings.discovery.exploration_calls_per_revision
    )
    assert all(f.verdict is not None for f in report.findings if f.candidate.lane == "baseline")
