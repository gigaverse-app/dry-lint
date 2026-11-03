"""Late baseline capacity survives earlier exploration under one cumulative allowance."""

import json

import pytest

from dry_lint.models import CandidatesFile

from conftest import claude, coverage_pair, replay_payload


@pytest.fixture
def experiment(load_script, monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    api = load_script("judge_history")
    client = claude(
        {"stop_reason": "end_turn", "content": [{"type": "text", "text": '{"label":"duplicate","score":0.9}'}]}, []
    )
    return api, api["LiveAnswers"](tmp_path, http_client=client)


def history(api, early, late):
    return replay_payload(api, {"semantic": early}, {"baseline": late, "semantic": early})


def test_exploration_leaves_capacity_for_later_baseline(experiment) -> None:
    api, answers = experiment
    early, late = coverage_pair(1), coverage_pair(2)
    result = api["evaluate"](history(api, [early], [late]), answers, "protected", total=1)
    assert result["curves"][0]["selected"] == []
    assert result["curves"][0]["stopped_reason"] == "exploration_call_reserve"
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
    assert result["curves"][0]["stopped_reason"] == "exploration_request_does_not_fit"
    assert late.key in result["curves"][1]["covered"]
    paced = api["evaluate"](history(api, early, [late]), answers, "protected", total=20, protection=reserve)
    assert len(paced["curves"][0]["selected"]) == 1
    assert paced["curves"][0]["stopped_reason"] == "exploration_pacing"
    assert paced["curves"][1]["selected"][0]["key"] == late.key


def test_duplicate_logical_run_does_not_buy_another_exploration_opportunity(experiment) -> None:
    api, answers = experiment
    payload = history(api, [coverage_pair(n) for n in range(5)], [])
    payload.steps = [payload.steps[0], payload.steps[0]]
    result = api["evaluate"](payload, answers, "protected", total=10)
    assert result["curves"][0]["cumulative_attempts"] == 1
    assert result["curves"][1]["selected"] == []
    assert result["curves"][1]["stopped_reason"] == "repeated_run"
    assert result["curves"][1]["cumulative_attempts"] == 1


@pytest.mark.parametrize("policy,calls,usd", [("fixed", 1, 0.1), ("protected", 41, 0.1), ("protected", 1, 0.6)])
def test_invalid_reserve_cannot_silently_expand_the_allowance(experiment, policy, calls, usd) -> None:
    api, answers = experiment
    with pytest.raises(ValueError, match="capacity must fit"):
        api["evaluate"](
            history(api, [], []),
            answers,
            policy,
            protection=api["Protection"](baseline_calls=calls, baseline_usd=usd),
        )


def test_reused_run_identity_with_changed_input_is_rejected(experiment) -> None:
    api, answers = experiment
    payload = history(api, [], [coverage_pair()])
    payload.steps[1].run_id = payload.steps[0].run_id
    with pytest.raises(ValueError, match="identity was reused"):
        api["evaluate"](payload, answers, "protected")


def test_changed_evidence_requires_new_judgment_without_replenishing_budget(experiment) -> None:
    api, answers = experiment
    original = coverage_pair()
    changed = original.model_copy(update={"new": original.new.model_copy(update={"code": "return changed()"})})
    payload = history(api, [], [changed])
    payload.steps[0].sources = {"baseline": CandidatesFile(candidates=[original])}
    limited = api["evaluate"](payload, answers, "protected", total=1)
    assert len(limited["curves"][0]["covered"]) == 1
    assert limited["curves"][1]["covered"] == {}
    assert limited["curves"][1]["cumulative_attempts"] == 1
    sufficient = api["evaluate"](payload, answers, "protected", total=2)
    assert len(sufficient["curves"][1]["covered"]) == 1
    assert sufficient["curves"][1]["cumulative_attempts"] == 2


def test_blinded_labels_score_both_prompt_identities_and_keep_unknowns_unresolved(
    experiment,
    load_script,
    tmp_path,
    monkeypatch,
) -> None:
    api, answers = experiment
    first, unknown = coverage_pair(), coverage_pair(2)
    payload = history(api, [], [first, unknown])
    capture = tmp_path / "inputs" / "captures" / "cohort"
    capture.mkdir(parents=True)
    (capture / "replay.json").write_text(payload.model_dump_json(), encoding="utf-8")
    results = tmp_path / "inputs" / "results"
    results.mkdir()
    rows = load_script("compare_history")["packets"](payload)
    assert all("verdict" not in row and "score" not in row for row in rows)
    labels = tmp_path / "inputs" / "labels.json"
    reference = [{"evidence": api["answer_key"](first, "reference-v1"), "label": "duplicate"}]
    labels.write_text(json.dumps(reference), encoding="utf-8")
    for policy in ("concept", "shared-operations"):
        answers.judge.prompt_policy = policy
        answers.judge.version = policy
        result = api["evaluate"](payload, answers, "protected")
        (results / f"cohort-{policy}-protected.json").write_text(json.dumps(result), encoding="utf-8")
    (results / "cohort-packets.json").write_text(json.dumps(rows), encoding="utf-8")
    # Later prompt changes must not alter the input identity of an already captured experiment.
    from dry_lint.judges.command import PROMPT_POLICIES

    monkeypatch.setitem(PROMPT_POLICIES, "shared-operations", ("future-version", "Different future prompt"))
    scorer = load_script("score_comparison")["score_comparison"]
    scored = scorer(capture.parent, results, labels, answers.directory)
    assert scored["physical_usage"]["requests"] == 4
    for arm in scored["cohorts"]["cohort"].values():
        assert arm["unique_true_reports"] == 1
        assert arm["unique_false_reports"] == 0
        assert arm["unique_unresolved_reports"] == 1
    labels.write_text(json.dumps(reference + [dict(reference[0], label="separate")]), encoding="utf-8")
    with pytest.raises(ValueError, match="Conflicting labels"):
        scorer(capture.parent, results, labels, answers.directory)
