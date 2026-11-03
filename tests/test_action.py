import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from test_action_sticky import FakeGitHub

from dry_lint import action, sticky
from dry_lint.action import count_findings, ensure_history, resolve_base, resolve_judge, resolve_mode

from conftest import Repo, judge_calls

HEAD, BASE = "c" * 40, "b" * 40
ANNOTATION = "::warning file=src/a.py,line=3,endLine=9,title=dry-lint::clip looks like src/b.py::shorten"


def pull_request(fork: bool = False) -> dict:
    head_repo = "someone/shop" if fork else "acme/shop"
    return {"pull_request": {"number": 7, "head": {"sha": HEAD, "repo": {"full_name": head_repo}},
                             "base": {"sha": BASE, "repo": {"full_name": "acme/shop"}}}}


WORKFLOW_RUN = {"workflow_run": {"id": 991, "head_sha": HEAD, "event": "pull_request"}}


@pytest.mark.parametrize("requested, event_name, event, mode", [
    ("auto", "pull_request", pull_request(), "single"),
    ("auto", "pull_request", pull_request(fork=True), "detect"),
    ("auto", "workflow_run", WORKFLOW_RUN, "judge"),
    ("auto", "push", {"before": BASE}, "single"),
    ("", "workflow_dispatch", {}, "single"),
    ("detect", "pull_request", pull_request(), "detect"),
])  # fmt: skip
def test_auto_mode_follows_where_secrets_are_available(requested, event_name, event, mode) -> None:
    assert resolve_mode(requested, event_name, event) == mode


def test_an_unknown_mode_is_an_error() -> None:
    with pytest.raises(ValueError, match="Unknown mode"):
        resolve_mode("judge-everything", "pull_request", {})


@pytest.mark.parametrize("explicit, event_name, event, base", [
    ("origin/develop", "pull_request", pull_request(), "origin/develop"),
    ("", "pull_request", pull_request(), BASE),
    ("", "pull_request_target", pull_request(), BASE),
    ("", "push", {"before": BASE}, BASE),
    ("", "push", {"before": "0" * 40}, "0" * 40),  # a new branch's first push: dry-lint maps it to the default branch
    ("", "workflow_dispatch", {}, ""),
])  # fmt: skip
def test_the_base_is_the_pull_requests_base_or_the_previous_push(explicit, event_name, event, base) -> None:
    assert resolve_base(explicit, event_name, event) == base


@pytest.mark.parametrize("requested, has_key, judge", [
    ("auto", True, "jev"), ("auto", False, "none"), ("", False, "none"), ("command", False, "command"),
])  # fmt: skip
def test_auto_judge_is_jev_only_with_a_key(requested, has_key, judge) -> None:
    assert resolve_judge(requested, has_key) == judge


def test_findings_are_counted_from_file_annotations_only() -> None:
    lines = [ANNOTATION, ANNOTATION.replace("::warning", "::error"), "::notice title=dry-lint::hi", "dry-lint: 3 pairs"]
    assert count_findings(lines) == 2


def test_a_shallow_checkout_gets_the_history_a_merge_base_needs(repo: Repo, tmp_path: Path) -> None:
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "--depth", "1", "--branch", "feature", f"file://{repo.root}", str(clone)],
                   check=True)
    main_sha = repo.git("rev-parse", "main").strip()
    ensure_history(clone, main_sha)
    assert subprocess.run(["git", "merge-base", main_sha, "HEAD"], cwd=clone, capture_output=True).returncode == 0


