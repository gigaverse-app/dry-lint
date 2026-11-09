import hashlib
import json

import pytest
from test_report import NEW, finding, pair

from dry_lint.commits import Outcome
from dry_lint.costs import Spend
from dry_lint.ledger import SPREAD, Backlog, Pair, PullLedger, RepositoryLedger, Tally, counter_key, headline, render
from dry_lint.models import Candidate, Run, Verdict, pair_key
from dry_lint.report import BacklogCleanup, Finding, JudgingSummary, Report
from dry_lint.settings import Settings

from conftest import function

SETTINGS = Settings()


def push(
    head: str,
    *findings: Finding,
    filtered: list[Candidate] = (),
    usd: float | None = 0.002,
    calls: int = 0,
    changed: int = 3,
    cached: int = 0,
) -> Report:
    spend = [Spend(judge="jev", calls=len(findings), usd=usd)]
    if calls:
        spend.append(Spend(judge="claude-code", calls=calls, subscription=True))
    found = [f.model_copy(update={"cached": i < cached}) for i, f in enumerate(findings)]
    return Report.build(
        found,
        SETTINGS,
        filtered=filtered,
        run=Run(repository="o/r", pull_request=5, head=head),
        changed=changed,
        judge="jev",
        functions=656,
        judging=JudgingSummary(spend=spend),
    )


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


def unspread(markdown: str) -> str:
    return markdown.replace(SPREAD, "")


def test_the_cleanup_basket_spans_the_comment_with_one_spacer_per_count() -> None:
    shown = render(PullLedger().advance([push("a" * 40, finding("duplicate"))], run="1"))
    [row] = [line for line in shown.splitlines() if SPREAD in line]
    assert row.count(SPREAD) == 3 and [cell.strip() for cell in row.strip("| ").split(" | ")] == [
        f"{SPREAD}**0 pairs**",
        f"{SPREAD}**1 pair**",
        f"{SPREAD}**0 pairs**",
    ]


def test_a_duplicate_reported_then_gone_is_kept_out_of_the_codebase() -> None:
    ledger = PullLedger().advance([push("a" * 40, finding("duplicate"))], run="1")
    assert ledger.count("open") == 1 and ledger.pushed == 1
    ledger = ledger.advance([push("b" * 40)], run="2")
    assert ledger.count("kept-out") == 1 and ledger.count("open") == 0
    assert ledger.pairs[pair().key] == Pair(
        new="clip",
        existing="shorten",
        found=1,
        state="kept-out",
        settled=2,
        scope="",
        lines=2,
        evidence=ledger.pairs[pair().key].evidence,
    )


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


def test_only_the_scope_that_found_a_duplicate_can_keep_it_out() -> None:
    """
    INVARIANT: a duplicate counts as kept out only when the scope that found it reported again without it. A run in
    which that scope did not complete (only the local check reported) is no evidence the duplicate is gone.
    """
    ledger = PullLedger().advance(
        [push("a" * 40), push("a" * 40, finding("duplicate"))], run="1", scopes=["local", "cross-repository"]
    )
    assert ledger.pairs[pair().key].scope == "cross-repository"
    partial = ledger.advance([push("b" * 40)], run="2", scopes=["local"])
    assert partial.count("open") == 1 and partial.count("kept-out") == 0
    assert headline(partial).startswith("**1 duplicate caught**")
    complete = partial.advance([push("c" * 40), push("c" * 40)], run="3", scopes=["local", "cross-repository"])
    assert complete.pairs[pair().key] == Pair(
        new="clip",
        existing="shorten",
        found=1,
        state="kept-out",
        settled=3,
        scope="cross-repository",
        lines=2,
        evidence=ledger.pairs[pair().key].evidence,
    )


