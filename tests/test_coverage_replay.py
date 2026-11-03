"""Exercise the offline scheduler through canonical candidates and its JSON CLI."""

import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from dry_lint.bench import GoldFunction, GoldPair
from dry_lint.detector import Detector
from dry_lint.models import Candidate, CandidatesFile, Consolidation, Run
from dry_lint.settings import Settings

from conftest import coverage_pair as pair
from conftest import function

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "replay_coverage.py"


@pytest.fixture
def api(load_script):
    return load_script("replay_coverage")


def step(api, name: str, baseline: list[Candidate], semantic: list[Candidate] = (), **kwargs):
    return api["ReplayStep"](
        run_id=name,
        sources={
            "baseline": CandidatesFile(candidates=baseline),
            "semantic": CandidatesFile(candidates=list(semantic)),
        },
        **kwargs,
    )


def test_repeated_runs_expand_coverage_without_repaying_for_unchanged_pairs(api) -> None:
    pairs = [pair(n) for n in range(7)]
    steps = [step(api, str(n), pairs[:3], pairs[3:]) for n in range(4)]
    fixed = api["replay"](steps, "fixed", 3, 12)
    exploring = api["replay"](steps, "balanced", 3, 12)
    assert fixed.state.attempts == 3
    assert fixed.steps[-1].covered == 3
    assert fixed.steps[-1].deferred == 4
    assert exploring.state.attempts == 7
    assert exploring.steps[-1].covered == 7
    assert exploring.steps[-1].deferred == 0


def test_refill_preserves_initial_baseline_then_explores(api) -> None:
    pairs = [pair(n) for n in range(7)]
    steps = [step(api, str(n), pairs[:3], pairs[3:]) for n in range(3)]
    result = api["replay"](steps, "refill", 3, 9)
    assert {s.key for s in result.steps[0].selected} == {p.key for p in pairs[:3]}
    assert result.steps[-1].covered == 7


@pytest.mark.parametrize("per_run,total,expected", [(0, 5, 0), (3, 0, 0), (3, 5, 5), (1, 9, 3)])
def test_budgets_bound_attempts_and_never_label_deferred_pairs(api, per_run, total, expected) -> None:
    pairs = [pair(n) for n in range(9)]
    result = api["replay"]([step(api, str(n), pairs) for n in range(3)], "balanced", per_run, total)
    assert result.state.attempts == expected
    assert all(len(s.selected) <= per_run for s in result.steps)
    assert result.steps[-1].covered + result.steps[-1].deferred == 9


def test_failed_attempt_consumes_budget_but_does_not_acknowledge_coverage(api) -> None:
    target = pair(1)
    result = api["replay"](
        [step(api, "fail", [target], failed_keys={target.key}), step(api, "retry", [target])], "balanced", 2, 2
    )
    assert result.steps[0].covered == 0
    assert result.steps[0].deferred == 1
    assert result.steps[1].covered == 1
    assert result.state.attempts == 2


def test_unordered_pairs_deduplicate_across_sources(api) -> None:
    target = pair(1)
    reverse = target.model_copy(update={"new": target.existing, "existing": target.new, "similarity": 0.1})
    result = api["replay"]([step(api, "one", [target], [reverse])], "balanced", 5, 5)
    assert result.state.attempts == 1
    assert result.steps[0].pool == 1


@pytest.mark.parametrize("change", ["new", "existing", "context", "policy"])
def test_changed_evidence_requires_a_new_simulated_judgment(api, change) -> None:
    target = pair(1)
    updated = target.model_copy(deep=True)
    policy = "offline-v1"
    if change == "policy":
        policy = "offline-v2"
    elif change == "context":
        updated.new.context = "from different_provider import value"
    else:
        side = updated.new if change == "new" else updated.existing
        side.code += "\n    changed()"
    result = api["replay"](
        [step(api, "one", [target]), step(api, "two", [updated], judge_policy=policy)], "balanced", 1, 2
    )
    assert result.state.attempts == 2
    assert result.steps[1].cached == 0
    assert len(result.state.historical_pairs) == 1


