"""Each review surface distinguishes executable duplication from model ownership review."""

import pytest
from test_report import finding, report

from dry_lint.commits import Journal
from dry_lint.costs import Spend
from dry_lint.ledger import PullLedger, Tally
from dry_lint.model_review import combine
from dry_lint.models import Declaration
from dry_lint.report import JudgingSummary, as_markdown, as_text


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