def test_a_duplicate_from_a_ledger_saved_before_scopes_stays_open_until_there_is_evidence() -> None:
    """
    INVARIANT: a pair whose scope is unknown is never counted as kept out by its absence: the run may not have
    included the check that found it. It settles only once a push reports it again (naming its scope) or a person
    dismisses it.
    """
    saved = json.loads(PullLedger().advance([push("a" * 40, finding("duplicate"))], run="1").model_dump_json())
    for stored in saved["pairs"].values():
        del stored["scope"]
    legacy = PullLedger.read(f"<!-- dry-lint-ledger {json.dumps(saved)} -->")
    assert legacy.pairs[pair().key].scope is None
    partial = legacy.advance([push("b" * 40)], run="2", scopes=["local"])
    assert (partial.count("open"), partial.count("kept-out")) == (1, 0)
    assert headline(partial).startswith("**1 duplicate caught**")
    assert partial.advance([push("c" * 40)], run="3").count("kept-out") == 0
    reported = partial.advance(
        [push("d" * 40), push("d" * 40, finding("duplicate"))], run="4", scopes=["local", "cross-repository"]
    )
    assert reported.pairs[pair().key].scope == "cross-repository"
    settled = reported.advance([push("e" * 40), push("e" * 40)], run="5", scopes=["local", "cross-repository"])
    assert settled.pairs[pair().key].state == "kept-out"
    dismissed = partial.advance([push("f" * 40, filtered=[pair(filtered="inline distinct-from")])], run="6")
    assert dismissed.pairs[pair().key].state == "dismissed"


def test_a_duplicate_that_comes_back_is_open_again() -> None:
    ledger = PullLedger().advance([push("a" * 40, finding("duplicate"))], run="1")
    ledger = ledger.advance([push("b" * 40)], run="2").advance([push("c" * 40, finding("duplicate"))], run="3")
    assert ledger.pairs[pair().key].state == "open" and ledger.pairs[pair().key].settled is None


def test_a_run_counts_once_however_often_it_posts() -> None:
    once = PullLedger().advance([push("a" * 40, finding("duplicate"))], run="1")
    assert once.advance([push("a" * 40, finding("duplicate"))], run="1") is once
    assert once.advance([], run="2") is once


def test_a_rerun_of_the_same_commit_costs_again_but_checks_nothing_new() -> None:
    ledger = (
        PullLedger()
        .advance([push("a" * 40, finding("duplicate"))], run="1-1")
        .advance([push("a" * 40, finding("duplicate"))], run="1-2")
    )
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
    ledger = PullLedger().advance(
        [push("a" * 40, finding("duplicate"), finding("duplicate", existing="trim"))], run="1"
    )
    assert headline(ledger) == (
        "**2 duplicates caught** for $0.002 of judging, on its first checked push. "
        "Each one fixed here is kept out of the codebase."
    )
    ledger = ledger.advance([push("b" * 40, finding("duplicate", existing="trim"))], run="2")
    assert headline(ledger) == (
        "**1 duplicate kept out of the codebase** for $0.004 of judging, across 2 checked pushes. "
        "1 duplicate still reported."
    )
    ledger = ledger.advance([push("c" * 40)], run="3")
    assert headline(ledger) == (
        "**2 duplicates kept out of the codebase** for $0.006 of judging, across 3 checked pushes."
    )


def test_the_headline_of_a_clean_pull_request_says_how_much_was_checked() -> None:
    assert headline(PullLedger().advance([push("a" * 40)], run="1")) == (
        "**3 functions checked, nothing duplicated**, for $0.002 of judging, on its first checked push."
    )
    assert headline(PullLedger().advance([push("a" * 40, changed=0, usd=0.0)], run="1")) == (
        "**No changed functions to check yet**, on its first checked push."
    )


def test_a_first_clean_push_shows_figures_without_a_push_table() -> None:
    shown = render(PullLedger().advance([push("a" * 40)], run="1"))
    assert "This PR's cleanup basket" in shown and "| **0 pairs** | **0 pairs** | **0 pairs** |" in unspread(shown)
    assert "spent-%240.002" in shown
    visible, hidden = shown.split("<details>", 1)
    assert "spent-" not in visible and "Previously reported" not in visible
    assert "History and check stats" in hidden and "spent-%240.002" in hidden
    assert "Push by push" not in shown and "still_open" not in shown


def test_the_push_table_lists_every_push_and_every_pair_by_outcome() -> None:
    ledger = PullLedger().advance(
        [
            push(
                "a" * 40,
                finding("duplicate"),
                finding("duplicate", existing="trim"),
                finding("duplicate", existing="cut"),
                cached=1,
            )
        ],
        run="1",
    )
    ledger = ledger.advance(
        [push("b" * 40, finding("duplicate", existing="trim"), filtered=[pair("cut", filtered="inline ignore")])],
        run="2",
    )
    shown = render(ledger)
    assert "| **1 pair** | **1 pair** | **1 pair** |" in unspread(shown)
    assert "| 1 | `aaaaaaa` | 3 | 3 | 2 <sub>+1 reused</sub> | 3 | 0 | $0.002 |" in shown
    assert "| **2** | | **6** | **5** | **3** | | **1** | **$0.004** |" in shown
    kept, still, dismissed = (shown.index(f"{icon} `clip`") for icon in ("✅", "🟡", "⚪"))
    assert kept < still < dismissed
    assert "found in push 1, kept out in push 2" in shown and "dismissed by a person's decision in push 2" in shown
    assert "`clip` ≈ `trim` · found in push 1, still reported" in shown


