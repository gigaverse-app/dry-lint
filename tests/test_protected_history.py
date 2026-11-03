"""Late baseline capacity survives earlier exploration under one cumulative allowance."""

import pytest

from dry_lint.models import CandidatesFile

from conftest import claude, coverage_pair


@pytest.fixture
def experiment(load_script, monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    api = load_script("judge_history")
    client = claude(
        {"stop_reason": "end_turn", "content": [{"type": "text", "text": '{"label":"duplicate","score":0.9}'}]}, []
    )
    return api, api["LiveAnswers"](tmp_path, http_client=client)


def history(api, early, late):
    return api["ReplayInput"].model_validate(
        {
            "steps": [
                {"run_id": "early", "sources": {"semantic": CandidatesFile(candidates=early).model_dump()}},
                {
                    "run_id": "late",
                    "sources": {
                        "baseline": CandidatesFile(candidates=late).model_dump(),
                        "semantic": CandidatesFile(candidates=early).model_dump(),
                    },
                },
            ]
        }
    )


def test_exploration_leaves_capacity_for_later_baseline(experiment) -> None:
    api, answers = experiment
    early, late = coverage_pair(1), coverage_pair(2)
    result = api["evaluate"](history(api, [early], [late]), answers, "protected", total=1)
    assert result["curves"][0]["selected"] == []
    assert late.key in result["curves"][1]["covered"]
    assert early.key not in result["curves"][1]["covered"]


def test_dollar_reserve_and_pacing_are_independent_of_the_call_ceiling(experiment) -> None:
    api, answers = experiment
    early, late = [coverage_pair(n) for n in range(4)], coverage_pair(10)
    reserve = api["Protection"](baseline_calls=1, baseline_usd=0.10, exploration_per_run=1)
    result = api["evaluate"](
        history(api, early, [late]), answers, "protected", total=20, total_usd=0.18, protection=reserve
    )
    # The next exploration request's worst-case price cannot fit outside the reserved $0.10.
    assert result["curves"][0]["selected"] == []
    assert late.key in result["curves"][1]["covered"]
    paced = api["evaluate"](history(api, early, [late]), answers, "protected", total=20, protection=reserve)
    assert len(paced["curves"][0]["selected"]) == 1
    assert paced["curves"][1]["selected"][0]["key"] == late.key


def test_duplicate_logical_run_does_not_buy_another_exploration_opportunity(experiment) -> None:
    api, answers = experiment
    payload = history(api, [coverage_pair(n) for n in range(5)], [])
    payload.steps = [payload.steps[0], payload.steps[0]]
    result = api["evaluate"](payload, answers, "protected", total=10)
    assert result["curves"][0]["cumulative_attempts"] == 1
    assert result["curves"][1]["selected"] == []
    assert result["curves"][1]["cumulative_attempts"] == 1
