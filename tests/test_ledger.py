import pytest
from test_report import finding, pair

from dry_lint.costs import Spend
from dry_lint.ledger import Pair, PullLedger, RepositoryLedger, Tally, headline, render
from dry_lint.models import Candidate, Run
from dry_lint.report import Finding, JudgingSummary, Report
from dry_lint.settings import Settings

SETTINGS = Settings()


def push(head: str, *findings: Finding, filtered: list[Candidate] = (), usd: float | None = 0.002,
         calls: int = 0, changed: int = 3, cached: int = 0) -> Report:
    spend = [Spend(judge="jev", calls=len(findings), usd=usd)]
    if calls:
        spend.append(Spend(judge="claude-code", calls=calls, subscription=True))
    found = [f.model_copy(update={"cached": i < cached}) for i, f in enumerate(findings)]
    return Report.build(found, SETTINGS, filtered=filtered, run=Run(repository="o/r", pull_request=5, head=head),
                        changed=changed, judge="jev", functions=656, judging=JudgingSummary(spend=spend))


def test_a_run_adds_its_checks_judgments_and_cost_to_the_tally() -> None:
    tally = Tally.of(push("a" * 40, finding("duplicate"), finding("duplicate", existing="trim"), cached=1))
    assert tally == Tally(runs=1, functions=3, codebase=656, pairs=2, judgments=1, reused=1, usd=0.002)


def test_tallies_add_up_and_keep_the_largest_codebase() -> None:
    total = Tally(runs=1, functions=2, codebase=10, usd=0.1) + Tally(runs=2, functions=3, codebase=7, unpriced=True)
    assert (total.runs, total.functions, total.codebase, total.usd, total.unpriced) == (3, 5, 10, 0.1, True)


@pytest.mark.parametrize("tally, cost, spent", [
    (Tally(), "$0", "for $0 of judging"),
    (Tally(usd=0.0004), "under $0.001", "for under $0.001 of judging"),
    (Tally(usd=0.0123), "$0.012", "for $0.012 of judging"),
    (Tally(usd=0.84), "$0.84", "for $0.84 of judging"),
    (Tally(usd=1.5), "$1.50", "for $1.50 of judging"),
    (Tally(usd=0.01, subscription_calls=1), "$0.010 + 1 subscription call", "for $0.010 + 1 subscription call of judging"),
    (Tally(unpriced=True), "unknown", "with an unpriced judge"),
    (Tally(usd=0.002, unpriced=True), "$0.002", "for $0.002 of judging plus an unpriced judge"),
])  # fmt: skip
def test_cost_is_never_shown_as_zero_when_part_of_it_is_unknown(tally: Tally, cost: str, spent: str) -> None:
    assert tally.cost() == cost and tally.spent() == spent


def test_a_duplicate_reported_then_gone_is_kept_out_of_the_codebase() -> None:
    ledger = PullLedger().advance([push("a" * 40, finding("duplicate"))], run="1")
    assert ledger.count("open") == 1 and ledger.pushed == 1
    ledger = ledger.advance([push("b" * 40)], run="2")
    assert ledger.count("kept-out") == 1 and ledger.count("open") == 0
    assert ledger.pairs[pair().key] == Pair(new="clip", existing="shorten", found=1, state="kept-out", settled=2)


def test_a_duplicate_a_person_dismissed_is_not_counted_as_kept_out() -> None:
    ledger = PullLedger().advance([push("a" * 40, finding("duplicate"))], run="1")
    ledger = ledger.advance([push("b" * 40, filtered=[pair(filtered="inline distinct-from")])], run="2")
    assert ledger.count("dismissed") == 1 and ledger.count("kept-out") == 0


def test_a_person_dismissing_a_pair_after_it_went_away_takes_back_the_credit() -> None:
    ledger = PullLedger().advance([push("a" * 40, finding("duplicate"))], run="1").advance([push("b" * 40)], run="2")
    ledger = ledger.advance([push("c" * 40, filtered=[pair(filtered="inline distinct-from")])], run="3")
    ledger = ledger.advance([push("d" * 40, filtered=[pair(filtered="inline distinct-from")])], run="4")
    assert ledger.pairs[pair().key].state == "dismissed" and ledger.pairs[pair().key].settled == 3


def test_a_duplicate_left_unjudged_stays_open() -> None:
    ledger = PullLedger().advance([push("a" * 40, finding("duplicate"))], run="1")
    deferred = Finding(candidate=pair(), deferred=True)
    ledger = ledger.advance([push("b" * 40, deferred)], run="2")
    assert ledger.count("open") == 1


