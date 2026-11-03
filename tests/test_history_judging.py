"""Real SDK requests against a fake provider: accounting and evaluation are the code under test."""

import runpy
from pathlib import Path

import anthropic
import httpx2
import pytest

from dry_lint.models import CandidatesFile

from conftest import claude
from conftest import coverage_pair as candidate

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "judge_history.py"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")
    return runpy.run_path(str(SCRIPT))


def provider(requests, *, model="claude-sonnet-5-5", text='{"label":"duplicate","score":0.9}', status=200, usage=True):
    return claude(
        {
            "model": model,
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1000, "output_tokens": 100} if usage else {},
            "content": [{"type": "text", "text": text}],
        },
        requests,
        status=status,
    )


def test_provider_usage_is_counted_once_physically_but_each_policy_pays_its_own_cost(api, tmp_path) -> None:
    requests = []
    answers = api["LiveAnswers"](tmp_path, http_client=provider(requests))
    first, second = candidate(), candidate(2)
    replay_api = runpy.run_path(str(SCRIPT.with_name("replay_coverage.py")))
    step = replay_api["ReplayStep"](
        run_id="one",
        sources={"baseline": CandidatesFile(candidates=[first]), "deep": CandidatesFile(candidates=[first, second])},
    )
    payload = api["ReplayInput"].model_validate(
        {"steps": [step.model_dump(), step.model_copy(update={"run_id": "two"}).model_dump()]}
    )
    fixed = api["evaluate"](payload, answers, "fixed", per_run=1)
    refill = api["evaluate"](payload, answers, "refill", per_run=1)
    assert len(requests) == 2
    assert answers.spent == pytest.approx(0.006)
    assert fixed["curves"][-1]["cumulative_usd"] == pytest.approx(0.003)
    assert refill["curves"][-1]["cumulative_usd"] == pytest.approx(0.006)
    assert len(refill["curves"][-1]["reported"]) == 2
    restored = api["LiveAnswers"](tmp_path, http_client=provider(requests))
    restored.get(first)
    assert len(requests) == 2


def test_currency_limit_prevents_a_request_before_it_is_sent(api, tmp_path) -> None:
    requests = []
    answers = api["LiveAnswers"](tmp_path, limit=0.001, http_client=provider(requests))
    with pytest.raises(ValueError, match="allowance"):
        answers.get(candidate())
    assert requests == []


def test_invalid_paid_answer_keeps_usage_without_creating_a_verdict(api, tmp_path) -> None:
    requests = []
    answers = api["LiveAnswers"](tmp_path, http_client=provider(requests, text="invalid"))
    with pytest.raises(ValueError, match="Paid judgment failed"):
        answers.get(candidate())
    assert answers.spent == pytest.approx(0.003)
    with pytest.raises(ValueError, match="Previous paid attempt failed"):
        answers.get(candidate())
    assert len(requests) == 1


@pytest.mark.parametrize("options", [{"status": 401}, {"model": "unexpected-model"}, {"usage": False}])
def test_unmetered_or_unpriced_answer_stops_and_prevents_automatic_resume(api, tmp_path, options) -> None:
    requests = []
    answers = api["LiveAnswers"](tmp_path, http_client=provider(requests, **options))
    with pytest.raises(ValueError):
        answers.get(candidate())
    with pytest.raises(ValueError, match="Unmetered attempt"):
        api["LiveAnswers"](tmp_path, http_client=provider(requests))
    assert len(requests) == 1


def payload(api, *sources):
    return api["ReplayInput"].model_validate(
        {
            "steps": [
                {
                    "run_id": str(i),
                    "sources": {name: CandidatesFile(candidates=cs).model_dump() for name, cs in source.items()},
                }
                for i, source in enumerate(sources)
            ]
        }
    )


def test_expensive_baseline_does_not_donate_its_budget_to_cheaper_exploration(api, tmp_path) -> None:
    requests = []
    answers = api["LiveAnswers"](tmp_path, http_client=provider(requests))
    expensive = candidate()
    expensive = expensive.model_copy(
        update={"new": expensive.new.model_copy(update={"path": "large.py", "code": "#" + "x" * 30000})}
    )
    result = api["evaluate"](
        payload(api, {"baseline": [expensive], "deep": [candidate(2)]}), answers, "refill", run_usd=0.10
    )
    assert requests == []
    assert result["curves"][0]["deferred"] == 2


def test_baseline_first_cannot_guarantee_later_baseline_with_one_shared_campaign_budget(api, tmp_path) -> None:
    answers = api["LiveAnswers"](tmp_path, http_client=provider([]))
    early, late = candidate(), candidate(2)
    history = payload(api, {"deep": [early]}, {"baseline": [late], "deep": [early]})
    fixed = api["evaluate"](history, answers, "fixed", total=1)
    refill = api["evaluate"](history, answers, "refill", total=1)
    assert late.key in fixed["curves"][-1]["covered"]
    assert late.key not in refill["curves"][-1]["covered"]
    assert refill["curves"][-1]["cumulative_attempts"] == 1


def test_changed_evidence_is_not_credited_as_current_and_missing_labels_are_not_negatives(api, tmp_path) -> None:
    scorer = runpy.run_path(str(SCRIPT.with_name("score_history.py")))["score"]
    answers = api["LiveAnswers"](tmp_path, http_client=provider([]))
    early = candidate()
    late = early.model_copy(update={"new": early.new.model_copy(update={"code": "def run(x):\n    return list(x)"})})
    history = payload(api, {"baseline": [early]}, {"baseline": [late]})
    result = api["evaluate"](history, answers, "fixed", total=1)
    scored = scorer(
        history, result, {answers.key(early): "duplicate", answers.key(late): "duplicate"}, answers.observations
    )
    assert scored["curves"][0]["reported_positives"] == 1
    assert scored["curves"][1]["reported_positives"] == 0
    assert scored["curves"][1]["ever_reported_positives"] == 1
    unknown = scorer(history, result, {}, answers.observations)
    assert unknown["unique_false_reports"] == 0
    assert unknown["unique_unresolved_reports"] == 1
    result["curves"][1]["covered"] = result["curves"][0]["covered"]
    with pytest.raises(ValueError, match="stale"):
        scorer(history, result, {}, answers.observations)


@pytest.mark.parametrize("options", [{"policy": "balanced"}, {"total": -1}, {"run_usd": -1}])
def test_invalid_live_budget_configuration_is_rejected(api, tmp_path, options) -> None:
    answers = api["LiveAnswers"](tmp_path, http_client=provider([]))
    with pytest.raises(ValueError, match="nonnegative"):
        api["evaluate"](payload(api), answers, **({"policy": "refill"} | options))


def test_interruption_after_send_keeps_unknown_usage_from_becoming_a_free_retry(api, tmp_path) -> None:
    def interrupted(request):
        assert list(tmp_path.glob("*.unmetered"))
        raise KeyboardInterrupt

    client = anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(interrupted))
    answers = api["LiveAnswers"](tmp_path, http_client=client)
    with pytest.raises(KeyboardInterrupt):
        answers.get(candidate())
    with pytest.raises(ValueError, match="Unmetered attempt"):
        answers.get(candidate(2))
    with pytest.raises(ValueError, match="Unmetered attempt"):
        api["LiveAnswers"](tmp_path, http_client=provider([]))
