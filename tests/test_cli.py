import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from dry_lint.bench import GoldFunction, GoldPair
from dry_lint.cli import main, parser, run_info, settings_for
from dry_lint.judges.jev import JevJudge
from dry_lint.models import CandidatesFile

from conftest import EXISTING, Repo, judge_calls
from conftest import TWIN as TWIN_SOURCE

TWIN = "src/widgets/caption.py::preview_caption_text"


@pytest.fixture(autouse=True)
def outside_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GITHUB_EVENT_PATH", "GITHUB_REPOSITORY", "TYPESAFE_AI_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def run(repo: Repo, tmp_path: Path, *args: str, command: str = "check") -> int:
    return main([command, "--root", str(repo.root), "--store", str(tmp_path / "store"), *args])


def test_check_fails_and_annotates_an_error_for_a_blocking_reimplementation(repo: Repo, tmp_path: Path,
                                                                              blocking_twin_judge: str, capsys) -> None:
    code = run(repo, tmp_path, "--base", "main", "--judge", "command", "--judge-command", blocking_twin_judge,
               "--format", "github")
    assert code == 1
    out = capsys.readouterr().out
    assert out.startswith("::error file=src/widgets/caption.py,line=1,") and "src/text.py::shorten_text" in out


def test_a_reported_duplicate_below_fail_at_warns_without_failing(repo: Repo, tmp_path: Path, twin_judge: str,
                                                                  capsys) -> None:
    code = run(repo, tmp_path, "--base", "main", "--judge", "command", "--judge-command", twin_judge, "--format", "github",
               "--fail-at", "0.9")
    assert code == 0
    assert capsys.readouterr().out.startswith("::warning file=src/widgets/caption.py,line=1,")
    (repo.root / ".dry-lint.toml").write_text("fail_at = 0.9\n")
    assert run(repo, tmp_path, "--base", "main", "--judge", "command", "--judge-command", twin_judge) == 0
    assert run(repo, tmp_path, "--base", "main", "--judge", "command", "--judge-command", twin_judge, "--fail-at", "0.8") == 1


def test_by_default_every_reported_duplicate_fails(repo: Repo, tmp_path: Path, twin_judge: str) -> None:
    assert run(repo, tmp_path, "--base", "main", "--judge", "command", "--judge-command", twin_judge) == 1


def test_verdicts_are_remembered_so_the_judge_is_asked_once(repo: Repo, tmp_path: Path, twin_judge: str, capsys) -> None:
    args = ("--base", "main", "--judge", "command", "--judge-command", twin_judge, "--format", "json")
    run(repo, tmp_path, *args)
    first = judge_calls(tmp_path)
    assert first >= 1
    capsys.readouterr()
    run(repo, tmp_path, *args)
    report = json.loads(capsys.readouterr().out)
    assert judge_calls(tmp_path) == first
    assert all(f["cached"] for f in report["findings"])
    assert any(f["reported"] and f["candidate"]["new"]["path"] + "::" + f["candidate"]["new"]["name"] == TWIN
               for f in report["findings"])
    assert len(list((tmp_path / "store").glob("*.json"))) == first


def test_warn_only_reports_without_failing_and_writes_the_comment_and_report(repo: Repo, tmp_path: Path, twin_judge: str) -> None:
    comment, report = tmp_path / "comment.md", tmp_path / "report.json"
    code = run(repo, tmp_path, "--base", "main", "--judge", "command", "--judge-command", twin_judge, "--warn-only",
               "--output", str(comment), "--report", str(report))
    assert code == 0
    assert comment.read_text().startswith("<!-- dry-lint -->") and f"`{TWIN.split('::')[1]}`" in comment.read_text()
    assert "blocking" not in comment.read_text()
    written = json.loads(report.read_text())
    assert written["schema"] == 3 and any(f["reported"] for f in written["findings"])


def test_without_a_judge_candidates_are_listed_and_never_fail(repo: Repo, tmp_path: Path, capsys) -> None:
    assert run(repo, tmp_path, "--base", "main") == 0
    out = capsys.readouterr().out
    assert "preview_caption_text looks like src/text.py::shorten_text (candidate)" in out
    assert not (tmp_path / "store").exists()