def test_ranking_changes_do_not_invalidate_the_same_judge_input(api) -> None:
    target = pair(1)
    updated = target.model_copy(update={"similarity": 0.1, "comparer": "new-version"})
    result = api["replay"]([step(api, "one", [target]), step(api, "two", [updated])], "balanced", 1, 2)
    assert result.state.attempts == 1
    assert result.steps[1].cached == 1


def test_persisted_state_resumes_and_identical_run_ids_are_idempotent(api) -> None:
    steps = [step(api, str(n), [pair(1), pair(2), pair(3)]) for n in range(3)]
    first = api["replay"](steps[:1], "balanced", 1, 3)
    state = api["ReplayState"].model_validate_json(first.state.model_dump_json())
    resumed = api["replay"](steps, "balanced", 1, 3, state)
    continuous = api["replay"](steps, "balanced", 1, 3)
    assert resumed.state == continuous.state
    assert resumed.steps[0].repeated
    assert resumed.steps[0].selected == []
    with pytest.raises(ValueError, match="run_id"):
        api["replay"]([step(api, "0", [pair(99)])], "balanced", 1, 4, state)


def test_aging_and_small_run_budgets_do_not_starve_old_candidates(api) -> None:
    old = pair(0)
    steps = [step(api, str(n), [pair(n + 1)], [old]) for n in range(10)]
    result = api["replay"](steps, "high-precision", 1, 10)
    assert old.key in result.state.historical_pairs


def test_contradictory_snapshot_evidence_is_rejected(api) -> None:
    target = pair(1)
    other = target.model_copy(deep=True)
    other.new.code += "\n    changed()"
    with pytest.raises(ValueError, match="conflicting"):
        api["replay"]([step(api, "one", [target], [other])], "balanced", 3, 3)


def test_conflicting_suppression_cannot_bypass_a_rule(api) -> None:
    target = pair(1)
    suppressed = target.model_copy(update={"filtered": "inline ignore"})
    with pytest.raises(ValueError, match="conflicting suppression"):
        api["replay"]([step(api, "one", [target], [suppressed])], "balanced", 3, 3)


def test_conflicting_consolidation_guidance_is_rejected(api) -> None:
    target = pair(1)
    different = target.model_copy(update={"consolidation": [Consolidation(path="shared/")]})
    with pytest.raises(ValueError, match="conflicting pair evidence"):
        api["replay"]([step(api, "one", [target], [different])], "balanced", 3, 3)


def test_candidate_sources_cannot_mix_revisions(api) -> None:
    snapshot = step(api, "one", [pair(1)], [pair(2)])
    snapshot.sources["semantic"].run = Run(head="future-revision")
    with pytest.raises(ValueError, match="snapshot provenance"):
        api["replay"]([snapshot], "balanced", 3, 3)


@pytest.mark.parametrize("per_run,total", [(-1, 1), (1, -1)])
def test_negative_budgets_are_rejected(api, per_run, total) -> None:
    with pytest.raises(ValueError, match="nonnegative"):
        api["replay"]([], "balanced", per_run, total)


def test_resuming_another_policy_requires_an_independent_ledger(api) -> None:
    previous = api["replay"]([], "fixed")
    with pytest.raises(ValueError, match="same policy"):
        api["replay"]([], "balanced", state=previous.state)


def test_round_robin_queries_get_a_first_attempt_before_repeat_work(api) -> None:
    first = pair(1)
    second = pair(2).model_copy(update={"new": function("other.py", "def other(value):\n    return value")})
    result = api["replay"]([step(api, "one", [first, pair(3), second])], "balanced", 2, 2)
    assert {s.query for s in result.steps[0].selected} == {first.new.qualname, second.new.qualname}


def test_filtered_pairs_never_consume_budget(api) -> None:
    target = pair(1).model_copy(update={"filtered": "inline distinct-from"})
    result = api["replay"]([step(api, "one", [target])], "balanced", 3, 3)
    assert result.steps[0].pool == 0
    assert result.state.attempts == 0


