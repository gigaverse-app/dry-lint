"""Real SDK requests against a fake provider: accounting and evaluation are the code under test."""

import anthropic
import httpx2
import pytest

from dry_lint.models import CandidatesFile

from conftest import claude
from conftest import coverage_pair as candidate
from conftest import replay_payload as payload


@pytest.fixture
def api(monkeypatch, load_script):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")
    return load_script("judge_history")


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


def test_cheaper_model_uses_its_own_price_reservation_and_cache_identity(api, tmp_path) -> None:
    requests = []
    cheap = api["LiveAnswers"](
        tmp_path,
        model="claude-haiku-5-5",
        max_tokens=512,
        http_client=provider(requests, model="claude-haiku-5-5"),
    )
    original = api["LiveAnswers"](tmp_path, http_client=provider([]))
    assert cheap.key(candidate()) != original.key(candidate())
    assert cheap.reserve(candidate()) < 0.003
    answer = cheap.get(candidate())
    assert answer.usd == pytest.approx(0.00015)
    assert answer.model == "claude-haiku-5-5"
    assert cheap.spent == pytest.approx(answer.usd)
    with pytest.raises(ValueError, match="price"):
        api["LiveAnswers"](tmp_path, model="unpriced")


def test_mixed_policy_rejudges_exploration_when_it_becomes_baseline(api, tmp_path, load_script) -> None:
    response = '{"label":"duplicate","score":0.65}'
    cheap = api["LiveAnswers"](
        tmp_path,
        model="claude-haiku-5-5",
        max_tokens=512,
        http_client=provider([], model="claude-haiku-5-5", text=response),
    )
    cheap.settings = cheap.settings.model_copy(update={"report_at": 0.7})
    baseline = api["LiveAnswers"](tmp_path, max_tokens=512, http_client=provider([], text=response))
    pair = candidate()
    history = payload(api, {"deep": [pair]}, {"baseline": [pair]})
    result = api["evaluate"](history, cheap, "protected", total_usd=0.04, baseline_answers=baseline)
    first, second = result["curves"]
    assert first["covered"][pair.key] != second["covered"][pair.key]
    assert second["cumulative_attempts"] == 2
    assert second["cumulative_usd"] == pytest.approx(0.00315)
    assert cheap.observations is baseline.observations
    assert first["reported"] == []
    assert len(second["reported"]) == 1
    labels = {cheap.key(pair): "duplicate", baseline.key(pair): "duplicate"}
    scored = load_script("score_history")["score"](history, result, labels, cheap.observations)
    assert scored["curves"][0]["reported_positives"] == 0
    assert scored["curves"][-1]["reported_positives"] == 1
    assert scored["unique_true_reports"] == 1


def test_dollar_pacing_leaves_exploration_for_later_revisions(api, tmp_path) -> None:
    answers = api["LiveAnswers"](
        tmp_path, model="claude-haiku-5-5", max_tokens=512, http_client=provider([], model="claude-haiku-5-5")
    )
    pairs = [candidate(n) for n in range(10)]
    allowance = answers.reserve(pairs[0]) * 1.1
    protection = api["Protection"](
        baseline_calls=20, baseline_usd=0.03, exploration_per_run=10, exploration_run_usd=allowance
    )
    result = api["evaluate"](
        payload(api, {"deep": pairs}, {"deep": pairs}), answers, "protected", total_usd=0.04, protection=protection
    )
    assert [len(c["selected"]) for c in result["curves"]] == [1, 1]
    assert result["curves"][-1]["exploration_usd"] == pytest.approx(0.0003)
    assert result["curves"][-1]["cumulative_usd"] <= 0.01


def test_failed_paid_replay_answer_consumes_budget_without_becoming_coverage(api, tmp_path, load_script) -> None:
    requests = []
    answers = api["LiveAnswers"](tmp_path, max_tokens=512, http_client=provider(requests, text="invalid"))
    history = payload(api, {"baseline": [candidate()]}, {"baseline": [candidate()]})
    result = api["evaluate"](history, answers, "fixed")
    assert len(requests) == 1
    assert result["curves"][-1]["covered"] == {}
    assert result["curves"][-1]["cumulative_attempts"] == 1
    assert result["curves"][-1]["cumulative_usd"] == pytest.approx(0.003)
    scored = load_script("score_history")["score"](history, result, {}, answers.observations)
    assert scored["unique_failed_evidence"] == 1
    assert scored["unique_judged_evidence"] == 0


def test_provider_usage_is_counted_once_physically_but_each_policy_pays_its_own_cost(
    api, tmp_path, load_script
) -> None:
    requests = []
    answers = api["LiveAnswers"](tmp_path, http_client=provider(requests))
    first, second = candidate(), candidate(2)
    replay_api = load_script("replay_coverage")
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


def test_currency_limit_prevents_a_request_before_it_is_sent(api, tmp_path, load_script) -> None:
    requests = []
    answers = api["LiveAnswers"](tmp_path, limit=0.001, http_client=provider(requests))
    with pytest.raises(ValueError, match="allowance"):
        answers.get(candidate())
    assert requests == []
    with pytest.raises(ValueError, match="allowance"):
        load_script("compare_history")["complete_pool"](payload(api, {"baseline": [candidate()]}), answers)
    assert requests == []


def test_invalid_paid_answer_keeps_usage_without_creating_a_verdict(api, tmp_path, load_script) -> None:
    requests = []
    answers = api["LiveAnswers"](tmp_path, http_client=provider(requests, text="invalid"))
    with pytest.raises(ValueError, match="Paid judgment failed"):
        answers.get(candidate())
    assert answers.spent == pytest.approx(0.003)
    with pytest.raises(ValueError, match="Previous paid attempt failed"):
        answers.get(candidate())
    assert len(requests) == 1
    complete_pool = load_script("compare_history")["complete_pool"]
    failed = complete_pool(payload(api, {"baseline": [candidate(), candidate(2)]}), answers)
    assert len(failed) == 2
    assert len(requests) == 2  # Continue independent evidence, never retry the failed paid answer.
    assert all(o.stop_reason == "end_turn" and o.error_detail for o in answers.observations.values())


@pytest.mark.parametrize("options", [{"status": 401}, {"model": "unexpected-model"}, {"usage": False}])
def test_unmetered_or_unpriced_answer_stops_and_prevents_automatic_resume(api, tmp_path, options) -> None:
    requests = []
    answers = api["LiveAnswers"](tmp_path, http_client=provider(requests, **options))
    with pytest.raises(ValueError):
        answers.get(candidate())
    with pytest.raises(ValueError, match="Unmetered attempt"):
        api["LiveAnswers"](tmp_path, http_client=provider(requests))
    assert len(requests) == 1


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


def test_changed_evidence_is_not_credited_as_current_and_missing_labels_are_not_negatives(
    api, tmp_path, load_script
) -> None:
    scorer = load_script("score_history")["score"]
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
