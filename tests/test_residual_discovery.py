"""Residual recovery uses real detection, SQLite, verdict storage and an offline SDK transport."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest
from test_discovery import check
from test_discovery import setup as setup
from test_operation_blocks import OPERATION, background

from dry_lint import judging as judging_module
from dry_lint.cli import main
from dry_lint.detector import Detector
from dry_lint.discovery import Campaign, CampaignStore, reservation_cost
from dry_lint.judges.anthropic import AnthropicJudge
from dry_lint.judging import Judging
from dry_lint.models import CandidatesFile, Run, evidence
from dry_lint.presets import resolve
from dry_lint.settings import Discovery, ExplorationComparer, Settings
from dry_lint.store import DirectoryStore, VerdictStore

from conftest import Repo, claude, coverage_pair, residual_pair


@pytest.fixture
def residual_setup(setup):
    original, judge, store, calls = setup
    settings = original.model_copy(deep=True, update={"discovery": Discovery(enabled=True)})
    settings.discovery.residual_comparers = [
        ExplorationComparer(use="tfidf", neighbours=100, min_similarity=0, min_similarity_small=0)
    ]
    return settings, judge, store, calls


@pytest.mark.parametrize("explicit", [False, True])
def test_residual_detection_preserves_complete_balanced_prefix_and_round_trips(tmp_path, explicit):
    repo = Repo(tmp_path / "balanced")
    for i in range(25):
        repo.write(f"copy{i:02}.py", "def deliver(owner, payload):\n" + OPERATION)
    repo.write("noise.py", "\n".join(f.code + "\n" for f in background(2500)))
    repo.commit()
    settings = resolve(Settings(preset="balanced-text", exclude=[]), {})
    if explicit:
        settings = resolve(Settings(preset="balanced-text", exclude=[], discovery=settings.discovery.model_dump()), {})
    choices = [c.model_dump() for c in settings.discovery.comparers]
    assert [c["use"] for c in choices] == ["tfidf", "operation-blocks"]
    detector = Detector.for_repository(repo.root, settings)
    changed = [f for f in detector.functions if f.path in {"copy00.py", "copy01.py"}]
    prefix = detector.candidates(changed)
    assert any(c.comparer.startswith("operation-blocks:") for c in prefix)
    settings.discovery.residual_comparers = [
        ExplorationComparer(use="tfidf", neighbours=100, min_similarity=0, min_similarity_small=0)
    ]
    candidates = Detector.for_repository(repo.root, settings).candidates(changed)
    assert [c.model_dump() for c in candidates if not c.residual] == [c.model_dump() for c in prefix]
    assert [c.model_dump() for c in settings.discovery.comparers] == choices
    assert any(c.residual for c in candidates)
    assert len({c.key for c in candidates}) == len(candidates)
    artifact = CandidatesFile(candidates=candidates)
    assert artifact.schema_version == 16
    assert CandidatesFile.model_validate_json(artifact.model_dump_json()).model_dump() == artifact.model_dump()


def test_native_prefix_is_protected_then_unattempted_exploration_borrows(residual_setup, tmp_path):
    settings, judge, store, calls = residual_setup
    baseline = coverage_pair(1)
    explore = coverage_pair(2).model_copy(update={"lane": "exploration"})
    suffix = residual_pair(3).model_copy(update={"similarity": 1})
    deferred = coverage_pair(4).model_copy(update={"lane": "exploration"})
    settings.discovery.exploration_per_revision = reservation_cost(judge, explore, settings)
    control_settings = settings.model_copy(deep=True)
    control_settings.discovery.residual_comparers = []
    control = (control_settings, judge, VerdictStore(DirectoryStore(tmp_path / "control-store")), calls)
    prefix, before = check(control, tmp_path / "control", [baseline, explore, deferred])
    assert len(before.attempts) == 2 and prefix.deferred == 1
    report, state = check(residual_setup, tmp_path / "treatment", [suffix, explore, baseline, deferred])
    assert state.attempts[:2] == before.attempts
    assert len(state.attempts) == 4 and report.deferred == 0
    assert {f.candidate.key for f in prefix.visible} <= {f.candidate.key for f in report.visible}
    assert state.usd == pytest.approx(before.usd * 2)
    assert state.usd <= settings.budget.usd
    again, repeat = check(residual_setup, tmp_path / "treatment", [suffix, explore, baseline, deferred])
    assert all(f.cached for f in again.findings)
    assert repeat == state


def test_residual_reservations_share_limits_and_cannot_mint_credit(residual_setup, tmp_path):
    settings, judge, _, _ = residual_setup
    settings.budget.usd = 0.004
    settings.discovery.exploration_per_revision = 0
    path = tmp_path / "state.sqlite3"
    run = Run(session="feature", revision="tree")
    campaign = CampaignStore(path, run)

    def reserve(n):
        candidate = residual_pair(n)
        return CampaignStore(path, run).reserve(candidate, judge, settings, 0.003, residual=True)

    with ThreadPoolExecutor(4) as pool:
        reservations = list(pool.map(reserve, range(4)))
    admitted = [r for r in reservations if isinstance(r, int)]
    assert len(admitted) == 1
    assert campaign.snapshot().usd == 0.003
    campaign.settle(admitted[0], 0.001, True)
    assert campaign.snapshot().credit == 0
    assert campaign.snapshot().usd == 0.001


def test_normal_admission_rejects_residual_before_any_call(residual_setup):
    settings, judge, store, calls = residual_setup
    with pytest.raises(ValueError, match="campaign"):
        Judging(settings, judge, None, store).findings([coverage_pair(1)])
    assert not calls


def test_phase_metadata_does_not_change_verdict_identity():
    pair = coverage_pair(1)
    residual = pair.model_copy(update={"lane": "exploration", "residual": True})
    assert evidence(pair, "judge:version") == evidence(residual, "judge:version")
    assert pair.context_hash == residual.context_hash and pair.key == residual.key


@pytest.mark.parametrize("limit", ["revision", "exploration", "campaign", "explicit"])
def test_residual_keeps_all_absolute_call_limits(residual_setup, tmp_path, limit):
    settings, judge, _, _ = residual_setup
    if limit == "explicit":
        settings.max_judgements = 1
    else:
        name = {"revision": "calls_per_revision", "exploration": "exploration_calls_per_revision", "campaign": "calls"}[
            limit
        ]
        setattr(settings.discovery, name, 1)
    path = tmp_path / "state.sqlite3"
    run = Run(session="feature", revision="tree1")
    campaign = CampaignStore(path, run)
    pair = coverage_pair(1).model_copy(update={"lane": "exploration"})
    first = campaign.reserve(pair, judge, settings, 0.001, residual=True)
    assert isinstance(first, int)
    campaign.settle(first, 0.0001, True)
    if limit == "campaign":
        campaign = CampaignStore(path, run.model_copy(update={"revision": "tree2"}))
    assert (
        campaign.reserve(
            coverage_pair(2).model_copy(update={"lane": "exploration"}), judge, settings, 0.001, residual=True
        )
        == "limit"
    )
    assert len(campaign.snapshot().attempts) == 1


@pytest.mark.parametrize("status", ["reserved", "failed"])
def test_unfinished_or_failed_prefix_blocks_residual_without_refunding(residual_setup, tmp_path, status):
    settings, judge, _, _ = residual_setup
    path = tmp_path / "state.sqlite3"
    run = Run(session="feature", revision="tree1")
    campaign = CampaignStore(path, run)
    pair = coverage_pair(1)
    hold = reservation_cost(judge, pair, settings)
    first = campaign.reserve(pair, judge, settings, hold)
    assert isinstance(first, int)
    if status == "failed":
        campaign.settle(first, None, False)
    reopened = CampaignStore(path, run)
    assert reopened.reserve(coverage_pair(2), judge, settings, hold, residual=True) is None
    assert reopened.reserve(pair, judge, settings, hold) is None
    assert reopened.snapshot().usd == hold
    # An immutable new revision may retry; the old hold and call remain charged.
    later = CampaignStore(path, run.model_copy(update={"revision": "tree2"}))
    assert later.reserve(pair, judge, settings, hold) is not None
    assert later.snapshot().usd == hold * 2


def test_residual_uses_actual_settlement_but_keeps_prior_charges(residual_setup, tmp_path):
    settings, judge, store, _ = residual_setup
    run = Run(repository="owner/repo", pull_request=7, revision="tree")
    baseline = coverage_pair(1)
    suffix = residual_pair(2)
    hold = reservation_cost(judge, baseline, settings)
    # Only one hold fits before settlement, but returned usage leaves room for another.
    prior = settings.budget.usd - hold - 0.0002
    store.add_spent(run, prior)
    judging = Judging(settings, judge, None, store)
    judging.campaign = CampaignStore(tmp_path / "state.sqlite3", run)
    found = judging.findings([suffix, baseline], run)
    state = judging.campaign.snapshot()
    assert all(f.verdict for f in found) and len(state.attempts) == 2
    assert state.prior_usd == prior and state.usd == pytest.approx(prior + 0.0003)
    assert state.usd <= settings.budget.usd


def test_unaffordable_baseline_still_bars_recovery(residual_setup, tmp_path):
    settings, _, _, calls = residual_setup
    settings.budget.usd = 0.0001
    suffix = residual_pair(2)
    report, state = check(residual_setup, tmp_path, [suffix, coverage_pair(1)])
    assert report.deferred == 2 and not calls and not state.attempts


def test_residual_exact_source_change_reopens_on_later_revision(residual_setup, tmp_path):
    pair = residual_pair(1)
    first, before = check(residual_setup, tmp_path, [pair])
    edited = pair.model_copy(update={"new": pair.new.model_copy(update={"code": pair.new.code + "\n# exact change"})})
    second, after = check(residual_setup, tmp_path, [edited], "tree2")
    assert first.visible and second.visible and not second.findings[0].cached
    assert len(after.attempts) == 2 and after.usd == pytest.approx(before.usd * 2)


def test_residual_artifact_requires_judging_side_opt_in(setup):
    settings, judge, store, calls = setup
    settings = settings.model_copy(update={"discovery": Discovery(enabled=True)})
    candidate = coverage_pair(1).model_copy(update={"residual": True})
    with pytest.raises(ValueError, match="opt-in"):
        Judging(settings, judge, None, store).findings([candidate])
    assert not calls


@pytest.mark.parametrize("lane", ["baseline", "exploration"])
def test_failed_protected_call_blocks_suffix_and_repeat_keeps_hold(residual_setup, tmp_path, lane):
    settings, _, store, calls = residual_setup
    judge = AnthropicJudge(
        api_key="test",
        http_client=claude({"error": {"type": "overloaded_error", "message": "unavailable"}}, calls, status=529),
        **settings.judge.options(),
    )
    setup = (settings, judge, store, calls)
    prefix = coverage_pair(1).model_copy(update={"lane": lane})
    suffix = residual_pair(2)
    first, state = check(setup, tmp_path, [prefix, suffix])
    assert len(calls) == len(state.attempts) == 1
    assert first.deferred == 2 and all(not f.budget_deferred for f in first.findings)
    assert state.usd == reservation_cost(judge, prefix, settings)
    _, repeat = check(setup, tmp_path, [prefix, suffix])
    assert repeat == state and len(calls) == 1


def test_old_campaign_and_candidates_default_to_protected_phase():
    old = Campaign.model_validate(
        {
            "schema_version": 1,
            "revisions": ["tree"],
            "attempts": [{"revision": "tree", "evidence": "exact", "lane": "exploration", "query": "q", "usd": 0.003}],
            "prior_usd": 0.01,
            "credit": 0.002,
        }
    )
    assert not old.attempts[0].residual and old.usd == pytest.approx(0.013)
    pair = coverage_pair(1).model_dump()
    pair.pop("residual")
    artifact = CandidatesFile.model_validate({"schema": 13, "candidates": [pair]})
    assert not artifact.candidates[0].residual


def test_example_resolves_complete_balanced_and_split_cli_reuses_campaign(repo, residual_setup, tmp_path):
    _, judge, _, calls = residual_setup
    example = Path(__file__).resolve().parents[1] / "examples/residual-discovery.toml"
    repo.write(".dry-lint.toml", example.read_text())
    repo.commit("opt in to residual recovery")
    configured = resolve(Settings.load(repo.root), {})
    assert [c.use for c in configured.discovery.comparers] == ["tfidf", "operation-blocks"]
    assert configured.discovery.residual_comparers[0].neighbours == 100
    candidates_path = tmp_path / "candidates.json"
    report_path = tmp_path / "report.json"
    common = ["--root", str(repo.root), "--store", str(tmp_path / "store")]
    assert main(["detect", *common, "--base", "main", "--out", str(candidates_path)]) == 0
    with patch.object(judging_module, "make_judge", return_value=judge):
        command = ["judge", *common, "--candidates", str(candidates_path), "--report", str(report_path)]
        assert main(command) == 1
        before = len(calls)
        assert main(command) == 1 and len(calls) == before


def test_no_judge_only_lists_residual_candidates(residual_setup):
    settings, _, store, calls = residual_setup
    pair = residual_pair(1)
    findings = Judging(settings, None, None, store).findings([pair])
    assert len(findings) == 1 and findings[0].verdict is None and not calls


@pytest.mark.parametrize("opt_in", [False, True])
def test_campaign_api_cannot_bypass_phase_opt_in(residual_setup, tmp_path, opt_in):
    settings, judge, _, _ = residual_setup
    campaign = CampaignStore(tmp_path / "state.sqlite3", Run(session="feature", revision="tree"))
    pair = residual_pair(1)
    if not opt_in:
        settings.discovery.residual_comparers = []
    with pytest.raises(ValueError, match="explicitly configured residual phase"):
        campaign.reserve(pair, judge, settings, 0.001, residual=not opt_in)
    assert not campaign.snapshot().attempts


def test_borrowed_capacity_is_unavailable_to_future_baseline(residual_setup, tmp_path):
    settings, judge, _, _ = residual_setup
    path = tmp_path / "state.sqlite3"
    campaign = CampaignStore(path, Run(session="feature", revision="tree1"))
    pair = coverage_pair(1).model_copy(update={"lane": "exploration"})
    # Ordinary exploration cannot consume the future-baseline reserve.
    borrowed = settings.budget.usd - 0.0001
    assert campaign.reserve(pair, judge, settings, borrowed) == "budget"
    attempt = campaign.reserve(pair, judge, settings, borrowed, residual=True)
    assert isinstance(attempt, int)
    campaign.settle(attempt, None, True)
    later = CampaignStore(path, Run(session="feature", revision="tree2"))
    baseline = coverage_pair(2)
    assert later.reserve(baseline, judge, settings, reservation_cost(judge, baseline, settings)) == "budget"
    assert later.snapshot().usd == borrowed