def test_a_duplicate_that_comes_back_is_open_again() -> None:
    ledger = PullLedger().advance([push("a" * 40, finding("duplicate"))], run="1")
    ledger = ledger.advance([push("b" * 40)], run="2").advance([push("c" * 40, finding("duplicate"))], run="3")
    assert ledger.pairs[pair().key].state == "open" and ledger.pairs[pair().key].settled is None


def test_a_run_counts_once_however_often_it_posts() -> None:
    once = PullLedger().advance([push("a" * 40, finding("duplicate"))], run="1")
    assert once.advance([push("a" * 40, finding("duplicate"))], run="1") is once
    assert once.advance([], run="2") is once


def test_a_rerun_of_the_same_commit_costs_again_but_checks_nothing_new() -> None:
    ledger = PullLedger().advance([push("a" * 40, finding("duplicate"))], run="1-1").advance([push("a" * 40, finding("duplicate"))],
                                                                                      run="1-2")
    assert ledger.pushed == 1 and len(ledger.pushes) == 1
    assert (ledger.tally.runs, ledger.tally.functions, ledger.tally.usd) == (2, 3, 0.004)
    assert ledger.pushes[0].tally == ledger.tally


def test_the_ledger_keeps_recent_pushes_and_runs_but_exact_totals() -> None:
    ledger = PullLedger()
    for n in range(40):
        ledger = ledger.advance([push(f"{n:040d}")], run=str(n))
    assert ledger.pushed == 40 and len(ledger.pushes) == 30 and len(ledger.runs) == 20
    assert ledger.tally.functions == 120
    assert "| 11 | `0000000` |" in render(ledger) and "| 10 |" not in render(ledger)


def test_the_ledger_round_trips_through_the_comment_body() -> None:
    ledger = PullLedger().advance([push("a" * 40, finding("duplicate"))], run="1")
    assert PullLedger.read(f"<!-- dry-lint -->\nreport\n{render(ledger)}\n<sub>source</sub>") == ledger


@pytest.mark.parametrize("body", ["no ledger here", '<!-- dry-lint-ledger {"pushed": "many"} -->'])
def test_a_missing_or_unreadable_ledger_is_none(body: str) -> None:
    assert PullLedger.read(body) is None


def test_the_headline_leads_with_what_was_kept_out_and_what_it_cost() -> None:
    ledger = PullLedger().advance([push("a" * 40, finding("duplicate"), finding("duplicate", existing="trim"))], run="1")
    assert headline(ledger) == ("**2 duplicates caught** for $0.002 of judging, on its first push. "
                                "Each one fixed here is kept out of the codebase.")
    ledger = ledger.advance([push("b" * 40, finding("duplicate", existing="trim"))], run="2")
    assert headline(ledger) == ("**1 duplicate kept out of the codebase** for $0.004 of judging, across 2 pushes. "
                                "1 duplicate still open.")
    ledger = ledger.advance([push("c" * 40)], run="3")
    assert headline(ledger) == "**2 duplicates kept out of the codebase** for $0.006 of judging, across 3 pushes."


def test_the_headline_of_a_clean_pull_request_says_how_much_was_checked() -> None:
    assert headline(PullLedger().advance([push("a" * 40)], run="1")) == (
        "**3 functions checked, nothing duplicated**, for $0.002 of judging, on its first push.")
    assert headline(PullLedger().advance([push("a" * 40, changed=0, usd=0.0)], run="1")) == (
        "**No changed functions to check yet**, on its first push.")


def test_a_first_clean_push_shows_figures_without_a_push_table() -> None:
    shown = render(PullLedger().advance([push("a" * 40)], run="1"))
    assert "This PR's cleanup basket" in shown and "| **0 pairs** | **0 pairs** | **0 pairs** |" in shown
    assert "spent-%240.002" in shown
    assert "Push by push" not in shown and "still_open" not in shown


def test_the_push_table_lists_every_push_and_every_pair_by_outcome() -> None:
    ledger = PullLedger().advance([push("a" * 40, finding("duplicate"), finding("duplicate", existing="trim"), finding("duplicate", existing="cut"), cached=1)],
                                  run="1")
    ledger = ledger.advance([push("b" * 40, finding("duplicate", existing="trim"), filtered=[pair("cut", filtered="inline ignore")])], run="2")
    shown = render(ledger)
    assert "| **1 pair** | **1 pair** | **1 pair** |" in shown
    assert "| 1 | `aaaaaaa` | 3 | 3 | 2 <sub>+1 reused</sub> | 3 | 0 | $0.002 |" in shown
    assert "| **2** | | **6** | **5** | **3** | | **1** | **$0.004** |" in shown
    kept, still, dismissed = (shown.index(f"{icon} `clip`") for icon in ("✅", "🟡", "⚪"))
    assert kept < still < dismissed
    assert "found in push 1, kept out in push 2" in shown and "dismissed by a person's decision in push 2" in shown


