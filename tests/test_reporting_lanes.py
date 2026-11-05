"""Each review surface distinguishes executable duplication from model ownership review."""

import pytest
from test_report import finding, report

from dry_lint.baseline import Baseline
from dry_lint.cli import main
from dry_lint.commits import Journal, outcomes
from dry_lint.costs import Spend
from dry_lint.ledger import PullLedger, Tally, render
from dry_lint.model_review import combine, profile
from dry_lint.models import Declaration
from dry_lint.report import BacklogCleanup, JudgingSummary, as_markdown, as_text
from dry_lint.settings import Settings

from conftest import Repo


def model_finding():
    proposed = finding("separate", score=0.1)
    candidate = proposed.candidate.model_copy(deep=True)
    for side, name in ((candidate.new, "Payload"), (candidate.existing, "Receipt")):
        side.name = name
        side.declaration = Declaration(kind="pydantic", fields={"url": "str", "size": "int"})
    return proposed.model_copy(update={"candidate": candidate, "source_review": True})


def combined(*functions, models=None):
    models = [model_finding()] if models is None else models
    model_report = report(*models).model_copy(
        update={
            "changed": 1,
            "functions": 9,
            "judging": JudgingSummary(judge="jev-models", spend=[Spend(judge="jev-models", calls=1, usd=0.03)]),
        }
    )
    return combine(report(*functions), model_report, None)


def test_function_volume_cannot_hide_model_ownership_work():
    rendered = as_markdown(combined(*(finding("duplicate", existing=f"copy{i}") for i in range(12))), max_findings=2)
    assert "#### Functions" in rendered and "#### Models" in rendered
    assert "Payload" in rendered and "Receipt" in rendered
    assert "review required" in rendered
    assert rendered.count("<!-- dry-lint -->") == 1
    assert "nested types" in rendered and "repository" in rendered


def test_hook_names_both_lanes_and_skipped_is_not_clean():
    rendered = as_text(combined(finding("duplicate")))
    assert "Functions" in rendered and "Models" in rendered
    skipped = as_markdown(report())
    assert "Models: not checked" in skipped


def test_model_cost_and_coverage_are_included_once_even_on_rerun():
    mixed = combined()
    mixed.judging = JudgingSummary(spend=[Spend(judge="jev", calls=1, usd=0.02)])
    tally = Tally.of(mixed)
    assert tally.usd == pytest.approx(0.05)
    assert tally.models == 1 and tally.model_codebase == 9
    assert (tally + tally.again()).models == 1
    assert (tally + tally.again()).usd == pytest.approx(0.10)


def test_unpriced_model_ranking_keeps_known_function_cost():
    mixed = combined()
    mixed.judging = JudgingSummary(spend=[Spend(judge="jev", calls=1, usd=0.02)])
    mixed.model_judging.spend[0].usd = None
    tally = Tally.of(mixed)
    assert tally.unpriced and tally.usd == 0.02


def test_skipping_model_pass_cannot_resolve_its_review_in_hook_or_sticky():
    initial = combined()
    key = initial.findings[0].candidate.key
    staged = {initial.findings[0].candidate.new.path}
    journal = Journal().observe(initial, staged)
    ledger = PullLedger().advance([initial], run="1")
    assert key in journal.blocked and key in ledger.pairs
    skipped = report()
    assert key in journal.observe(skipped, staged).blocked
    assert ledger.advance([skipped], run="2").pairs[key].state == "open"
    assert ledger.count("open") == 0  # model review is never counted as a confirmed duplicate
    reviewed = combined(models=[])
    assert journal.observe(reviewed, staged).pending[key].state == "kept-out"
    assert ledger.advance([reviewed], run="3").pairs[key].state == "kept-out"


def test_progress_refresh_reads_both_baselines_without_rejudging_or_mutating_debt(tmp_path):
    repo = Repo(tmp_path / "progress")
    repo.write("README.md", "# Keep this introduction\n")
    repo.write(".dry-lint.toml", '[models]\nbaseline = ".dry-lint/custom-models.json"\n')
    functions = Baseline.start(report(finding("duplicate", score=0.99)), Settings())
    models = Baseline.start(report(finding("duplicate", score=0.99, existing="model_copy")), profile(Settings()))
    repo.write(".dry-lint/baseline.json", functions.model_dump_json())
    repo.write(".dry-lint/custom-models.json", models.model_dump_json())
    before = {p: p.read_bytes() for p in (repo.root / ".dry-lint").glob("*.json")}
    args = [
        "progress",
        "--root",
        str(repo.root),
        "--readme",
        "README.md",
        "--repository",
        "acme/widgets",
        "--repository-id",
        "4242",
    ]
    assert main(args) == 0
    text = (repo.root / "README.md").read_text()
    assert "# Keep this introduction" in text
    assert "| Functions | 1 | 0 | 0 |" in text
    assert "| Models | 1 | 0 | 0 |" in text
    assert "](.dry-lint/custom-models.json)" in text
    assert "models_remaining=1" in text and "models_cleaned=0" in text
    assert main(args) == 0 and (repo.root / "README.md").read_text() == text
    assert all(p.read_bytes() == data for p, data in before.items())


