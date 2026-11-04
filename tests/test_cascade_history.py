"""Both cascade stages use the real SDK and one metered replay ledger."""

import pytest

from dry_lint.settings import Escalation

from conftest import claude, coverage_pair, replay_payload


def clients(api, path, second_text='{"label":"duplicate","score":0.8}'):
    requests = []

    def client(model, text):
        return api["LiveAnswers"](
            path,
            model=model,
            max_tokens=512,
            prompt_policy="shared-operations-compact",
            http_client=claude(
                {
                    "model": model,
                    "usage": {"input_tokens": 1000, "output_tokens": 100},
                    "content": [{"type": "text", "text": text}],
                },
                requests,
            ),
        )

    cheap = client("claude-haiku-5-5", '{"label":"separate","score":0.55}')
    second = client("claude-sonnet-5-5", second_text)
    cheap.settings = cheap.settings.model_copy(update={"report_at": 0.7})
    return cheap, second, requests


@pytest.mark.parametrize("failed", [False, True])
def test_cascade_prices_both_stages_and_never_treats_failure_as_coverage(load_script, monkeypatch, tmp_path, failed):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    api = load_script("judge_history")
    first, second, requests = clients(api, tmp_path, "broken" if failed else '{"label":"duplicate","score":0.8}')
    pair = coverage_pair()
    history = replay_payload(api, {"baseline": [pair]}, {"baseline": [pair]})
    result = api["evaluate"](
        history,
        first,
        "protected",
        per_run=10,
        total=200,
        total_usd=0.04,
        protection=api["Protection"](baseline_calls=100, baseline_usd=0.025),
        escalation_answers=second,
        escalation=Escalation(use="anthropic", between=(0.4, 0.7), first_at=0.7),
    )
    last = result["curves"][-1]
    assert len(requests) == last["cumulative_attempts"] == 2
    assert last["cumulative_usd"] == pytest.approx(0.00315)
    assert last["reported"] == ([] if failed else [pair.key])
    assert last["decisions"][pair.key] == (first.key(pair) if failed else second.key(pair))
    assert first.observations is second.observations
    score = load_script("score_history")["score"](
        history, result, {first.key(pair): "duplicate", second.key(pair): "duplicate"}, first.observations
    )
    assert score["unique_true_reports"] == (0 if failed else 1)
    assert score["unique_failed_evidence"] == int(failed)


def test_deferred_second_opinion_waits_for_credit_without_spending_future_baseline(load_script, monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    api = load_script("judge_history")
    first, second, requests = clients(api, tmp_path)
    pair, later = coverage_pair(), coverage_pair(2)
    history = replay_payload(api, {"baseline": [pair]}, {"baseline": [pair, later]})
    result = api["evaluate"](
        history,
        first,
        "protected",
        per_run=10,
        total=200,
        total_usd=0.04,
        protection=api["Protection"](
            baseline_calls=100, baseline_usd=0.025, exploration_run_usd=0.006, exploration_carry_usd=0.015
        ),
        escalation_answers=second,
        escalation=Escalation(use="anthropic", between=(0.4, 0.7)),
    )
    early, last = result["curves"]
    assert early["reported"] == []
    assert later.key in last["covered"]
    assert pair.key in last["reported"]
    assert last["exploration_usd"] <= 0.015
    assert last["cumulative_usd"] <= 0.04
    assert len(requests) == last["cumulative_attempts"]


def test_changed_source_reopens_both_stages_without_crediting_old_second_opinion(load_script, monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    api = load_script("judge_history")
    first, second, requests = clients(api, tmp_path)
    pair = coverage_pair()
    revised = pair.model_copy(
        update={
            "new": pair.new.model_copy(
                update={
                    "code": pair.new.code.replace("value", "text"),
                }
            )
        }
    )
    history = replay_payload(api, {"baseline": [pair]}, {"baseline": [revised]})
    result = api["evaluate"](
        history,
        first,
        "protected",
        per_run=10,
        total=200,
        total_usd=0.04,
        protection=api["Protection"](baseline_calls=100, baseline_usd=0.025),
        escalation_answers=second,
        escalation=Escalation(use="anthropic", between=(0.4, 0.7)),
    )
    early, late = result["curves"]
    assert pair.key == revised.key
    assert early["covered"][pair.key] != late["covered"][pair.key]
    assert early["decisions"][pair.key] == second.key(pair)
    assert late["decisions"][pair.key] == second.key(revised)
    assert len(requests) == late["cumulative_attempts"] == 4