def test_a_concept_with_one_name_on_both_sides_is_named_once() -> None:
    assert Pair(new="clip", existing="clip", found=1).concept() == "`clip`"


def test_cleanup_progress_counts_pairs_across_commits_and_separates_dismissals() -> None:
    remaining = finding("duplicate", existing="trim")
    ledger = PullLedger().advance([push("a" * 40, finding("duplicate"), remaining,
                                        finding("duplicate", existing="cut"))], run="1")
    ledger = ledger.advance([push("b" * 40, remaining, filtered=[pair("cut", filtered="inline ignore")])], run="2")
    shown = render(ledger)
    assert "### 🧹 A little less lint" in shown
    assert "| 🧼 Cleaned up | 🧶 Still tangled | 🏷️ Dismissed |" in shown
    assert "| **1 pair** | **1 pair** | **1 pair** |" in shown
    assert "`bbbbbbb` · **+1 pair cleaned up**" in shown
    assert "Previously reported pairs no longer reported; dismissals do not count as cleanup." in shown
    assert "| 2 | `bbbbbbb` | 3 | 2 | 1 | 1 | **+1** | $0.002 |" in shown
    ledger = ledger.advance([push("c" * 40)], run="3")
    assert "| **2 pairs** | **0 pairs** | **1 pair** |" in render(ledger)
    assert "`ccccccc` · **+1 pair cleaned up**" in render(ledger)
    assert render(ledger.advance([push("c" * 40)], run="3")) == render(ledger)


def test_returning_and_unjudged_pairs_do_not_receive_cleanup_credit() -> None:
    ledger = PullLedger().advance([push("a" * 40, finding("duplicate"))], run="1")
    ledger = ledger.advance([push("b" * 40)], run="2")
    ledger = ledger.advance([push("c" * 40, finding("duplicate"))], run="3")
    ledger = ledger.advance([push("d" * 40, Finding(candidate=pair(), deferred=True))], run="4")
    shown = render(ledger)
    assert "| **0 pairs** | **1 pair** | **0 pairs** |" in shown
    assert "pair cleaned up**" not in shown


def test_the_repository_line_appears_once_a_merged_pull_request_is_counted() -> None:
    ledger = PullLedger().advance([push("a" * 40)], run="1")
    repository = RepositoryLedger(repository="o/r", since="2026-11-03T10:00:00+00:00")
    assert "🏆" not in render(ledger, repository)
    repository.add_pull(4, PullLedger().advance([push("a" * 40, finding("duplicate"))], run="1").advance([push("b" * 40)],
                                                                                                run="2"))
    assert repository.line() == ("🏆 `o/r` since Nov 3, 2026: **1 duplicate kept out of the codebase** across "
                                 "1 merged pull request, for $0.004 of judging.")
    assert f"<sub>{repository.line()}</sub>" in render(ledger, repository)


def test_the_repository_ledger_counts_each_pull_request_and_run_once() -> None:
    repository = RepositoryLedger()
    still_open = PullLedger().advance([push("a" * 40, finding("duplicate"))], run="1")
    dismissed = still_open.advance([push("b" * 40, filtered=[pair(filtered="inline ignore")])], run="2")
    for number, ledger in ((1, still_open), (2, dismissed), (1, dismissed)):
        repository.add_pull(number, ledger)
    for run in ("9-1", "9-1", ""):
        repository.add_run(Tally(runs=1, usd=0.5), run)
    assert repository.pulls == [1, 2] and repository.pushes == 3
    assert (repository.merged_open, repository.dismissed, repository.kept_out) == (1, 1, 0)
    assert repository.tally.runs == 5 and repository.runs == ["9-1"]
    assert repository.line().startswith("🏆 This repository since ")


@pytest.mark.parametrize("text", ["", "not json", '{"pulls": "many"}'])
def test_an_unreadable_repository_ledger_starts_again_today(text: str) -> None:
    ledger = RepositoryLedger.load(text, "o/r")
    assert ledger.repository == "o/r" and ledger.pulls == []


def test_a_saved_repository_ledger_loads_as_it_was() -> None:
    saved = RepositoryLedger(repository="o/r", pulls=[3], kept_out=2)
    assert RepositoryLedger.load(saved.model_dump_json(), "other/name") == saved
