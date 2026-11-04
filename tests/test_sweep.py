import json
from pathlib import Path

import pytest

from dry_lint.baseline import Baseline
from dry_lint.extractors import PythonExtractor
from dry_lint.functions import repository_functions
from dry_lint.report import Report
from dry_lint.typescript import TypeScriptExtractor

from conftest import Repo, clear_judge_credentials, run_cli


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_judge_credentials(monkeypatch)


def sweep(repo: Repo, tmp_path: Path, judge: str, *args: str) -> int:
    return run_cli(repo, tmp_path, "--judge", "command", "--judge-command", judge, "--update", *args, command="sweep")


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
    args = (
        "--base",
        "main",
        "--judge",
        "command",
        "--judge-command",
        twin_judge,
        "--baseline",
        ".dry-lint/baseline.json",
        "--require-complete",
    )
    assert run_cli(repo, tmp_path, *args) == 0
    assert run_cli(repo, tmp_path, *args, "--warn-only") == 2
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


def test_sweep_refuses_incomplete_judging_and_existing_initialization(
    repo: Repo, tmp_path: Path, twin_judge: str
) -> None:
    assert sweep(repo, tmp_path, twin_judge, "--init") == 0
    before = state(repo)
    assert sweep(repo, tmp_path, twin_judge, "--init") == 2
    assert state(repo) == before


def test_readme_progress_is_idempotent_and_matches_shields_schema(repo: Repo, tmp_path: Path, twin_judge: str) -> None:
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
    assert (
        run_cli(
            repo,
            tmp_path,
            "--base",
            base,
            "--baseline-ref",
            base,
            "--baseline",
            ".dry-lint/baseline.json",
            "--judge",
            "command",
            "--judge-command",
            twin_judge,
        )
        == 2
    )


def test_partial_sweep_keeps_all_previous_state(repo: Repo, tmp_path: Path, twin_judge: str) -> None:
    source = (repo.root / "src/widgets/caption.py").read_text()
    repo.write("src/third.py", source.replace("preview_caption_text", "third_caption"))
    repo.write(".dry-lint.toml", "max_judgements = 1\n")
    repo.commit()
    assert sweep(repo, tmp_path, twin_judge, "--init") == 2
    assert not (repo.root / ".dry-lint/baseline.json").exists()


def test_default_audit_is_read_only_even_after_cleanup(repo: Repo, tmp_path: Path, twin_judge: str) -> None:
    assert sweep(repo, tmp_path, twin_judge, "--init") == 0
    before = state(repo)
    repo.write("src/widgets/caption.py", "from src.text import shorten_text\n")
    repo.commit()
    assert run_cli(repo, tmp_path, "--judge", "command", "--judge-command", twin_judge, command="sweep") == 0
    assert state(repo) == before


@pytest.mark.parametrize("mutation", ["duplicate", "missing_hash", "scope", "hash", "reopen"])
def test_corrupt_or_widened_acceptance_is_rejected(repo: Repo, tmp_path: Path, twin_judge: str, mutation: str) -> None:
    assert sweep(repo, tmp_path, twin_judge, "--init") == 0
    original = Baseline.model_validate(state(repo))
    value = state(repo)
    if mutation == "duplicate":
        value["entries"].append(value["entries"][0])
    elif mutation == "missing_hash":
        value["entries"][0]["hashes"] = {"a.py::a": ""}
    elif mutation == "scope":
        repo.write(".dry-lint.toml", 'exclude = ["src/*"]\n')
        assert sweep(repo, tmp_path, twin_judge) == 2
        return
    elif mutation == "hash":
        name = next(iter(value["entries"][0]["hashes"]))
        value["entries"][0]["hashes"][name] = "different"
    else:
        original.entries[0].state = "cleaned"
    with pytest.raises(ValueError):
        Baseline.model_validate(value).validate_successor(original)


def test_valid_successor_and_direct_advance_refuse_new_debt(repo: Repo, tmp_path: Path, twin_judge: str) -> None:
    report_path = tmp_path / "report.json"
    assert sweep(repo, tmp_path, twin_judge, "--init", "--report", str(report_path)) == 0
    baseline = Baseline.model_validate(state(repo))
    baseline.validate_successor(baseline)
    report = Report.model_validate_json(report_path.read_text())
    empty = baseline.model_copy(update={"entries": []})
    with pytest.raises(ValueError, match="cannot be added"):
        empty.advance(report)
    with pytest.raises(ValueError, match="OWNER/NAME"):
        baseline.markdown("bad repo", "main", ".dry-lint")


def test_strict_scanning_requires_valid_source_and_a_validating_plugin(repo: Repo) -> None:
    class LegacyExtractor:
        files = ("*.py",)

    with pytest.raises(ValueError, match="strict source validation"):
        repository_functions(repo.root, ["*"], [], [LegacyExtractor()], strict=True)
    (repo.root / "src/text.py").unlink()
    with pytest.raises(FileNotFoundError):
        repository_functions(repo.root, ["*"], [], [PythonExtractor()], strict=True)
    extractor = TypeScriptExtractor()
    extractor.validate_source("a.ts", "export const a = (x: number) => x + 1;")
    with pytest.raises(ValueError, match="parse error"):
        extractor.validate_source("a.ts", "export function broken( {")


def test_strict_mode_rejects_workspace_scopes(repo: Repo, tmp_path: Path) -> None:
    assert run_cli(repo, tmp_path, "--require-complete", "--repo", f"acme/lib={repo.root}") == 2


@pytest.mark.parametrize("staged", [False, True])
def test_balanced_strict_check_validates_the_selected_tree(repo: Repo, tmp_path: Path, capsys, staged: bool) -> None:
    repo.write("src/text.py", "def broken(\n")
    repo.commit()
    if staged:
        repo.write("src/text.py", "def also_broken(\n")
        repo.git("add", "src/text.py")
    # A valid unstaged repair must not hide invalid committed/staged input from the strict check.
    repo.write("src/text.py", "def repaired():\n    return 1\n")
    args = ["--staged"] if staged else ["--base", "main"]
    assert run_cli(repo, tmp_path, "--preset", "balanced", "--judge", "none",
                   "--require-complete", *args) == 2
    assert "Cannot completely scan src/text.py" in capsys.readouterr().err
