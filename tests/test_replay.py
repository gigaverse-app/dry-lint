"""`dry-lint bench --replay`: what `check` would have done on each recent commit, without touching your checkout."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dry_lint.functions import repository_functions
from dry_lint.plugins import load
from dry_lint.replay import Replay, replay
from dry_lint.settings import PluginChoice, Settings
from dry_lint.store import DirectoryStore, VerdictStore

from conftest import EXISTING, TWIN, Repo, filler_module, judge_calls, run_cli


@pytest.fixture
def history(tmp_path: Path) -> Repo:
    """On main, oldest first: a helper and fillers; a twin of the helper; a docs-only change."""
    repo = Repo(tmp_path / "repo")
    repo.write("src/text.py", EXISTING)
    repo.write("src/filler.py", filler_module())
    repo.commit("helper")
    repo.write("src/widgets/caption.py", TWIN)
    repo.commit("twin")
    repo.write("README.md", "docs\n")
    repo.commit("docs")
    return repo


def judged_by(command: str, **thresholds: float) -> Settings:
    return Settings(judge=PluginChoice(use="command", command=command), **thresholds)


def worktrees(repo: Repo) -> list[str]:
    return [line for line in repo.git("worktree", "list", "--porcelain").splitlines() if line.startswith("worktree ")]


def test_each_commit_is_checked_against_its_parent_oldest_first(history, tmp_path, blocking_twin_judge) -> None:
    result = replay(history.root, judged_by(blocking_twin_judge), VerdictStore(DirectoryStore(tmp_path / "store")), 10, "main")
    subjects = [c.subject for c in result.commits]
    assert subjects == ["helper", "twin", "docs"]
    root, twin, docs = result.commits
    assert root.report.changed == 0 and root.report.findings == []  # no parent to compare with
    assert docs.report.changed == 0 and not docs.fails  # nothing analysed changed
    assert twin.report.changed == 2 and twin.fails and not twin.warns
    blocking = [f for f in twin.report.findings if f.blocking]
    assert [(f.candidate.new.name, f.candidate.existing.name) for f in blocking] == [("preview_caption_text", "shorten_text")]
    assert twin.report.run.head == history.git("rev-parse", "main~1") and twin.report.run.base == history.git("rev-parse", "main~2")
    assert result.head == history.git("rev-parse", "main") and result.judging.judge.startswith("command:")


def test_replay_never_touches_the_checkout_and_leaves_no_worktree(history, tmp_path, blocking_twin_judge) -> None:
    history.git("checkout", "-q", "-b", "work", "main~2")
    (history.root / "src/text.py").write_text("unsaved = 1\n")
    replay(history.root, judged_by(blocking_twin_judge), VerdictStore(DirectoryStore(tmp_path / "store")), 10, "main")
    assert history.git("rev-parse", "--abbrev-ref", "HEAD") == "work"
    assert (history.root / "src/text.py").read_text() == "unsaved = 1\n"
    assert len(worktrees(history)) == 1


def test_a_failing_judge_still_removes_the_temporary_worktree(history, tmp_path) -> None:
    failing = f'"{sys.executable}" -c "import sys; sys.exit(3)"'
    with pytest.raises(subprocess.CalledProcessError):
        replay(history.root, judged_by(failing), VerdictStore(DirectoryStore(tmp_path / "store")), 10, "main")
    assert len(worktrees(history)) == 1


def test_replaying_again_with_another_threshold_judges_nothing_new(history, tmp_path, twin_judge) -> None:
    store = VerdictStore(DirectoryStore(tmp_path / "store"))
    first = replay(history.root, judged_by(twin_judge), store, 10, "main")
    calls = judge_calls(tmp_path)
    stricter = replay(history.root, judged_by(twin_judge, fail_at=0.9), store, 10, "main")
    assert judge_calls(tmp_path) == calls  # every verdict came from the store
    assert [c.fails for c in first.commits] == [False, True, False]
    assert [c.warns for c in stricter.commits] == [False, True, False] and not any(c.fails for c in stricter.commits)
    assert all(f.cached for _, f in stricter.findings())


def test_unchanged_files_are_read_once_across_checkouts(history) -> None:
    extractors = [load("extractors", PluginChoice(use="python"))]
    cache: dict = {}
    history.git("checkout", "-q", "main~1")
    first = repository_functions(history.root, ["*"], [], extractors, cache)
    entries = len(cache)
    history.write("src/widgets/caption.py", TWIN.replace("max_len", "limit"))
    history.commit("rename")
    second = repository_functions(history.root, ["*"], [], extractors, cache)
    assert second == repository_functions(history.root, ["*"], [], extractors)  # the cache never changes the answer
    assert len(cache) == entries + 1  # only the changed file was read again
    assert [f for f in first if f.path != "src/widgets/caption.py"] == [f for f in second if f.path != "src/widgets/caption.py"]


def test_the_text_report_lists_what_failed_and_why(history, tmp_path, blocking_twin_judge) -> None:
    result = replay(history.root, judged_by(blocking_twin_judge), VerdictStore(DirectoryStore(tmp_path / "store")), 10, "main")
    text = result.as_text()
    assert "the last 3 commits of main" in text
    assert "fails" in text and "1 would fail, 0 would only warn" in text
    assert "src/widgets/caption.py:1: preview_caption_text looks like src/text.py::shorten_text (duplicate) [blocks]" in text
    assert "judging: " in text


def test_a_replay_with_nothing_to_report_says_so_plainly() -> None:
    text = Replay(ref="main", head="0" * 40).as_text()
    assert "0 replayed" in text and "0 reported" in text and "reported findings" not in text and "judging:" not in text


def run(repo: Repo, tmp_path: Path, *args: str) -> int:
    return run_cli(repo, tmp_path, *args, command="bench")


def test_bench_replay_prints_text_or_json_and_writes_the_report(history, tmp_path, blocking_twin_judge, capsys) -> None:
    judge = ("--judge", "command", "--judge-command", blocking_twin_judge)
    assert run(history, tmp_path, "--replay", "5", "--ref", "main", *judge) == 0  # a benchmark never fails the run
    captured = capsys.readouterr()
    assert "1 would fail" in captured.out and "replay 3/3" in captured.err
    report = tmp_path / "replay.json"
    assert run(history, tmp_path, "--replay", "2", "--ref", "main", "--format", "json", "--report", str(report), *judge) == 0
    printed = Replay.model_validate_json(capsys.readouterr().out)
    assert [c.subject for c in printed.commits] == ["twin", "docs"]
    assert json.loads(report.read_text()) == json.loads(printed.model_dump_json())


@pytest.mark.parametrize("args,message", [
    (("--replay", "3", "--format", "markdown"), "text or json"),
    (("--replay", "0"), "at least 1"),
    (("--replay", "3", "--comparer"), "neither --repo nor --comparer"),
    (("--replay", "3", "--repo", "a/b=."), "neither --repo nor --comparer"),
    (("--replay", "3", "--ref", "no-such-branch"), "no-such-branch"),
])
def test_bench_replay_refuses_what_it_cannot_do(history, tmp_path, capsys, args, message) -> None:
    assert run(history, tmp_path, "--judge", "none", *args) == 2
    assert message in capsys.readouterr().err


def test_bench_needs_exactly_one_of_a_gold_set_or_a_replay(history, tmp_path) -> None:
    with pytest.raises(SystemExit):
        run(history, tmp_path)
    with pytest.raises(SystemExit):
        run(history, tmp_path, "--replay", "3", "--gold", "gold.jsonl")
