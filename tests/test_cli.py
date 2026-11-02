import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from dry_lint.cli import default_store, main
from dry_lint.judges.jev import JevJudge

from conftest import Repo

TWIN = "src/widgets/caption.py::preview_caption_text"


@pytest.fixture
def judge(tmp_path: Path) -> str:
    """A judge command that counts its calls and calls the caption twin a duplicate, everything else separate."""
    path = tmp_path / "judge.py"
    calls = tmp_path / "calls"
    path.write_text(
        "import json, pathlib, sys\n"
        f"calls = pathlib.Path({str(calls)!r})\n"
        "calls.write_text(str(int(calls.read_text() or 0) + 1) if calls.exists() else '1')\n"
        "prompt = sys.stdin.read()\n"
        "twin = 'preview_caption_text' in prompt and 'shorten_text' in prompt\n"
        "print(json.dumps({'label': 'duplicate' if twin else 'separate', 'score': 0.9 if twin else 0.1, 'owner': 'existing'}))\n"
    )
    return f'"{sys.executable}" "{path}"'


def run(repo: Repo, tmp_path: Path, *args: str) -> int:
    return main(["check", "--root", str(repo.root), "--store", str(tmp_path / "store" / "verdicts.jsonl"), *args])


def calls(tmp_path: Path) -> int:
    path = tmp_path / "calls"
    return int(path.read_text()) if path.exists() else 0


def test_check_fails_and_annotates_a_judged_reimplementation(repo: Repo, tmp_path: Path, judge: str, capsys) -> None:
    code = run(repo, tmp_path, "--base", "main", "--judge", "command", "--judge-command", judge, "--format", "github")
    assert code == 1
    out = capsys.readouterr().out
    assert out.startswith("::warning file=src/widgets/caption.py,line=1,") and "src/text.py::shorten_text" in out


def test_verdicts_are_remembered_so_the_judge_is_asked_once(repo: Repo, tmp_path: Path, judge: str, capsys) -> None:
    args = ("--base", "main", "--judge", "command", "--judge-command", judge, "--format", "json")
    run(repo, tmp_path, *args)
    first = calls(tmp_path)
    assert first >= 1
    capsys.readouterr()
    run(repo, tmp_path, *args)
    findings = json.loads(capsys.readouterr().out)
    assert calls(tmp_path) == first
    assert all(f["cached"] for f in findings)
    assert any(f["reported"] and f["candidate"]["new"]["path"] + "::" + f["candidate"]["new"]["name"] == TWIN for f in findings)


def test_warn_only_reports_without_failing_and_writes_the_comment(repo: Repo, tmp_path: Path, judge: str) -> None:
    report = tmp_path / "report.md"
    code = run(repo, tmp_path, "--base", "main", "--judge", "command", "--judge-command", judge, "--warn-only",
               "--output", str(report))
    assert code == 0
    assert report.read_text().startswith("<!-- dry-lint -->") and TWIN in report.read_text()


def test_without_a_judge_candidates_are_listed_and_never_fail(repo: Repo, tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.delenv("TYPESAFE_AI_API_KEY", raising=False)
    assert run(repo, tmp_path, "--base", "main") == 0
    out = capsys.readouterr().out
    assert "preview_caption_text looks like src/text.py::shorten_text (candidate)" in out
    assert not (tmp_path / "store").exists()


def test_staged_check_sees_only_the_staged_change(repo: Repo, tmp_path: Path, capsys) -> None:
    repo.write("src/more.py", "def shorten_label(label, size):\n    if len(label) <= size:\n        return label\n"
               "    trimmed = label[: size - 1].rstrip()\n    return trimmed.rstrip('.,;') + '…'\n")
    repo.git("add", "src/more.py")
    assert run(repo, tmp_path, "--staged", "--judge", "none", "--format", "markdown") == 0
    out = capsys.readouterr().out
    assert "`src/more.py::shorten_label`" in out and "preview_caption_text`" not in out.split("| `src/more.py")[0]


def test_scan_lists_the_repository_backlog(repo: Repo, tmp_path: Path, capsys) -> None:
    assert main(["scan", "--root", str(repo.root), "--judge", "none", "--limit", "5"]) == 0
    out = capsys.readouterr().out
    assert "shorten_text" in out and "preview_caption_text" in out


def test_errors_exit_2_with_a_message(tmp_path: Path, capsys) -> None:
    assert main(["check", "--root", str(tmp_path), "--judge", "none"]) == 2
    assert capsys.readouterr().err.startswith("dry-lint: ")


def test_bad_judge_settings_exit_2(repo: Repo, tmp_path: Path, capsys) -> None:
    assert run(repo, tmp_path, "--base", "main", "--judge", "command") == 2
    assert "--judge-command" in capsys.readouterr().err


def test_the_default_store_lives_inside_the_git_directory(repo: Repo) -> None:
    assert default_store(repo.root) == (repo.root / ".git" / "dry-lint" / "verdicts.jsonl").resolve()


def test_the_module_runs_as_a_command(repo: Repo) -> None:
    out = subprocess.run([sys.executable, "-m", "dry_lint", "--version"], capture_output=True, text=True, check=True)
    assert out.stdout.startswith("dry-lint 0.1.0")


def test_judge_failures_exit_2_without_a_traceback(repo: Repo, tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("TYPESAFE_AI_API_KEY", "key")
    with patch.object(JevJudge, "judge", side_effect=httpx.ConnectError("api unreachable")):
        assert run(repo, tmp_path, "--base", "main", "--judge", "jev") == 2
    assert capsys.readouterr().err.startswith("dry-lint: ")
