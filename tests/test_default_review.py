"""Regressions from gigaverse-ai #3360 / AI-926: delegation is not cleanup duplication."""

import hashlib
import tomllib
from pathlib import Path

import pytest
from test_ledger import push
from test_report import finding, report

from dry_lint.baseline import Baseline, contract
from dry_lint.bench import as_function, load_gold
from dry_lint.cli import main
from dry_lint.commits import Journal, outcomes
from dry_lint.detector import Detector
from dry_lint.extractors import PythonExtractor
from dry_lint.goldens import settled
from dry_lint.judges.command import prompt
from dry_lint.ledger import PullLedger, render
from dry_lint.presets import resolve
from dry_lint.settings import Settings

from conftest import Repo, filler_module

GOLD = Path(__file__).parents[1] / "examples/oz-fixtures-gold.toml"


@pytest.mark.parametrize("gold", load_gold(GOLD))
def test_oz_fixtures_remain_retrievable_without_blanket_fixture_suppression(gold, tmp_path) -> None:
    # Both negative and positive controls must reach judging. Names/test paths are not exemptions.
    repo = Repo(tmp_path / "repo")
    repo.write("filler.py", filler_module())

    for side in (gold.new, gold.existing):
        path = repo.root / side.id.split("::")[0]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(side.code)
    repo.git("add", ".")
    settings = resolve(Settings(preset="balanced", exclude=[]), {})
    detector = Detector.for_repository(repo.root, settings)
    pairs = detector.candidates([f for f in detector.functions if f.name == "collection"])
    assert len(pairs) == 1 and not pairs[0].filtered
    assert pairs[0].new.code == as_function(gold.new, PythonExtractor()).code


def test_oz_excerpts_have_pinned_provenance_and_unchanged_hashes() -> None:
    rows = tomllib.loads(GOLD.read_text())["pair"]
    assert [row["label"] for row in rows].count("duplicate") == 6
    assert [row["label"] for row in rows].count("separate") == 6
    for row in rows:
        for side in (row["new"], row["existing"]):
            assert row["revision"] in side["source"]
            assert hashlib.sha256(side["code"].encode()).hexdigest() == side["sha256"]


def test_api_defaults_to_balanced_even_with_jev_credentials() -> None:
    settings = resolve(Settings(), {"ANTHROPIC_API_KEY": "test", "TYPESAFE_AI_API_KEY": "test"})
    assert settings.preset == "balanced"
    assert settings.judge.use == "anthropic" and settings.escalate is None
    assert settings.report_at == settings.fail_at == 0.5
    assert settings.discovery.enabled


def test_policy_migration_preserves_debt_and_rejects_new_allowances(tmp_path) -> None:
    repo = Repo(tmp_path / "repo")
    old = resolve(Settings(preset="agent"), {})
    debt = Baseline.start(report(finding("duplicate", score=0.99)), old)
    repo.write(".dry-lint/baseline.json", debt.model_dump_json())
    repo.git("add", ".")
    repo.git("commit", "-qm", "test: accept original debt")
    repo.write(".dry-lint.toml", 'preset = "balanced"\n')
    assert main(["baseline-migrate", "--root", str(repo.root)]) == 0
    new = resolve(Settings(preset="balanced"), {})
    migrated, original = Baseline.for_repository(repo.root, Path(".dry-lint/baseline.json"), new, base="HEAD")
    assert original == debt
    assert migrated.entries == debt.entries
    assert migrated.started_at == debt.started_at and migrated.checked_at == debt.checked_at
    assert migrated.contract == contract(new)
    assert main(["baseline-migrate", "--root", str(repo.root)]) == 0
    assert Baseline.read(repo.root / ".dry-lint/baseline.json", new) == migrated
    forged = migrated.model_copy(deep=True)
    forged.entries[0].hashes[next(iter(forged.entries[0].hashes))] = "different-code"
    with pytest.raises(ValueError, match="widen"):
        forged.validate_successor(debt)


def test_hook_inherits_repository_policy_instead_of_forcing_agent() -> None:
    hooks = (Path(__file__).parents[1] / ".pre-commit-hooks.yaml").read_text()
    assert "--preset agent" not in hooks


def test_replaced_prompt_names_use_the_canonical_shared_operation_policy() -> None:
    candidate = finding("duplicate").candidate
    expected = prompt(candidate, policy="shared-operations")
    assert prompt(candidate) == expected
    assert prompt(candidate, policy="concept") == expected
    assert prompt(candidate, policy="shared-operations-compact") == expected


def test_revert_or_missing_candidate_is_not_verified_cleanup() -> None:
    ledger = PullLedger().advance([push("a" * 40, finding("duplicate"))])
    ledger = ledger.advance([push("b" * 40)])  # reverting the changed fixture removes it from changed candidates
    assert ledger.count("kept-out") == 0
    assert ledger.count("not-reported") == 1
    assert ledger.contribution("repo", 3360)["kept_out"] == 0
    shown = render(ledger)
    assert "no longer reported" in shown
    assert "+1 pair cleaned up" not in shown
    assert settled("gigaverse-app/gigaverse-ai", 3360, ledger) == []


def test_hooks_and_old_trailers_cannot_turn_absence_into_cleanup() -> None:
    first = report(finding("duplicate"))
    key = first.findings[0].candidate.key
    staged = {"src/widgets/caption.py"}
    journal = Journal().observe(first, staged).observe(report(), staged)
    assert journal.pending[key].state == "not-reported"
    assert journal.pending[key].trailer().startswith("Dry-Lint-Not-Reported:")
    [old] = outcomes([f"Dry-Lint-Kept-Out: {key} clip ≈ shorten (4 lines)"])
    assert old.state == "not-reported"


def test_old_sticky_cleanup_claim_is_downgraded_without_losing_history() -> None:
    ledger = PullLedger().advance([push("a" * 40, finding("duplicate"))])
    saved = ledger.model_dump()
    saved["schema"] = 15
    pair = next(iter(saved["pairs"].values()))
    pair.update(state="kept-out", settled=2)
    restored = PullLedger.model_validate(saved)
    assert restored.count("not-reported") == 1
    assert restored.count("kept-out") == 0
    assert restored.tally == ledger.tally