def test_the_history_counts_checked_pushes_and_says_what_an_open_pair_means() -> None:
    """
    A push before dry-lint's workflow existed has no run, so the first push the comment sees may be the pull
    request's second: it says "checked push". An open pair is the one the findings below mark as blocking, so the
    history says what "still reported" means rather than looking like a second, softer verdict.
    """
    ledger = PullLedger().advance([push("a" * 40, finding("duplicate"))], run="1")
    ledger = ledger.advance([push("b" * 40, finding("duplicate"))], run="2")
    shown = render(ledger)
    assert "checked_pushes-2" in shown and "| Checked push | Commit |" in shown
    assert "Push numbers count only the pushes dry-lint checked." in shown
    assert "🟡 still reported means the latest checked push reports the pair" in shown
    assert "the findings below say whether it blocks this check" in shown
    assert "still open" not in shown


def test_a_concept_with_one_name_on_both_sides_is_named_once() -> None:
    assert Pair(new="clip", existing="clip", found=1).concept() == "`clip`"


def test_cleanup_progress_counts_pairs_across_commits_and_separates_dismissals() -> None:
    remaining = finding("duplicate", existing="trim")
    ledger = PullLedger().advance(
        [push("a" * 40, finding("duplicate"), remaining, finding("duplicate", existing="cut"))], run="1"
    )
    ledger = ledger.advance([push("b" * 40, remaining, filtered=[pair("cut", filtered="inline ignore")])], run="2")
    shown = render(ledger)
    assert "### 🧹 A little less lint" in shown
    assert "| 🧼 Cleaned up | 🧶 Still tangled | 🏷️ Dismissed |" in shown
    assert "| **1 pair** | **1 pair** | **1 pair** |" in unspread(shown)
    assert "`bbbbbbb` · **+1 pair cleaned up**" in shown
    assert "dismissals do not count as cleanup." in shown and "by the pre-commit hook before commit" in shown
    assert "| 2 | `bbbbbbb` | 3 | 2 | 1 | 1 | **+1** | $0.002 |" in shown
    ledger = ledger.advance([push("c" * 40)], run="3")
    assert "| **2 pairs** | **0 pairs** | **1 pair** |" in unspread(render(ledger))
    assert "`ccccccc` · **+1 pair cleaned up**" in render(ledger)
    assert render(ledger.advance([push("c" * 40)], run="3")) == render(ledger)


def test_returning_and_unjudged_pairs_do_not_receive_cleanup_credit() -> None:
    ledger = PullLedger().advance([push("a" * 40, finding("duplicate"))], run="1")
    ledger = ledger.advance([push("b" * 40)], run="2")
    ledger = ledger.advance([push("c" * 40, finding("duplicate"))], run="3")
    ledger = ledger.advance([push("d" * 40, Finding(candidate=pair(), deferred=True))], run="4")
    shown = render(ledger)
    assert "| **0 pairs** | **1 pair** | **0 pairs** |" in unspread(shown)
    assert "pair cleaned up**" not in shown


def test_the_repository_line_appears_once_a_merged_pull_request_is_counted() -> None:
    ledger = PullLedger().advance([push("a" * 40)], run="1")
    repository = RepositoryLedger(repository="o/r", since="2026-11-03T10:00:00+00:00")
    assert "🏆" not in render(ledger, repository)
    repository.add_pull(
        4, PullLedger().advance([push("a" * 40, finding("duplicate"))], run="1").advance([push("b" * 40)], run="2")
    )
    assert repository.line() == (
        "🏆 `o/r` since Nov 3, 2026: **1 duplicate kept out of the codebase** across "
        "1 merged pull request, for $0.004 of judging."
    )
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


def rewrite(label: str, existing: str) -> Finding:
    """A pair whose existing side was written differently, not copied: its structure hash differs."""
    source = f"def {existing}(text, limit):\n    if len(text) <= limit:\n        return text\n    return text[:limit]\n"
    return Finding(
        candidate=Candidate(new=NEW, existing=function("src/text.py", source), similarity=0.6, comparer="tfidf:1"),
        verdict=Verdict(label=label, score=0.9, owner="existing", judge="jev", judge_version="v"),
    )