def test_cli_replays_real_detector_output_without_a_judge(api, repo, tmp_path) -> None:
    detector = Detector.for_repository(repo.root, Settings())
    candidates = detector.candidates(detector.functions)
    assert candidates
    payload = api["ReplayInput"](steps=[step(api, "one", candidates), step(api, "two", candidates)])
    source, output = tmp_path / "input.json", tmp_path / "output.json"
    source.write_text(payload.model_dump_json(), encoding="utf-8")
    subprocess.run(
        [sys.executable, str(SCRIPT), "--input", str(source), "--out", str(output), "--per-run", "1", "--total", "2"],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["state"]["attempts"] <= 2
    assert result["steps"][0]["selected"]
    assert "code" not in output.read_text(encoding="utf-8")


@pytest.mark.parametrize("subprocess_cli", [True, False])
def test_probe_cli_captures_and_compares_policies_on_a_real_repository(
    repo, tmp_path, monkeypatch, subprocess_cli
) -> None:
    output = tmp_path / "probe"
    command = [
        str(SCRIPT.with_name("probe_coverage.py")),
        "--root",
        str(repo.root),
        "--out",
        str(output),
        "--passes",
        "3",
        "--per-run",
        "2",
        "--total",
        "5",
    ]
    if subprocess_cli:
        subprocess.run([sys.executable, *command], check=True, capture_output=True, text=True)
    else:
        monkeypatch.syspath_prepend(str(SCRIPT.parent))
        monkeypatch.setattr(sys, "argv", command)
        runpy.run_path(command[0], run_name="__main__")
    result = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert result["head"] == repo.git("rev-parse", "HEAD")
    assert not result["dirty"]
    assert set(result["policies"]) == {"fixed", "refill", "high-precision", "balanced", "high-recall"}
    assert all(rows[-1]["attempts"] <= 5 for rows in result["policies"].values())


def test_probe_does_not_apply_labels_to_changed_or_missing_code(repo, load_script) -> None:
    capture = load_script("probe_coverage")["capture"]
    detector = Detector.for_repository(repo.root, Settings())
    candidate = detector.candidates(detector.functions)[0]
    label = GoldPair(
        new=GoldFunction(id=candidate.new.qualname, code=candidate.new.code),
        existing=GoldFunction(id=candidate.existing.qualname, code=candidate.existing.code),
        label="duplicate",
    )
    stale = label.model_copy(update={"new": label.new.model_copy(update={"code": "changed"})})
    missing = label.model_copy(update={"new": label.new.model_copy(update={"id": "absent.py::missing"})})
    borderline = label.model_copy(update={"label": "borderline"})
    _, metadata = capture(repo.root, [label, stale, missing, borderline], 3)
    assert metadata["positive_keys"] == [candidate.key]
    assert metadata["stale_labels"] == 1
    assert metadata["missing_labels"] == 1
    assert metadata["borderline_labels"] == 1
    with pytest.raises(ValueError, match="conflicting gold labels"):
        capture(repo.root, [label, label.model_copy(update={"label": "separate"})], 3)


def test_cli_resume_preserves_total_allowance(api, tmp_path, monkeypatch) -> None:
    source, output = tmp_path / "input.json", tmp_path / "result.json"
    payload = api["ReplayInput"](steps=[step(api, "one", [pair(1), pair(2)])])
    source.write_text(payload.model_dump_json(), encoding="utf-8")
    command = [str(SCRIPT), "--input", str(source), "--out", str(output), "--per-run", "1", "--total", "1"]
    monkeypatch.setattr(sys, "argv", command)
    runpy.run_path(str(SCRIPT), run_name="__main__")
    payload.steps.append(step(api, "two", [pair(1), pair(2)]))
    source.write_text(payload.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [*command, "--resume", str(output)])
    runpy.run_path(str(SCRIPT), run_name="__main__")
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["state"]["attempts"] == 1
    assert result["steps"][-1]["deferred"] == 1


def test_probe_rejects_invalid_pool_dimensions(tmp_path, monkeypatch) -> None:
    script = str(SCRIPT.with_name("probe_coverage.py"))
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    monkeypatch.setattr(sys, "argv", [script, "--root", str(tmp_path), "--out", str(tmp_path), "--passes", "0"])
    with pytest.raises(SystemExit) as error:
        runpy.run_path(script, run_name="__main__")
    assert error.value.code == 2
