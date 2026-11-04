import json
from pathlib import Path

import pytest

from conftest import Repo, run_cli


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("TYPESAFE_AI_API_KEY", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def sweep(repo: Repo, tmp_path: Path, judge: str, *args: str) -> int:
    return run_cli(repo, tmp_path, "--judge", "command", "--judge-command", judge, *args, command="sweep")


def state(repo: Repo) -> dict:
    return json.loads((repo.root / ".dry-lint/baseline.json").read_text())


def test_sweep_ratchets_specific_pairs_and_rejects_reintroduction(repo: Repo, tmp_path: Path, twin_judge: str) -> None:
    assert sweep(repo, tmp_path, twin_judge, "--init") == 0
    assert len(state(repo)["entries"]) == 1
    assert sweep(repo, tmp_path, twin_judge) == 0
    original = (repo.root / "src/widgets/caption.py").read_text()
    repo.write("src/widgets/caption.py", "from src.text import shorten_text\n")
    repo.commit()
    assert sweep(repo, tmp_path, twin_judge) == 0
    assert state(repo)["entries"][0]["state"] == "cleaned"
    repo.write("src/widgets/caption.py", original)
    repo.commit()
    before = state(repo)
    assert sweep(repo, tmp_path, twin_judge) == 1
    assert state(repo) == before


def test_baseline_allows_only_unchanged_debt(repo: Repo, tmp_path: Path, twin_judge: str) -> None:
    assert sweep(repo, tmp_path, twin_judge, "--init") == 0
    args = ("--base", "main", "--judge", "command", "--judge-command", twin_judge,
            "--baseline", ".dry-lint/baseline.json", "--require-complete")
    assert run_cli(repo, tmp_path, *args) == 0
    path = repo.root / "src/widgets/caption.py"
    path.write_text(path.read_text().replace("max_len - 1", "max_len - 2"))
    repo.commit()
    assert run_cli(repo, tmp_path, *args) == 1
    assert sweep(repo, tmp_path, twin_judge) == 1


def test_suppression_is_dismissal_not_cleanup(repo: Repo, tmp_path: Path, twin_judge: str) -> None:
    assert sweep(repo, tmp_path, twin_judge, "--init") == 0
    path = repo.root / "src/widgets/caption.py"
    path.write_text(path.read_text().replace("    if len", "    # dry-lint: ignore\n    if len", 1))
    repo.commit()
    assert sweep(repo, tmp_path, twin_judge) == 0
    assert state(repo)["entries"][0]["state"] == "dismissed"


@pytest.mark.parametrize("command", ["check", "sweep"])
def test_strict_mode_never_passes_without_a_judge(repo: Repo, tmp_path: Path, command: str) -> None:
    args = ["--base", "main", "--require-complete"] if command == "check" else ["--init"]
    assert run_cli(repo, tmp_path, "--judge", "none", *args, command=command) == 2
    assert not (repo.root / ".dry-lint/baseline.json").exists()


def test_sweep_refuses_incomplete_judging_and_existing_initialization(repo: Repo, tmp_path: Path,
                                                                    twin_judge: str) -> None:
    assert sweep(repo, tmp_path, twin_judge, "--init") == 0
    before = state(repo)
    assert sweep(repo, tmp_path, twin_judge, "--init") == 2
    assert state(repo) == before


def test_readme_progress_is_idempotent_and_matches_shields_schema(repo: Repo, tmp_path: Path,
                                                                twin_judge: str) -> None:
    repo.write("README.md", "# A library\n\nUseful introduction.\n")
    args = ("--readme", "README.md", "--repository", "acme/library")
    assert sweep(repo, tmp_path, twin_judge, "--init", *args) == 0
    readme = (repo.root / "README.md").read_text()
    assert "Useful introduction." in readme and "img.shields.io/endpoint?url=" in readme
    assert sweep(repo, tmp_path, twin_judge, *args) == 0
    assert (repo.root / "README.md").read_text() == readme
    badge = json.loads((repo.root / ".dry-lint/progress.json").read_text())
    assert badge["schemaVersion"] == 1
    assert badge["message"] == "0 cleaned · 1 remaining"


def test_parse_failure_cannot_clear_the_backlog(repo: Repo, tmp_path: Path, twin_judge: str) -> None:
    assert sweep(repo, tmp_path, twin_judge, "--init") == 0
    before = state(repo)
    repo.write("src/widgets/caption.py", "def broken(:\n")
    assert sweep(repo, tmp_path, twin_judge) == 2
    assert state(repo) == before


def test_unknown_baseline_schema_is_an_error(repo: Repo, tmp_path: Path, twin_judge: str) -> None:
    assert sweep(repo, tmp_path, twin_judge, "--init") == 0
    value = state(repo)
    value["schema"] = 999
    (repo.root / ".dry-lint/baseline.json").write_text(json.dumps(value))
    assert sweep(repo, tmp_path, twin_judge) == 2


def test_required_check_rejects_a_widened_pr_baseline(repo: Repo, tmp_path: Path, twin_judge: str) -> None:
    assert sweep(repo, tmp_path, twin_judge, "--init") == 0
    repo.commit()
    base = repo.git("rev-parse", "HEAD")
    value = state(repo)
    value["entries"] = []
    (repo.root / ".dry-lint/baseline.json").write_text(json.dumps(value))
    repo.commit()
    assert run_cli(repo, tmp_path, "--base", base, "--baseline-ref", base, "--baseline", ".dry-lint/baseline.json",
                   "--judge", "command", "--judge-command", twin_judge) == 2


def test_partial_sweep_keeps_all_previous_state(repo: Repo, tmp_path: Path, twin_judge: str) -> None:
    source = (repo.root / "src/widgets/caption.py").read_text()
    repo.write("src/third.py", source.replace("preview_caption_text", "third_caption"))
    repo.write(".dry-lint.toml", "max_judgements = 1\n")
    repo.commit()
    assert sweep(repo, tmp_path, twin_judge, "--init") == 2
    assert not (repo.root / ".dry-lint/baseline.json").exists()