def test_staged_check_sees_only_the_staged_change(repo: Repo, tmp_path: Path, capsys) -> None:
    repo.write("src/more.py", "def shorten_label(label, size):\n    if len(label) <= size:\n        return label\n"
               "    trimmed = label[: size - 1].rstrip()\n    return trimmed.rstrip('.,;') + '…'\n")
    repo.git("add", "src/more.py")
    assert run(repo, tmp_path, "--staged", "--judge", "none", "--format", "text") == 0
    out = capsys.readouterr().out
    assert "src/more.py:1: shorten_label looks like" in out and "caption.py:1:" not in out


def test_scan_lists_the_repository_backlog(repo: Repo, tmp_path: Path, capsys) -> None:
    assert main(["scan", "--root", str(repo.root), "--judge", "none", "--limit", "5"]) == 0
    out = capsys.readouterr().out
    assert "shorten_text" in out and "preview_caption_text" in out


def test_scan_refresh_re_judges_answers_from_an_older_judge_version(repo: Repo, tmp_path: Path, twin_judge: str) -> None:
    for version in ("v1", "v1", "v2"):
        (repo.root / ".dry-lint.toml").write_text(f'judge = {{ use = "command", command = {json.dumps(twin_judge)}, version = "{version}" }}\n')
        main(["scan", "--root", str(repo.root), "--store", str(tmp_path / "store"), "--limit", "1", "--refresh", "--warn-only"])
    assert judge_calls(tmp_path) == 2


def test_the_two_ci_jobs_hand_over_through_candidates_json(repo: Repo, tmp_path: Path, blocking_twin_judge: str,
                                                           monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"number": 42, "head": {"sha": "feedbeef"}}}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_REPOSITORY", "octo/repo")
    candidates = tmp_path / "candidates.json"
    assert run(repo, tmp_path, "--base", "main", "--out", str(candidates), command="detect") == 0
    assert "candidate pair(s) to judge" in capsys.readouterr().out
    handed = CandidatesFile.model_validate_json(candidates.read_text())
    assert (handed.run.repository, handed.run.pull_request, handed.run.head, handed.run.base) == ("octo/repo", 42, "feedbeef", "main")
    assert handed.changed == 2 and all(c.new.hash and c.existing.hash for c in handed.candidates)
    assert not (tmp_path / "store").exists()  # detect never touches the store

    report = tmp_path / "report.json"
    code = run(repo, tmp_path, "--candidates", str(candidates), "--judge", "command", "--judge-command", blocking_twin_judge,
               "--report", str(report), "--warn-only", command="judge")
    assert code == 0 and judge_calls(tmp_path) >= 1
    capsys.readouterr()
    assert main(["report", "--root", str(repo.root), "--from", str(report), "--format", "check-run"]) == 1
    body = json.loads(capsys.readouterr().out)
    assert (body["head_sha"], body["conclusion"]) == ("feedbeef", "failure")
    assert json.loads(report.read_text())["findings"][0]["blocking"] is True
    main(["report", "--root", str(repo.root), "--from", str(report), "--format", "check-run", "--warn-only"])
    assert json.loads(capsys.readouterr().out)["conclusion"] == "neutral"
    assert json.loads(report.read_text())["run"]["pull_request"] == 42


def test_detect_prints_candidates_without_out_and_proposes_the_backlog_with_all(repo: Repo, tmp_path: Path, capsys) -> None:
    assert run(repo, tmp_path, "--base", "main", command="detect") == 0
    assert CandidatesFile.model_validate_json(capsys.readouterr().out).changed == 2
    assert run(repo, tmp_path, "--all", command="detect") == 0
    everything = CandidatesFile.model_validate_json(capsys.readouterr().out)
    assert everything.changed > 30 and any(c.existing.name == "shorten_text" or c.new.name == "shorten_text"
                                           for c in everything.candidates)