def test_readme_missing_model_baseline_is_unknown_even_when_function_debt_is_zero():
    baseline = Baseline.start(report(), Settings())
    shown = baseline.markdown("acme/widgets", "main", ".dry-lint")
    assert "| Models | Not initialized |" in shown


def test_model_hook_trailer_roundtrip_preserves_review_semantics_and_excludes_prevention_credit():
    initial = combined()
    staged = {initial.findings[0].candidate.new.path}
    journal = Journal().observe(initial, staged).observe(combined(models=[]), staged)
    [settled] = journal.pending.values()
    carried = outcomes([settled.trailer()])
    assert carried[0].kind == "model" and carried[0].state == "kept-out"
    ledger = PullLedger().advance([combined(models=[])], before_commit=carried)
    assert ledger.contribution("a" * 64, 1)["kept_out"] == 0
    assert ledger.contribution("a" * 64, 1)["caught"] == 0
    assert "model review resolved" in render(ledger)


def test_skipping_models_preserves_previous_model_debt_retirement_without_function_credit():
    current = combined(models=[])
    current.model_backlog = [BacklogCleanup(new="a.py::A", existing="b.py::B", how="removed", kind="model")]
    ledger = PullLedger().advance([current], run="1")
    skipped = report().model_copy(update={"backlog": []})
    later = ledger.advance([skipped], run="2")
    assert later.backlog_count("model") == 1 and later.backlog_count() == 0
    assert "1 reviewed model debt pairs retired" in render(later)
    assert later.contribution("a" * 64, 1)["kept_out"] == 0


def test_no_ranking_key_still_displays_required_source_review():
    current = combined()
    current.model_judging.judge = None
    shown = as_markdown(current)
    assert "Payload" in shown and "review required" in shown
    assert "pairs have not been assessed" not in shown


def test_unranked_model_inventory_is_visible_without_claiming_confirmed_duplication():
    proposed = model_finding().model_copy(update={"verdict": None, "source_review": False})
    current = combined(models=[proposed])
    current.model_judging.judge = None
    shown = as_markdown(current)
    assert "Payload" in shown and "Receipt" in shown
    assert "1 model candidate for ownership review" in shown
    assert "structural candidates, not confirmed duplicates" in shown


def test_model_policy_dismissal_is_distinct_from_resolved_review():
    current = combined()
    proposed = current.findings[0].candidate
    later = combined(models=[])
    later.filtered = [proposed.model_copy(update={"filtered": "independent prompt contract"})]
    ledger = PullLedger().advance([current], run="1").advance([later], run="2")
    assert ledger.count("dismissed", "model") == 1
    assert ledger.count("kept-out", "model") == 0
    assert ledger.contribution("a" * 64, 1)["dismissed"] == 0


def test_clean_model_pass_says_review_complete_and_keeps_one_sticky_marker():
    shown = as_markdown(combined(models=[]))
    assert "No unresolved model candidates" in shown
    assert shown.count("<!-- dry-lint clean -->") == 1
    assert "9 models" in shown
    assert "ranking only" in shown


def test_model_ratchet_refreshes_readme_and_missing_readme_option_is_actionable(tmp_path, capsys):
    repo = Repo(tmp_path / "empty")
    repo.write("README.md", "# Library\n")
    repo.write(".dry-lint.toml", '[models]\nbaseline = ".dry-lint/models.json"\n')
    settings = Settings.load(repo.root)
    repo.write(".dry-lint/baseline.json", Baseline.start(report(), settings).model_dump_json())
    repo.write(".dry-lint/models.json", Baseline.start(report(), profile(settings)).model_dump_json())
    repo.commit()
    assert (
        main(["model-baseline", "--root", str(repo.root), "--update", "--readme", "README.md", "--repository", "a/b"])
        == 0
    )
    assert "| Models | 0 | 0 | 0 |" in (repo.root / "README.md").read_text()
    assert main(["progress", "--root", str(repo.root)]) == 2
    assert "progress requires --readme" in capsys.readouterr().err