def test_the_counter_hears_how_large_drifted_and_rewritten_the_duplicates_kept_out_were() -> None:
    first = push(
        "a" * 40, finding("duplicate", existing="copy"), rewrite("drifted", "drift"), rewrite("duplicate", "kept")
    )
    ledger = PullLedger().advance([first], run="1").advance([push("b" * 40, rewrite("duplicate", "kept"))], run="2")
    sent = ledger.contribution("o/r", 7)
    assert ledger.count("kept-out") == 2 and ledger.count("open") == 1
    assert (sent["drifted_kept_out"], sent["rewrites_kept_out"], sent["lines_kept_out"]) == (1, 1, 2 + 2)
    assert (sent["pairs"], sent["reused"]) == (ledger.tally.pairs, ledger.tally.reused) == (4, 0)
    assert sent["measured_kept_out"] == 2


def test_a_duplicate_reported_before_an_upgrade_is_kept_out_but_never_claimed_as_measured() -> None:
    ledger = PullLedger().advance([push("a" * 40, finding("duplicate"))], run="1")
    ledger.pairs[pair().key].lines = 0  # what a version without details recorded
    ledger = ledger.advance([push("b" * 40)], run="2")
    sent = ledger.contribution("o/r", 7)
    assert (sent["kept_out"], sent["measured_kept_out"], sent["lines_kept_out"], sent["rewrites_kept_out"]) == (
        1,
        0,
        0,
        0,
    )


def test_a_renamed_copy_is_not_a_rewrite_and_a_pair_without_hashes_is_not_counted_as_one() -> None:
    copied = finding("duplicate")
    unhashed = copied.model_copy(
        update={"candidate": copied.candidate.model_copy(update={"new": NEW.model_copy(update={"hash": ""})})}
    )
    for reported in (copied, unhashed):
        ledger = PullLedger().advance([push("a" * 40, reported)], run="1")
        assert not ledger.pairs[reported.candidate.key].rewrite


@pytest.mark.parametrize("text", ["", "not json", '{"pulls": "many"}'])
def test_an_unreadable_repository_ledger_starts_again_today(text: str) -> None:
    ledger = RepositoryLedger.load(text, "o/r")
    assert ledger.repository == "o/r" and ledger.pulls == []


def test_a_saved_repository_ledger_loads_as_it_was() -> None:
    saved = RepositoryLedger(repository="o/r", pulls=[3], kept_out=2)
    assert RepositoryLedger.load(saved.model_dump_json(), "other/name") == saved


def test_the_counter_key_comes_from_the_repository_id_alone() -> None:
    key = counter_key("4242")
    assert key == counter_key(" 4242 ") and len(key) == 64 and key != counter_key("4243")
    assert key != hashlib.sha256(b"acme/shop").hexdigest()  # a guessable name never leads to it


HOOKED = Outcome(key="ab7719f1ec3f9b70", new="format_price", existing="money", lines=6, state="kept-out")


def test_what_the_pre_commit_hook_kept_out_counts_as_kept_out_of_the_codebase() -> None:
    dismissed = HOOKED.model_copy(update={"key": "5c0e2f6a91d3b7e4", "state": "dismissed"})
    ledger = PullLedger().advance([push("a" * 40)], run="1", before_commit=[HOOKED, dismissed])
    assert ledger.pairs[HOOKED.key] == Pair(
        new="format_price", existing="money", found=1, state="kept-out", settled=1, lines=6, before_commit=True
    )
    assert (ledger.count("kept-out"), ledger.count("dismissed")) == (1, 1)
    sent = ledger.contribution("o/r", 7)
    assert (sent["kept_out"], sent["caught"], sent["dismissed"], sent["lines_kept_out"]) == (1, 2, 1, 6)
    assert "(1 by the pre-commit hook, before commit)" in headline(ledger)
    assert "✅ `format_price` ≈ `money` · kept out before commit, by the pre-commit hook" in render(ledger)
    assert "⚪ `format_price` ≈ `money` · dismissed by a person's decision before commit" in render(ledger)


