"""What the pre-commit hook kept out before a commit, and the trailers that carry it to the pull request."""

from pathlib import Path

import pytest
from test_report import finding, pair, report

from dry_lint.cli import main
from dry_lint.commits import Journal, Outcome, outcomes, trailed

from conftest import TWIN, Repo, run_cli

KEY = finding("duplicate").candidate.key
STAGED = {"src/widgets/caption.py"}
REPAIR = "from src.text import shorten_text as preview_caption_text\n"


def blocked() -> Journal:
    return Journal().observe(report(finding("duplicate")), STAGED)


def test_a_reported_pair_is_blocked_with_its_names_and_file() -> None:
    [pair_] = blocked().blocked.values()
    assert (pair_.key, pair_.new, pair_.existing, pair_.path, pair_.state) == (
        KEY, "clip", "shorten", "src/widgets/caption.py", "blocked")
    assert blocked().pending == {}


@pytest.mark.parametrize("later, state", [
    (report(), "kept-out"),  # the copy is gone, by the rule the ledger uses across pushes
    (report(filtered=[pair(filtered="distinct-from")]), "dismissed"),  # a rule settled it
])  # fmt: skip
def test_a_blocked_pair_no_longer_reported_is_settled_for_the_next_commit(later, state) -> None:
    journal = blocked().observe(later, STAGED)
    assert journal.blocked == {} and journal.pending[KEY].state == state


@pytest.mark.parametrize("later, staged", [
    (report(finding(None)), STAGED),  # unjudged: nothing says the duplicate is gone
    (report(), {"src/other.py"}),  # its file was not staged: unstaging settles nothing
    (report(finding("duplicate")), STAGED),  # still reported
])  # fmt: skip
def test_only_a_check_that_staged_and_judged_the_pair_settles_it(later, staged) -> None:
    journal = blocked().observe(later, staged)
    assert KEY in journal.blocked and journal.pending == {}


def test_a_settled_pair_reported_again_is_no_longer_claimed_as_kept_out() -> None:
    settled = blocked().observe(report(), STAGED)
    again = settled.observe(report(finding("duplicate")), STAGED)
    assert again.pending == {} and KEY in again.blocked


def test_a_trailer_reads_back_as_the_outcome_it_wrote() -> None:
    kept = Outcome(key="ab7719f1ec3f9b70", new="clip", existing="shorten", lines=4, state="kept-out")
    dismissed = kept.model_copy(update={"key": "5c0e2f6a91d3b7e4", "state": "dismissed", "lines": 0})
    message = f"feat: x\n\nbody\n\nCo-Authored-By: A <a@b>\n{kept.trailer()}\n{dismissed.trailer()}\n"
    assert kept.trailer() == "Dry-Lint-Kept-Out: ab7719f1ec3f9b70 clip ≈ shorten (4 lines)"
    assert outcomes([message]) == [kept.model_copy(update={"path": ""}), dismissed]


def test_the_latest_commit_s_word_on_a_pair_wins_and_malformed_trailers_are_ignored() -> None:
    older = "fix: a\n\nDry-Lint-Kept-Out: ab7719f1ec3f9b70 clip ≈ shorten"
    newer = "fix: b\n\ndry-lint-dismissed: ab7719f1ec3f9b70 clip ≈ shorten\nDry-Lint-Kept-Out: not a pair"
    assert [(o.key, o.state) for o in outcomes([older, newer])] == [("ab7719f1ec3f9b70", "dismissed")]


def test_the_hook_carries_a_fixed_duplicate_into_the_commit_and_counts_it_in_its_header(
        repo: Repo, tmp_path: Path, blocking_twin_judge: str, capsys) -> None:
    repo.git("update-ref", "refs/remotes/origin/main", "main")
    judge = ("--judge", "command", "--judge-command", blocking_twin_judge, "--format", "text")
    repo.write("src/more.py", TWIN)
    repo.git("add", "src/more.py")
    assert run_cli(repo, tmp_path, "--staged", *judge) == 1
    assert "before commit on this branch" not in capsys.readouterr().out
    repo.write("src/more.py", REPAIR)
    repo.git("add", "src/more.py")
    assert run_cli(repo, tmp_path, "--staged", *judge) == 0
    assert "dry-lint before commit on this branch: 1 duplicate kept out, 0 look-alikes dismissed" in capsys.readouterr().out
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("feat: reuse the shared helper\n")
    assert main(["trailers", "--root", str(repo.root), str(message), "message"]) == 0
    assert main(["trailers", "--root", str(repo.root), str(message)]) == 0  # written once
    assert message.read_text().count("Dry-Lint-Kept-Out: ") == 1
    repo.git("commit", "-q", "-F", str(message))
    [kept] = trailed(repo.root, "origin/main")
    assert (kept.state, kept.new, kept.existing) == ("kept-out", "preview_caption_text", "shorten_text")
    assert Journal.load(repo.root) == Journal()
