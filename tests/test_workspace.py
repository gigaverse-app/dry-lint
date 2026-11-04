import json
from pathlib import Path

import pytest

from dry_lint.cli import main
from dry_lint.detector import Detector
from dry_lint.models import CandidatesFile, Function, Run
from dry_lint.report import function_link
from dry_lint.settings import Settings

from conftest import EXISTING, TWIN, Repo, filler_module


@pytest.fixture
def workspace(tmp_path: Path) -> dict[str, Path]:
    roots = {}
    for name, source in (("web", EXISTING), ("mobile", TWIN), ("common", filler_module())):
        repo = Repo(tmp_path / name)
        repo.write("src/text.py", source)
        repo.commit()
        roots[f"org/{name}"] = repo.root
    return roots


def test_cross_repository_twins_with_identical_paths_keep_distinct_identity_and_links(workspace) -> None:
    detector = Detector.for_workspace(workspace, Settings())
    pair = detector.scan()[0]
    assert {pair.new.origin.repository, pair.existing.origin.repository} == {"org/web", "org/mobile"}
    assert pair.new.path == pair.existing.path == "src/text.py"
    assert pair.new.qualname != pair.existing.qualname
    assert pair.new.hash and pair.existing.hash
    for function in (pair.new, pair.existing):
        link = function_link(function, Run(repository="wrong/repo", head="a" * 40))
        assert f"/{function.origin.repository}/blob/{function.origin.head}/src/text.py#L" in link
        assert function.origin.repository in link.split("](")[0]
    reverse = Detector.for_workspace(dict(reversed(list(workspace.items()))), Settings()).scan()[0]
    assert reverse.key == pair.key
    loaded = CandidatesFile.model_validate_json(CandidatesFile(candidates=[pair]).model_dump_json())
    assert loaded.candidates[0].key == pair.key


def test_workspace_applies_each_repository_file_exclusions(workspace) -> None:
    (workspace["org/mobile"] / ".dry-lint.toml").write_text('exclude = ["src/text.py"]\n')
    detector = Detector.for_workspace(workspace, Settings())
    assert all(f.origin.repository != "org/mobile" for f in detector.functions)
    assert not detector.scan()


def test_workspace_filters_same_repository_before_selecting_nearest(workspace) -> None:
    mobile = workspace["org/mobile"]
    from dry_lint.git import git

    (mobile / "src/copy.py").write_text(TWIN)
    git(mobile, "add", ".")
    git(mobile, "commit", "-qm", "copy")
    detector = Detector.for_workspace(workspace, Settings())
    function = detector.find("org/mobile/src/text.py::preview_caption_text")
    assert detector.neighbours(function)[0][0].origin.repository == "org/web"


@pytest.mark.parametrize("problem", ["dirty", "duplicate-root", "bad-name", "one-repo"])
def test_workspace_rejects_ambiguous_or_uncommitted_sources(workspace, problem: str) -> None:
    if problem == "dirty":
        (workspace["org/web"] / "src/text.py").write_text(TWIN)
    elif problem == "duplicate-root":
        workspace["org/alias"] = workspace["org/web"]
    elif problem == "bad-name":
        workspace["../bad"] = workspace.pop("org/web")
    else:
        workspace = {"org/web": workspace["org/web"]}
    with pytest.raises(ValueError):
        Detector.for_workspace(workspace, Settings())


def test_workspace_cli_uses_existing_judge_and_report_pipeline(workspace, tmp_path, twin_judge, capsys) -> None:
    output = tmp_path / "report.json"
    args = [
        "scan",
        "--root",
        str(workspace["org/web"]),
        "--judge",
        "command",
        "--judge-command",
        twin_judge,
        "--warn-only",
        "--format",
        "markdown",
        "--report",
        str(output),
    ]
    for name, root in workspace.items():
        args.extend(["--repo", f"{name}={root}"])
    assert main(args) == 0
    data = json.loads(output.read_text())
    assert data["schema"] == 8 and data["findings"][0]["reported"]
    assert data["functions"] == 33 and data["scope"] == "repository"
    assert "https://github.com/org/" in capsys.readouterr().out
    assert main(["report", "--root", str(workspace["org/web"]), "--from", str(output), "--format", "sarif"]) == 2
    assert "workspace report" in capsys.readouterr().err
    assert main([*args, "--repo", f"org/web={workspace['org/web']}"]) == 2
    assert "Duplicate repository" in capsys.readouterr().err
    assert main([*args, "--format", "github"]) == 2
    assert "workspace" in capsys.readouterr().err
    assert main([*args, "--repo", "missing-path"]) == 2


def test_schema_two_functions_still_have_local_identity() -> None:
    function = Function(path="src/a.ts", name="shorten", line=1, end_line=2, code="")
    loaded = CandidatesFile.model_validate({"schema": 2, "candidates": []})
    assert loaded.schema_version == 2
    assert function.origin is None and function.qualname == "src/a.ts::shorten"


def test_workspace_check_queries_only_changed_primary_functions(workspace, tmp_path, twin_judge, capsys):
    from dry_lint.git import git

    web = workspace["org/web"]
    base = git(web, "rev-parse", "HEAD")
    (web / "src/text.py").write_text(EXISTING.replace('rstrip(".,;")', 'rstrip(".,;!")'), encoding="utf-8")
    git(web, "add", ".")
    git(web, "commit", "-qm", "fix(text): adjust punctuation")
    output = tmp_path / "change.json"
    args = [
        "check",
        "--root",
        str(web),
        "--base",
        base,
        "--judge",
        "command",
        "--judge-command",
        twin_judge,
        "--warn-only",
        "--report",
        str(output),
    ]
    for name, root in workspace.items():
        args.extend(["--repo", f"{name}={root}"])
    assert main(args) == 0
    report = json.loads(output.read_text())
    assert report["changed"] == 1
    assert report["run"]["repository"] == "org/web"
    assert all(f["candidate"]["new"]["origin"]["repository"] == "org/web" for f in report["findings"])
    assert main(["report", "--root", str(web), "--from", str(output), "--format", "github", "--warn-only"]) == 0
    detected = tmp_path / "candidates.json"
    assert main(["detect", *args[1:], "--out", str(detected)]) == 0
    assert json.loads(detected.read_text())["run"]["repository"] == "org/web"
    without_primary = args[: args.index("--repo")]
    for name in ["org/mobile", "org/common"]:
        without_primary.extend(["--repo", f"{name}={workspace[name]}"])
    assert main(without_primary) == 2
    assert "primary" in capsys.readouterr().err