def test_what_ci_saw_of_a_pair_wins_over_a_commit_trailer() -> None:
    claimed = Outcome(key=pair().key, new="clip", existing="shorten", state="kept-out")
    still = PullLedger().advance([push("a" * 40, finding("duplicate"))], run="1", before_commit=[claimed])
    assert still.pairs[pair().key].state == "open" and not still.pairs[pair().key].before_commit
    hooked = PullLedger().advance([push("a" * 40)], run="1", before_commit=[claimed])
    back = hooked.advance([push("b" * 40, finding("duplicate"))], run="2", before_commit=[claimed])
    assert back.pairs[pair().key].state == "open" and not back.pairs[pair().key].before_commit


def cleaned(report: Report, *items: BacklogCleanup) -> Report:
    """The report of a baselined check that saw `items` cleaned up."""
    return report.model_copy(update={"backlog": list(items)})


TRIM = BacklogCleanup(new="src/a.py::trim", existing="src/b.py::strip", how="removed")
CLIP = BacklogCleanup(new="src/widgets/caption.py::clip", existing="src/text.py::shorten", how="separate")


def test_accepted_debt_cleaned_up_is_backlog_and_never_kept_out() -> None:
    ledger = PullLedger().advance([cleaned(push("a" * 40), TRIM)], run="1")
    assert ledger.count("kept-out") == 0 and list(ledger.backlog.values()) == [
        Backlog(new="src/a.py::trim", existing="src/b.py::strip", how="removed", settled=1)
    ]
    assert ledger.contribution("k", 5)["kept_out"] == 0  # remediation is not prevention
    shown = unspread(render(ledger))
    assert "### 🧹 A little less lint" in shown
    assert "| **1 pair**<br><sub>1 from the accepted backlog</sub> | **0 pairs** | **0 pairs** |" in shown
    assert "- ✅ `trim` ≈ `strip` · accepted backlog, cleaned up in push 1: one side removed" in shown
    assert headline(ledger) == (
        "**1 accepted backlog pair cleaned up** for $0.002 of judging, on its first checked push."
    )


def test_each_baseline_check_restates_the_backlog() -> None:
    ledger = PullLedger().advance([cleaned(push("a" * 40), TRIM)], run="1")
    ledger = ledger.advance([push("b" * 40)], run="2")  # no baseline checked: no claim either way
    assert list(ledger.backlog) == [pair_key(TRIM.new, TRIM.existing)]
    ledger = ledger.advance([cleaned(push("c" * 40), TRIM, CLIP)], run="3")
    assert {item.new: item.settled for item in ledger.backlog.values()} == {TRIM.new: 1, CLIP.new: 3}
    ledger = ledger.advance([cleaned(push("d" * 40), CLIP)], run="4")  # the removed side came back
    assert [item.new for item in ledger.backlog.values()] == [CLIP.new]


def test_accepted_debt_a_push_reported_is_counted_once_as_backlog() -> None:
    ledger = PullLedger().advance([push("a" * 40, finding("duplicate"))], run="1")  # an edit voided its allowance
    ledger = ledger.advance([cleaned(push("b" * 40, finding("separate")), CLIP)], run="2")
    assert ledger.count("kept-out") == 0 and ledger.count("open") == 0 and len(ledger.backlog) == 1
    shown = unspread(render(ledger))
    assert "| **1 pair**<br><sub>1 from the accepted backlog</sub> |" in shown
    assert "accepted backlog, found in push 1, cleaned up in push 2: the judge now finds them separate" in shown
    assert "| 2 | `bbbbbbb` | 3 | 1 | 1 | 0 | **+1** |" in shown


def test_accepted_debt_a_push_already_cleared_keeps_that_push() -> None:
    ledger = PullLedger().advance([push("a" * 40, finding("duplicate"))], run="1")
    ledger = ledger.advance([push("b" * 40)], run="2")  # cleared before any baseline check credited it
    ledger = ledger.advance([cleaned(push("c" * 40), CLIP)], run="3")
    assert [item.settled for item in ledger.backlog.values()] == [2]


def test_the_basket_splits_backlog_from_duplicates_found_here() -> None:
    ledger = PullLedger().advance([push("a" * 40, finding("duplicate"))], run="1")
    ledger = ledger.advance([cleaned(push("b" * 40), TRIM)], run="2")
    shown = unspread(render(ledger))
    assert "| **2 pairs**<br><sub>1 from the accepted backlog · 1 found here</sub> |" in shown
    assert "| **2** | | **6** | **1** | **1** | | **2** |" in shown