@pytest.fixture
def github_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The environment a composite action step sees, with its output files in tmp_path."""

    def set_event(name: str, payload: dict, **inputs: str) -> Path:
        event = tmp_path / "event.json"
        event.write_text(json.dumps(payload))
        values = {"GITHUB_EVENT_NAME": name, "GITHUB_EVENT_PATH": str(event), "GITHUB_REPOSITORY": "acme/shop",
                  "GITHUB_RUN_ID": "55", "GITHUB_OUTPUT": str(tmp_path / "output"), "GITHUB_TOKEN": "token",
                  "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"), "RUNNER_TEMP": str(tmp_path / "runner"),
                  "INPUT_COMMENT": "true", "INPUT_CHECK_RUN": "true", "INPUT_WORKING_DIRECTORY": str(tmp_path)}
        values.update({f"INPUT_{k.upper()}": v for k, v in inputs.items() if k != "key"})
        if "key" in inputs:
            values["TYPESAFE_AI_API_KEY"] = inputs["key"]
        else:
            monkeypatch.delenv("TYPESAFE_AI_API_KEY", raising=False)
        for name_, value in values.items():
            monkeypatch.setenv(name_, value)
        return tmp_path

    return set_event


def outputs(tmp_path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in (tmp_path / "output").read_text().splitlines())


def cli_writes_comment(tmp_path: Path, findings: list[str], code: int = 0, run: dict | None = None):
    """A stand-in for the dry-lint CLI that leaves the files the real one writes."""

    def fake(*args: str, echo: bool = True):
        work = tmp_path / "runner" / "dry-lint"
        (work / "comment.md").write_text("<!-- dry-lint -->\n### dry-lint\n")
        if run is not None:
            (work / "report.json").write_text(json.dumps({"run": run}))
        return code, findings

    return fake


def test_single_mode_comments_and_reports_without_failing_by_default(github_env, tmp_path) -> None:
    github_env("pull_request", pull_request(), key="secret")
    with patch.object(action, "dry_lint", side_effect=cli_writes_comment(tmp_path, [ANNOTATION])) as cli, \
            patch.object(sticky, "main", return_value=0) as post:
        assert action.main(["run"]) == 0
    args = cli.call_args.args
    assert args[0] == "check" and args[args.index("--base") + 1] == BASE and args[args.index("--judge") + 1] == "jev"
    assert args[args.index("--format") + 1] == "github"
    posted = post.call_args.args[0]
    assert posted[posted.index("--pull-request") + 1] == "7" and posted[posted.index("--findings") + 1] == "1"
    assert "--expect-head" not in posted and posted[posted.index("--run-url") + 1].endswith("/acme/shop/actions/runs/55")
    assert outputs(tmp_path) == {"mode": "single", "exit-code": "1", "findings": "1", "stored": "false"}
    assert "### dry-lint" in (tmp_path / "summary").read_text()


def test_fail_on_findings_fails_the_step(github_env, tmp_path) -> None:
    github_env("pull_request", pull_request(), key="secret", fail_on_findings="true")
    with patch.object(action, "dry_lint", side_effect=cli_writes_comment(tmp_path, [ANNOTATION])), \
            patch.object(sticky, "main", return_value=0):
        assert action.main(["run"]) == 1


def test_without_a_judge_nothing_is_annotated_commented_or_failed(github_env, tmp_path, capsys) -> None:
    github_env("pull_request", pull_request(), fail_on_findings="true")
    with patch.object(action, "dry_lint", side_effect=cli_writes_comment(tmp_path, [])) as cli, \
            patch.object(sticky, "main") as post:
        assert action.main(["run"]) == 0
    args = cli.call_args.args
    assert args[args.index("--judge") + 1] == "none" and args[args.index("--format") + 1] == "text"
    post.assert_not_called()
    assert "Set typesafe-api-key" in capsys.readouterr().out
    assert outputs(tmp_path)["findings"] == "0"


def test_comment_off_means_no_comment(github_env, tmp_path) -> None:
    github_env("pull_request", pull_request(), key="secret", comment="false")
    with patch.object(action, "dry_lint", side_effect=cli_writes_comment(tmp_path, [ANNOTATION])), \
            patch.object(sticky, "main") as post:
        assert action.main(["run"]) == 0
    post.assert_not_called()


def test_a_dry_lint_error_fails_the_step_and_posts_nothing(github_env, tmp_path) -> None:
    github_env("pull_request", pull_request(), key="secret")
    with patch.object(action, "dry_lint", side_effect=cli_writes_comment(tmp_path, [], code=2)), \
            patch.object(sticky, "main") as post:
        assert action.main(["run"]) == 2
    post.assert_not_called()
    assert outputs(tmp_path)["exit-code"] == "2"


def test_a_fork_pull_request_only_proposes_candidates(github_env, tmp_path, capsys) -> None:
    github_env("pull_request", pull_request(fork=True), key="leaked?")
    with patch.object(action, "dry_lint", return_value=(0, [])) as cli, patch.object(sticky, "main") as post:
        assert action.main(["run"]) == 0
    args = cli.call_args.args
    assert args[0] == "detect" and Path(args[args.index("--out") + 1]).parts[-2:] == ("dry-lint", "candidates.json")
    assert "--judge" not in args
    post.assert_not_called()
    assert "dry-lint-candidates" in capsys.readouterr().out


def test_judge_mode_comments_on_the_pull_request_of_the_triggering_commit(github_env, tmp_path) -> None:
    github_env("workflow_run", WORKFLOW_RUN, key="secret")
    candidates = tmp_path / "runner" / "dry-lint" / "in" / "candidates.json"
    candidates.parent.mkdir(parents=True)
    candidates.write_text("{}")
    fake = cli_writes_comment(tmp_path, [ANNOTATION], run={"pull_request": 7, "head": HEAD, "repository": "acme/shop"})
    with patch.object(action, "dry_lint", side_effect=fake) as cli, patch.object(sticky, "main", return_value=0) as post:
        assert action.main(["run"]) == 0
    args = cli.call_args_list[0].args
    assert args[0] == "judge" and args[args.index("--candidates") + 1] == str(candidates)
    posted = post.call_args.args[0]
    assert posted[posted.index("--pull-request") + 1] == "7" and posted[posted.index("--expect-head") + 1] == HEAD


def test_judge_mode_refuses_candidates_from_another_commit(github_env, tmp_path, capsys) -> None:
    github_env("workflow_run", WORKFLOW_RUN, key="secret")
    candidates = tmp_path / "runner" / "dry-lint" / "in" / "candidates.json"
    candidates.parent.mkdir(parents=True)
    candidates.write_text("{}")
    forged = cli_writes_comment(tmp_path, [ANNOTATION], run={"pull_request": 1, "head": "f" * 40})
    with patch.object(action, "dry_lint", side_effect=forged), patch.object(sticky, "main") as post:
        assert action.main(["run"]) == 2
    post.assert_not_called()
    assert "not from the triggering run" in capsys.readouterr().out


def test_judge_mode_without_candidates_has_nothing_to_do(github_env, tmp_path, capsys) -> None:
    github_env("workflow_run", WORKFLOW_RUN, key="secret")
    with patch.object(action, "dry_lint") as cli:
        assert action.main(["run"]) == 0
    cli.assert_not_called()
    assert "nothing to judge" in capsys.readouterr().out


def test_plan_tells_the_action_which_steps_to_run(github_env, tmp_path) -> None:
    github_env("workflow_run", WORKFLOW_RUN)
    assert action.main(["plan"]) == 0
    assert outputs(tmp_path) == {"mode": "judge", "workflow-run-id": "991"}


def test_a_bad_mode_input_is_reported_as_an_error(github_env, tmp_path, capsys) -> None:
    github_env("pull_request", pull_request(), mode="sometimes")
    assert action.main(["run"]) == 2
    assert "::error title=dry-lint::Unknown mode" in capsys.readouterr().out


def test_dry_lint_runs_the_installed_cli_and_echoes_its_output(capsys) -> None:
    code, lines = action.dry_lint("--version")
    assert code == 0 and lines[0].startswith("dry-lint ")
    assert capsys.readouterr().out.startswith("dry-lint ")


# End to end: the real CLI on a throwaway repository, a real judge command, and an in-memory GitHub.


def pr_event(repo: Repo, fork: bool = False) -> dict:
    event = pull_request(fork)
    event["pull_request"]["head"]["sha"] = repo.git("rev-parse", "HEAD").strip()
    event["pull_request"]["base"]["sha"] = repo.git("rev-parse", "main").strip()
    return event


def test_a_pull_request_that_reimplements_a_helper_gets_one_comment_that_tracks_the_fix(
        repo: Repo, github_env, tmp_path, twin_judge, capsys) -> None:
    github = FakeGitHub(head=repo.git("rev-parse", "HEAD").strip())
    github_env("pull_request", pr_event(repo), judge="command", judge_command=twin_judge,
               working_directory=str(repo.root))
    assert action.main(["run"], transport=httpx.MockTransport(github)) == 0
    out = capsys.readouterr().out
    assert "::warning file=src/widgets/caption.py,line=1" in out
    [body] = github.stickies()
    assert "preview_caption_text" in body and "src/text.py::shorten_text" in body
    assert outputs(tmp_path)["findings"] == "1" and outputs(tmp_path)["stored"] == "true"

    # The next push changes nothing that matters: the verdict comes from the store, the comment is edited.
    first = judge_calls(tmp_path)
    assert action.main(["run"], transport=httpx.MockTransport(github)) == 0
    assert judge_calls(tmp_path) == first and len(github.stickies()) == 1

    # The author reuses the existing helper: the comment says so instead of going stale.
    repo.write("src/widgets/caption.py", "from src.text import shorten_text\n\n\ndef register_widget(registry, widget):\n"
               "    registry.add(widget)\n    return widget\n")
    repo.commit("reuse shorten_text")
    assert action.main(["run"], transport=httpx.MockTransport(github)) == 0
    [body] = github.stickies()
    assert "Resolved" in body and "preview_caption_text" not in body


def test_without_a_judge_the_real_cli_lists_look_alikes_and_comments_nothing(repo: Repo, github_env, tmp_path, capsys):
    github = FakeGitHub()
    github_env("pull_request", pr_event(repo), working_directory=str(repo.root))
    assert action.main(["run"], transport=httpx.MockTransport(github)) == 0
    out = capsys.readouterr().out
    assert "preview_caption_text" in out and "::warning file=" not in out
    assert github.stickies() == [] and github.writes == []


def test_a_fork_pull_request_is_judged_by_the_workflow_run_job(repo: Repo, github_env, tmp_path, twin_judge) -> None:
    head = repo.git("rev-parse", "HEAD").strip()
    github_env("pull_request", pr_event(repo, fork=True), working_directory=str(repo.root))
    assert action.main(["run"]) == 0
    candidates = tmp_path / "runner" / "dry-lint" / "candidates.json"
    assert candidates.exists()

    # The judge workflow downloads the artifact, then runs with secrets from the default branch.
    downloaded = tmp_path / "runner" / "dry-lint" / "in" / "candidates.json"
    downloaded.parent.mkdir(parents=True)
    downloaded.write_text(candidates.read_text())
    github = FakeGitHub(head=head)
    github_env("workflow_run", {"workflow_run": {"id": 3, "head_sha": head, "event": "pull_request"}},
               judge="command", judge_command=twin_judge, working_directory=str(repo.root))
    assert action.main(["run"], transport=httpx.MockTransport(github)) == 0
    [body] = github.stickies()
    assert "preview_caption_text" in body and f"commit {head[:7]}" in body
    [check] = github.check_runs
    assert (check["name"], check["head_sha"], check["conclusion"]) == ("dry-lint", head, "neutral")
    assert check["output"]["annotations"][0]["path"] == "src/widgets/caption.py"


def judged_report(tmp_path: Path, repo: Repo, twin_judge: str, github_env) -> tuple[Path, str]:
    """Run detect then judge for real, leaving report.json; return it and the head commit."""
    head = repo.git("rev-parse", "HEAD").strip()
    github_env("pull_request", pr_event(repo, fork=True), working_directory=str(repo.root))
    action.main(["run"])
    work = tmp_path / "runner" / "dry-lint"
    (work / "in").mkdir()
    (work / "in" / "candidates.json").write_text((work / "candidates.json").read_text())
    return work / "report.json", head


@pytest.mark.parametrize("status, outcome", [(403, "forbidden"), (201, "posted")])
def test_a_check_run_the_token_may_not_post_is_a_warning(repo, github_env, tmp_path, twin_judge, capsys, status, outcome):
    report, head = judged_report(tmp_path, repo, twin_judge, github_env)
    github_env("workflow_run", {"workflow_run": {"id": 3, "head_sha": head}}, judge="command",
               judge_command=twin_judge, working_directory=str(repo.root), comment="false", check_run="false")
    assert action.main(["run"]) == 0
    github_env("workflow_run", {"workflow_run": {"id": 3, "head_sha": head}}, check_run="true")
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json={}))
    assert action.check_run(repo.root, "acme/shop", report, transport) == outcome
    assert ("checks: write" in capsys.readouterr().out) is (status == 403)


def test_check_run_errors_other_than_permissions_are_raised(repo, github_env, tmp_path, twin_judge) -> None:
    report, head = judged_report(tmp_path, repo, twin_judge, github_env)
    github_env("workflow_run", {"workflow_run": {"id": 3, "head_sha": head}}, judge="command",
               judge_command=twin_judge, working_directory=str(repo.root), comment="false", check_run="false")
    action.main(["run"])
    github_env("workflow_run", {"workflow_run": {"id": 3, "head_sha": head}}, check_run="true")
    with pytest.raises(httpx.HTTPStatusError):
        action.check_run(repo.root, "acme/shop", report, httpx.MockTransport(lambda request: httpx.Response(500)))


def test_no_check_run_when_off_or_when_the_report_cannot_be_rendered(github_env, tmp_path) -> None:
    github_env("workflow_run", WORKFLOW_RUN, check_run="false")
    assert action.check_run(tmp_path, "acme/shop", tmp_path / "report.json") == "off"
    github_env("workflow_run", WORKFLOW_RUN, check_run="true")
    broken = tmp_path / "report.json"
    broken.write_text("not json")
    assert action.check_run(tmp_path, "acme/shop", broken) == "failed"


def test_a_base_the_checkout_lacks_is_fetched(repo: Repo, tmp_path: Path) -> None:
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "--single-branch", "--branch", "feature", f"file://{repo.root}", str(clone)],
                   check=True)
    repo.git("checkout", "-q", "main")
    repo.write("src/later.py", "def later(x):\n    return x\n")
    repo.commit("later on main")
    later = repo.git("rev-parse", "HEAD").strip()
    ensure_history(clone, later)
    assert subprocess.run(["git", "cat-file", "-e", f"{later}^{{commit}}"], cwd=clone).returncode == 0