def test_explain_shows_the_similarity_the_rule_and_the_stored_verdict(repo: Repo, tmp_path: Path, twin_judge: str, capsys) -> None:
    assert run(repo, tmp_path, "caption.py::preview_caption_text", "text.py::shorten_text", command="explain") == 0
    out = capsys.readouterr().out
    assert out.startswith(f"{TWIN} ~ src/text.py::shorten_text\n  similarity ")
    assert "(tfidf:2)" in out and "shared: " in out and "proposed: #1 of" in out
    assert "rule: none applies" in out and "stored verdict: none" in out
    run(repo, tmp_path, "--base", "main", "--judge", "command", "--judge-command", twin_judge, "--warn-only")
    capsys.readouterr()
    run(repo, tmp_path, "caption.py::preview_caption_text", "text.py::shorten_text", command="explain")
    out = capsys.readouterr().out
    assert "stored verdict: duplicate 0.85 by command:" in out and "reused: yes, neither function's logic changed" in out
    run(repo, tmp_path, "caption.py::register_widget", "filler.py::sync_invoice", command="explain")
    assert "proposed: not among" in capsys.readouterr().out


def test_bench_measures_the_judge_or_the_comparer(repo: Repo, tmp_path: Path, twin_judge: str, capsys) -> None:
    gold = tmp_path / "gold.jsonl"
    twin = GoldPair(new=GoldFunction(id=TWIN, code=TWIN_SOURCE), existing=GoldFunction(id="src/text.py::shorten_text", code=EXISTING),
                    label="duplicate")
    gold.write_text(twin.model_dump_json() + "\n")
    assert run(repo, tmp_path, "--gold", str(gold), "--judge", "command", "--judge-command", twin_judge, command="bench") == 0
    assert "1 labelled pairs, 1 duplicates" in capsys.readouterr().out
    assert run(repo, tmp_path, "--gold", str(gold), "--comparer", command="bench") == 0
    assert "partner among the top 3 proposed: 100%" in capsys.readouterr().out
    assert run(repo, tmp_path, "--gold", str(gold), "--comparer", "--format", "json", command="bench") == 0
    assert json.loads(capsys.readouterr().out)["recall"] == 1.0
    assert run(repo, tmp_path, "--gold", str(gold), "--judge", "command", "--judge-command", twin_judge, "--format", "json",
               command="bench") == 0
    assert json.loads(capsys.readouterr().out)["duplicates"] == 1
    assert run(repo, tmp_path, "--gold", str(gold), "--judge", "none", command="bench") == 2
    assert "bench needs a judge" in capsys.readouterr().err


def test_the_command_line_judge_overrides_the_settings_and_keeps_their_options(repo: Repo) -> None:
    (repo.root / ".dry-lint.toml").write_text('judge = { use = "command", command = "llm-a", version = "v9" }\n')
    args = parser().parse_args(["check", "--judge-command", "llm-b"])
    assert settings_for(repo.root, args).judge.options() == {"command": "llm-b", "version": "v9"}
    args = parser().parse_args(["check", "--judge", "jev"])
    assert settings_for(repo.root, args).judge.model_dump() == {"use": "jev"}
    assert settings_for(repo.root, parser().parse_args(["check"])).judge.options()["command"] == "llm-a"


def test_run_info_outside_actions_is_the_local_head(repo: Repo) -> None:
    info = run_info(repo.root, None)
    assert info.head == repo.git("rev-parse", "HEAD").strip() and info.pull_request is None and info.base == "origin/main"


def test_errors_exit_2_with_a_message(tmp_path: Path, capsys) -> None:
    assert main(["check", "--root", str(tmp_path), "--judge", "none"]) == 2
    assert capsys.readouterr().err.startswith("dry-lint: ")


def test_bad_judge_settings_exit_2(repo: Repo, tmp_path: Path, capsys) -> None:
    assert run(repo, tmp_path, "--base", "main", "--judge", "command") == 2
    assert "--judge-command" in capsys.readouterr().err


def test_the_module_runs_as_a_command(repo: Repo) -> None:
    out = subprocess.run([sys.executable, "-m", "dry_lint", "--version"], capture_output=True, text=True, check=True)
    assert out.stdout.startswith("dry-lint 0.")


def test_judge_failures_exit_2_without_a_traceback(repo: Repo, tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("TYPESAFE_AI_API_KEY", "key")
    with patch.object(JevJudge, "judge", side_effect=httpx.ConnectError("api unreachable")):
        assert run(repo, tmp_path, "--base", "main", "--judge", "jev") == 2
    assert capsys.readouterr().err.startswith("dry-lint: ")
