import hashlib
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from test_action_sticky import FakeGitHub
from test_ledger import push
from test_report import finding

from dry_lint import action, sticky
from dry_lint.action import count_findings, default_branch, ensure_history, resolve_base, resolve_judge, resolve_mode
from dry_lint.ledger import PullLedger, RepositoryLedger, counter_key

from conftest import Repo, clear_judge_credentials, judge_calls, run_cli

HEAD, BASE = "c" * 40, "b" * 40
ANNOTATION = "::warning file=src/a.py,line=3,endLine=9,title=dry-lint::clip looks like src/b.py::shorten"


def pull_request(fork: bool = False) -> dict:
    head_repo = "someone/shop" if fork else "acme/shop"
    return {
        "pull_request": {
            "number": 7,
            "head": {"sha": HEAD, "repo": {"full_name": head_repo}},
            "base": {"sha": BASE, "repo": {"full_name": "acme/shop"}},
        }
    }


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
    ("auto", True, "auto"), ("auto", False, "none"), ("", False, "none"), ("command", False, "command"),
    ("jev", True, "jev"),
])  # fmt: skip
def test_auto_leaves_the_preset_to_dry_lint_while_any_judge_key_is_present(requested, has_key, judge) -> None:
    assert resolve_judge(requested, has_key) == judge


def test_strict_action_fails_without_credentials(repo: Repo, github_env, tmp_path: Path) -> None:
    github_env("pull_request", pr_event(repo), working_directory=str(repo.root), require_complete="true")
    assert action.main(["run"]) == 2
    assert outputs(tmp_path)["exit-code"] == "2"


def test_strict_fork_without_artifact_cannot_pass(github_env) -> None:
    github_env("workflow_run", WORKFLOW_RUN, require_complete="true")
    assert action.main(["run"]) == 2


def test_a_sweep_action_audits_without_mutating_the_baseline(
    repo: Repo, tmp_path: Path, twin_judge: str, github_env
) -> None:
    assert run_cli(repo, tmp_path, "--init", "--judge", "command", "--judge-command", twin_judge, command="sweep") == 0
    baseline = repo.root / ".dry-lint/baseline.json"
    before = baseline.read_bytes()
    github_env(
        "workflow_dispatch",
        {},
        mode="sweep",
        working_directory=str(repo.root),
        judge="command",
        judge_command=twin_judge,
        require_complete="true",
        baseline=".dry-lint/baseline.json",
    )
    assert action.main(["run"]) == 0
    assert outputs(tmp_path)["mode"] == "sweep"
    assert baseline.read_bytes() == before


def test_baselined_action_checks_target_branch_allowances(
    repo: Repo, tmp_path: Path, twin_judge: str, github_env
) -> None:
    assert run_cli(repo, tmp_path, "--init", "--judge", "command", "--judge-command", twin_judge, command="sweep") == 0
    github_env(
        "pull_request",
        pr_event(repo),
        working_directory=str(repo.root),
        judge="command",
        judge_command=twin_judge,
        baseline=".dry-lint/baseline.json",
        require_complete="true",
    )
    head = repo.git("rev-parse", "HEAD").strip()
    assert action.main(["run"], transport=httpx.MockTransport(FakeGitHub(head=head))) == 0
    path = repo.root / "src/widgets/caption.py"
    path.write_text(path.read_text().replace("max_len - 1", "max_len - 2"))
    repo.commit()
    event = pr_event(repo)
    event["pull_request"]["labels"] = [{"name": "dry-lint: override"}]
    github_env(
        "pull_request",
        event,
        working_directory=str(repo.root),
        judge="command",
        judge_command=twin_judge,
        baseline=".dry-lint/baseline.json",
        require_complete="true",
    )
    github = FakeGitHub(head=repo.git("rev-parse", "HEAD").strip())
    assert action.main(["run"], transport=httpx.MockTransport(github)) == 1
    assert outputs(tmp_path)["overridden"] == "false"
    assert "cannot widen the ratchet" in github.stickies()[0]


def test_incomplete_fork_judging_publishes_a_failing_check(
    repo: Repo, tmp_path: Path, twin_judge: str, github_env
) -> None:
    report, head = judged_report(tmp_path, repo, twin_judge, github_env)
    github = FakeGitHub(head=head)
    github_env(
        "workflow_run",
        {"workflow_run": {"id": 3, "head_sha": head}},
        working_directory=str(repo.root),
        require_complete="true",
    )
    assert action.main(["run"], transport=httpx.MockTransport(github)) == 2
    assert github.check_runs[-1]["conclusion"] == "failure"


def test_findings_are_counted_from_file_annotations_only() -> None:
    lines = [ANNOTATION, ANNOTATION.replace("::warning", "::error"), "::notice title=dry-lint::hi", "dry-lint: 3 pairs"]
    assert count_findings(lines) == (2, 1)


def test_a_shallow_checkout_gets_the_history_a_merge_base_needs(repo: Repo, tmp_path: Path) -> None:
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", "--branch", "feature", f"file://{repo.root}", str(clone)], check=True
    )
    main_sha = repo.git("rev-parse", "main").strip()
    ensure_history(clone, main_sha)
    assert subprocess.run(["git", "merge-base", main_sha, "HEAD"], cwd=clone, capture_output=True).returncode == 0


@pytest.fixture
def github_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The environment a composite action step sees, with its output files in tmp_path."""

    def set_event(name: str, payload: dict, **inputs: str) -> Path:
        event = tmp_path / "event.json"
        event.write_text(json.dumps(payload))
        values = {
            "GITHUB_EVENT_NAME": name,
            "GITHUB_EVENT_PATH": str(event),
            "GITHUB_REPOSITORY": "acme/shop",
            "GITHUB_REPOSITORY_ID": "4242",
            "GITHUB_RUN_ID": "55",
            "GITHUB_OUTPUT": str(tmp_path / "output"),
            "GITHUB_TOKEN": "token",
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
            "RUNNER_TEMP": str(tmp_path / "runner"),
            "INPUT_COMMENT": "true",
            "INPUT_CHECK_RUN": "true",
            "INPUT_WORKING_DIRECTORY": str(tmp_path),
        }
        values.update({f"INPUT_{k.upper()}": v for k, v in inputs.items() if k != "key"})
        # Hermetic: a developer's or Claude Code's own keys must never reach a judge from a test.
        clear_judge_credentials(monkeypatch)
        monkeypatch.delenv("GITHUB_RUN_ATTEMPT", raising=False)  # set when the tests themselves run in Actions
        if "key" in inputs:
            values["TYPESAFE_AI_API_KEY"] = inputs["key"]
        for name_, value in values.items():
            monkeypatch.setenv(name_, value)
        return tmp_path

    return set_event


def outputs(tmp_path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in (tmp_path / "output").read_text().splitlines())


def cli_writes_comment(
    tmp_path: Path, findings: list[str], code: int = 0, run: dict | None = None, judge: str | None = "test-judge"
):
    """
    A stand-in for the dry-lint CLI: judging leaves the files the real one writes (report.json names the judge,
    or null when nothing was judged), and `report --format github` renders the findings as annotations.
    """

    def fake(*args: str, echo: bool = True):
        work = tmp_path / "runner" / "dry-lint"
        if args[0] == "report":
            return code, findings
        (work / "comment.md").write_text("<!-- dry-lint -->\n### dry-lint\n")
        (work / "report.json").write_text(json.dumps({"run": run or {}, "judge": judge}))
        return code, [f"dry-lint: {len(findings)} finding(s)"]

    return fake


def test_single_mode_comments_and_reports_without_failing_by_default(github_env, tmp_path) -> None:
    github_env("pull_request", pull_request(), key="secret")
    with (
        patch.object(action, "dry_lint", side_effect=cli_writes_comment(tmp_path, [ANNOTATION])) as cli,
        patch.object(sticky, "main", return_value=0) as post,
    ):
        assert action.main(["run"]) == 0
    args = cli.call_args_list[0].args
    assert args[0] == "check" and args[args.index("--base") + 1] == BASE and "--judge" not in args
    assert args[args.index("--format") + 1] == "text"
    rendered = cli.call_args_list[1].args
    assert rendered[0] == "report" and rendered[rendered.index("--format") + 1] == "github"
    posted = post.call_args.args[0]
    assert posted[posted.index("--pull-request") + 1] == "7" and posted[posted.index("--findings") + 1] == "1"
    assert posted[posted.index("--expect-head") + 1] == HEAD
    assert posted[posted.index("--run-url") + 1].endswith("/acme/shop/actions/runs/55")
    assert outputs(tmp_path) == {
        "mode": "single",
        "exit-code": "0",
        "findings": "1",
        "blocking": "0",
        "overridden": "false",
        "stored": "false",
    }
    assert posted[posted.index("--note") + 1] == ""
    assert "### dry-lint" in (tmp_path / "summary").read_text()


BLOCKING = ANNOTATION.replace("::warning", "::error")


def labelled(*names: str) -> dict:
    event = pull_request()
    event["pull_request"]["labels"] = [{"name": name} for name in names]
    return event


def test_a_near_certain_duplicate_fails_the_check_and_says_how_to_override(github_env, tmp_path) -> None:
    github_env("pull_request", labelled("enhancement"), key="secret")
    with (
        patch.object(action, "dry_lint", side_effect=cli_writes_comment(tmp_path, [BLOCKING, ANNOTATION], code=1)),
        patch.object(sticky, "main", return_value=0) as post,
    ):
        assert action.main(["run"]) == 1
    note = post.call_args.args[0][post.call_args.args[0].index("--note") + 1]
    assert note.startswith("> [!CAUTION]\n> **Blocking:** 1 finding(s)") and "`dry-lint: override` label" in note
    assert outputs(tmp_path) | {} == {
        "mode": "single",
        "exit-code": "1",
        "findings": "2",
        "blocking": "1",
        "overridden": "false",
        "stored": "false",
    }


def test_findings_below_fail_at_only_warn(github_env, tmp_path) -> None:
    github_env("pull_request", pull_request(), key="secret")
    with (
        patch.object(action, "dry_lint", side_effect=cli_writes_comment(tmp_path, [ANNOTATION], code=0)),
        patch.object(sticky, "main", return_value=0),
    ):
        assert action.main(["run"]) == 0


def test_the_override_label_turns_a_blocking_finding_into_a_warning(github_env, tmp_path, capsys) -> None:
    github_env("pull_request", labelled("dry-lint: override"), key="secret")
    with (
        patch.object(action, "dry_lint", side_effect=cli_writes_comment(tmp_path, [BLOCKING], code=1)),
        patch.object(sticky, "main", return_value=0) as post,
    ):
        assert action.main(["run"]) == 0
    note = post.call_args.args[0][post.call_args.args[0].index("--note") + 1]
    assert note.startswith("> [!NOTE]\n> **Overridden:**")
    assert "overridden by the `dry-lint: override` label" in capsys.readouterr().out
    assert outputs(tmp_path)["overridden"] == "true"


def test_the_override_label_name_is_configurable(github_env, tmp_path) -> None:
    github_env("pull_request", labelled("ship-it"), key="secret", override_label="ship-it")
    with (
        patch.object(action, "dry_lint", side_effect=cli_writes_comment(tmp_path, [BLOCKING], code=1)),
        patch.object(sticky, "main", return_value=0),
    ):
        assert action.main(["run"]) == 0


def test_warn_only_never_fails_and_does_not_claim_to_block(github_env, tmp_path) -> None:
    github_env("pull_request", pull_request(), key="secret", warn_only="true")
    with (
        patch.object(action, "dry_lint", side_effect=cli_writes_comment(tmp_path, [BLOCKING], code=1)),
        patch.object(sticky, "main", return_value=0) as post,
    ):
        assert action.main(["run"]) == 0
    note = post.call_args.args[0][post.call_args.args[0].index("--note") + 1]
    assert note.startswith("> [!NOTE]\n> **Advisory mode:**") and "does not fail" in note


def test_without_a_judge_nothing_is_annotated_commented_or_failed(github_env, tmp_path, capsys) -> None:
    github_env("pull_request", pull_request())
    with (
        patch.object(action, "dry_lint", side_effect=cli_writes_comment(tmp_path, [])) as cli,
        patch.object(sticky, "main") as post,
    ):
        assert action.main(["run"]) == 0
    args = cli.call_args_list[0].args
    assert args[args.index("--judge") + 1] == "none" and args[args.index("--format") + 1] == "text"
    post.assert_not_called()
    assert "Set typesafe-api-key" in capsys.readouterr().out
    assert outputs(tmp_path)["findings"] == "0"


def test_comment_off_means_no_comment(github_env, tmp_path) -> None:
    github_env("pull_request", pull_request(), key="secret", comment="false")
    with (
        patch.object(action, "dry_lint", side_effect=cli_writes_comment(tmp_path, [ANNOTATION])),
        patch.object(sticky, "main") as post,
    ):
        assert action.main(["run"]) == 0
    post.assert_not_called()


def test_a_dry_lint_error_fails_the_step_and_posts_nothing(github_env, tmp_path) -> None:
    github_env("pull_request", pull_request(), key="secret")
    with (
        patch.object(action, "dry_lint", side_effect=cli_writes_comment(tmp_path, [], code=2)),
        patch.object(sticky, "main") as post,
    ):
        assert action.main(["run"]) == 2
    post.assert_not_called()
    assert outputs(tmp_path)["exit-code"] == "2"


def test_a_fork_pull_request_only_proposes_candidates(github_env, tmp_path, capsys) -> None:
    github_env("pull_request", pull_request(fork=True), key="leaked?")
    with patch.object(action, "dry_lint", return_value=(0, [])) as cli, patch.object(sticky, "main") as post:
        assert action.main(["run"]) == 0
    args = cli.call_args_list[0].args
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
    with (
        patch.object(action, "dry_lint", side_effect=fake) as cli,
        patch.object(sticky, "main", return_value=0) as post,
    ):
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


@pytest.mark.parametrize("mode", ["single", "detect"])
@pytest.mark.parametrize("invalid_source", [False, True], ids=["valid", "syntax-error"])
def test_pr_analysis_uses_head_source_when_merge_ref_contains_newer_main(
    repo: Repo, github_env, tmp_path: Path, mode: str, invalid_source: bool, capsys
) -> None:
    """A rerun's event base can predate its synthetic merge; main-only code is never PR work."""
    if invalid_source:
        repo.write("src/broken.py", "def broken(:\n")
        repo.commit("invalid source on feature")
    event = pr_event(repo)
    head = event["pull_request"]["head"]["sha"]
    repo.git("checkout", "main")
    repo.write("src/main_only.py", "def unrelated(value):\n    return value.strip().lower()\n")
    repo.write(".dry-lint.toml", 'include = ["src/main_only.py"]\n')
    repo.commit("main advances after the event")
    repo.git("merge", "--no-ff", "feature", "-m", "synthetic merge")
    merge = repo.git("rev-parse", "HEAD")
    before = repo.git("worktree", "list", "--porcelain")
    github_env(
        "pull_request",
        event,
        mode=mode,
        judge="none",
        working_directory=str(repo.root),
        require_complete="true" if invalid_source else "false",
    )

    assert action.main(["run"]) == (2 if invalid_source else 0)

    if invalid_source:
        assert "broken.py" in capsys.readouterr().err
    else:
        filename = "report.json" if mode == "single" else "candidates.json"
        result = json.loads((tmp_path / "runner" / "dry-lint" / filename).read_text())
        assert result["changed"] == 2  # the feature's two functions, not unrelated() or main's config
        assert result["run"]["head"] == head
    assert repo.git("rev-parse", "HEAD") == merge
    assert repo.git("worktree", "list", "--porcelain") == before


def test_a_pull_request_that_reimplements_a_helper_gets_one_comment_that_tracks_the_fix(
    repo: Repo, github_env, tmp_path, twin_judge, capsys, monkeypatch
) -> None:
    github = FakeGitHub(head=repo.git("rev-parse", "HEAD").strip())
    github_env(
        "pull_request", pr_event(repo), judge="command", judge_command=twin_judge, working_directory=str(repo.root)
    )
    assert action.main(["run"], transport=httpx.MockTransport(github)) == 1  # 0.85 reaches the default fail_at (0.8)
    out = capsys.readouterr().out
    assert "::error file=src/widgets/caption.py,line=1" in out  # 0.85 >= the default fail_at
    [body] = github.stickies()
    assert "`preview_caption_text` ≈ `shorten_text`" in body and "distinct-from src/text.py::shorten_text" in body
    assert f"/blob/{github.head}/src/widgets/caption.py#L1-L5" in body
    assert outputs(tmp_path)["findings"] == "1" and outputs(tmp_path)["stored"] == "true"

    # The next push changes nothing that matters: the verdict comes from the store, the comment is edited.
    first = judge_calls(tmp_path)
    monkeypatch.setenv("GITHUB_RUN_ID", "56")
    assert action.main(["run"], transport=httpx.MockTransport(github)) == 1
    assert judge_calls(tmp_path) == first and len(github.stickies()) == 1

    # The author reuses the existing helper: the comment says so instead of going stale.
    repo.write(
        "src/widgets/caption.py",
        "from src.text import shorten_text\n\n\ndef register_widget(registry, widget):\n"
        "    registry.add(widget)\n    return widget\n",
    )
    repo.commit("reuse shorten_text")
    github.head = repo.git("rev-parse", "HEAD").strip()
    github_env(
        "pull_request", pr_event(repo), judge="command", judge_command=twin_judge, working_directory=str(repo.root)
    )
    monkeypatch.setenv("GITHUB_RUN_ID", "57")
    assert action.main(["run"], transport=httpx.MockTransport(github)) == 0
    [body] = github.stickies()
    assert "Resolved" in body and "distinct-from src/text.py::shorten_text" not in body
    # The ledger remembers what the fix was worth: the run on the same commit was not a new push.
    assert "**1 duplicate kept out of the codebase**" in body and "across 2 pushes" in body
    assert "`preview_caption_text` ≈ `shorten_text` · found in push 1, kept out in push 2" in body


def test_typescript_pull_request_updates_and_resolves_one_sticky_comment(
    repo: Repo, github_env, tmp_path, twin_judge, capsys
):
    repo.git("checkout", "-q", "main")
    repo.write(".dry-lint.toml", 'include = ["*.ts", "src/filler.py"]')
    repo.write(
        "src/text.ts",
        """export function shorten_text(text: string, limit: number) {
      if (text.length <= limit) return text;
      return text.slice(0, limit - 1).trimEnd() + "…";
    }""",
    )
    repo.write("package.json", '{"scripts":{"test":"bun test"}}')
    repo.commit()
    repo.git("checkout", "-q", "-b", "typescript")
    repo.write(
        "src/caption.ts",
        """export const preview_caption_text = (caption: string, limit: number) => {
      if (caption.length <= limit) return caption;
      return caption.slice(0, limit - 1).trimEnd() + "…";
    };""",
    )
    repo.commit()
    github = FakeGitHub(head=repo.git("rev-parse", "HEAD").strip())
    github_env(
        "pull_request",
        pr_event(repo),
        judge="command",
        judge_command=twin_judge,
        working_directory=str(repo.root),
        warn_only="true",
    )
    for _ in range(2):
        assert action.main(["run"], transport=httpx.MockTransport(github)) == 0
    [body] = github.stickies()
    assert "`preview_caption_text` ≈ `shorten_text`" in body
    assert "```ts\n// dry-lint: distinct-from src/text.ts::shorten_text\n```" in body
    assert "`// dry-lint: ignore`" in body and judge_calls(tmp_path) == 1
    assert "blocking" not in body
    assert "// dry-lint: distinct-from src/text.ts::shorten_text" in capsys.readouterr().out
    repo.write("src/caption.ts", 'export { shorten_text as preview_caption_text } from "./text";')
    repo.commit()
    github.head = repo.git("rev-parse", "HEAD").strip()
    github_env(
        "pull_request",
        pr_event(repo),
        judge="command",
        judge_command=twin_judge,
        working_directory=str(repo.root),
        warn_only="true",
    )
    assert action.main(["run"], transport=httpx.MockTransport(github)) == 0
    [body] = github.stickies()
    assert "Resolved" in body


def test_without_a_judge_the_real_cli_lists_look_alikes_and_comments_nothing(repo: Repo, github_env, tmp_path, capsys):
    github = FakeGitHub()
    github_env("pull_request", pr_event(repo), working_directory=str(repo.root))
    assert action.main(["run"], transport=httpx.MockTransport(github)) == 0
    out = capsys.readouterr().out
    assert "preview_caption_text" in out and "::warning file=" not in out
    assert github.stickies() == [] and github.writes == []


@pytest.mark.parametrize("mode", ["single", "detect"])
def test_workspace_action_keeps_primary_annotations_and_peer_links(repo, github_env, tmp_path, twin_judge, mode):
    from conftest import EXISTING

    peer = Repo(tmp_path / "peer checkout")
    peer.write("src/shared.py", EXISTING)
    peer.commit()
    repo.write(".dry-lint.toml", '[[consolidation]]\nrepository = "acme/common"\npath = "src"\n')
    repo.commit()
    github = FakeGitHub(head=repo.git("rev-parse", "HEAD").strip())
    github_env(
        "pull_request",
        pr_event(repo),
        mode=mode,
        judge="command",
        judge_command=twin_judge,
        working_directory=str(repo.root),
        warn_only="true",
        repositories=f"acme/shop={repo.root}\n\nacme/common={peer.root}\n",
    )
    assert action.main(["run"], transport=httpx.MockTransport(github)) == 0
    folder = tmp_path / "runner" / "dry-lint"
    data = json.loads((folder / ("report.json" if mode == "single" else "candidates.json")).read_text())
    pairs = [finding["candidate"] for finding in data["findings"]] if mode == "single" else data["candidates"]
    assert pairs and all(pair["new"]["origin"]["repository"] == "acme/shop" for pair in pairs)
    assert all(pair["existing"]["origin"]["repository"] == "acme/common" for pair in pairs)
    if mode == "single":
        [body] = github.stickies()
        assert "/acme/common/blob/" in body and "acme/common/src" in body


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
    github_env(
        "workflow_run",
        {"workflow_run": {"id": 3, "head_sha": head, "event": "pull_request"}},
        judge="command",
        judge_command=twin_judge,
        working_directory=str(repo.root),
    )
    assert action.main(["run"], transport=httpx.MockTransport(github)) == 1
    [body] = github.stickies()
    assert "`preview_caption_text`" in body and f"commit {head[:7]}" in body
    assert f"/blob/{head}/src/widgets/caption.py#L1-L5" in body
    [check] = github.check_runs
    assert (check["name"], check["head_sha"], check["conclusion"]) == ("dry-lint", head, "failure")
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
def test_a_check_run_the_token_may_not_post_is_a_warning(
    repo, github_env, tmp_path, twin_judge, capsys, status, outcome
):
    report, head = judged_report(tmp_path, repo, twin_judge, github_env)
    github_env(
        "workflow_run",
        {"workflow_run": {"id": 3, "head_sha": head}},
        judge="command",
        judge_command=twin_judge,
        working_directory=str(repo.root),
        comment="false",
        check_run="false",
    )
    assert action.main(["run"], transport=httpx.MockTransport(FakeGitHub(head=head))) == 1
    github_env("workflow_run", {"workflow_run": {"id": 3, "head_sha": head}}, check_run="true")
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json={}))
    assert action.check_run(repo.root, "acme/shop", report, transport) == outcome
    assert ("checks: write" in capsys.readouterr().out) is (status == 403)


def test_check_run_errors_other_than_permissions_are_raised(repo, github_env, tmp_path, twin_judge) -> None:
    report, head = judged_report(tmp_path, repo, twin_judge, github_env)
    github_env(
        "workflow_run",
        {"workflow_run": {"id": 3, "head_sha": head}},
        judge="command",
        judge_command=twin_judge,
        working_directory=str(repo.root),
        comment="false",
        check_run="false",
    )
    action.main(["run"], transport=httpx.MockTransport(FakeGitHub(head=head)))
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
    subprocess.run(
        ["git", "clone", "-q", "--single-branch", "--branch", "feature", f"file://{repo.root}", str(clone)], check=True
    )
    repo.git("checkout", "-q", "main")
    repo.write("src/later.py", "def later(x):\n    return x\n")
    repo.commit("later on main")
    later = repo.git("rev-parse", "HEAD").strip()
    ensure_history(clone, later)
    assert subprocess.run(["git", "cat-file", "-e", f"{later}^{{commit}}"], cwd=clone).returncode == 0


def judge_run(tmp_path: Path, lines: list[str], code: int):
    """A stand-in CLI for judge mode: judges with `code`, and renders the check run the way dry-lint does."""
    judged = cli_writes_comment(tmp_path, lines, code=code, run={"pull_request": PR_NUMBER, "head": HEAD})

    def fake(*args: str, echo: bool = True):
        if args[0] == "report" and "check-run" in args:
            return 1, [json.dumps({"name": "dry-lint", "head_sha": HEAD, "conclusion": "neutral"})]
        return judged(*args)

    return fake


PR_NUMBER = 7


@pytest.mark.parametrize("labels, result, conclusion", [
    ([], 1, "failure"),
    (["dry-lint: override"], 0, "neutral"),
])  # fmt: skip
def test_a_fork_pull_request_is_blocked_through_its_check_run_unless_overridden(
    github_env, tmp_path, labels, result, conclusion
) -> None:
    github_env("workflow_run", WORKFLOW_RUN, key="secret")
    candidates = tmp_path / "runner" / "dry-lint" / "in" / "candidates.json"
    candidates.parent.mkdir(parents=True)
    candidates.write_text("{}")
    github = FakeGitHub(head=HEAD, labels=labels)
    with (
        patch.object(action, "dry_lint", side_effect=judge_run(tmp_path, [BLOCKING], code=1)),
        patch.object(sticky, "banner_available", return_value=False),
    ):
        assert action.main(["run"], transport=httpx.MockTransport(github)) == result
    [check] = github.check_runs
    assert check["conclusion"] == conclusion
    assert ("**Overridden:**" in github.stickies()[0]) is bool(labels)


def test_labels_are_unknown_without_a_token_or_when_the_api_fails(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert action.pull_labels("acme/shop", 7) == set()
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    assert action.pull_labels("acme/shop", 7, httpx.MockTransport(lambda request: httpx.Response(500))) == set()


def test_a_near_certain_reimplementation_fails_the_check_end_to_end(
    repo: Repo, github_env, tmp_path, blocking_twin_judge, capsys
) -> None:
    github = FakeGitHub(head=repo.git("rev-parse", "HEAD").strip())
    github_env(
        "pull_request",
        pr_event(repo),
        judge="command",
        judge_command=blocking_twin_judge,
        working_directory=str(repo.root),
    )
    assert action.main(["run"], transport=httpx.MockTransport(github)) == 1
    assert "::error file=src/widgets/caption.py,line=1" in capsys.readouterr().out
    [body] = github.stickies()
    assert "**Blocking:** 1 finding(s)" in body and "`dry-lint: override` label" in body
    assert outputs(tmp_path)["blocking"] == "1"


def test_the_override_label_lets_a_blocking_finding_through_end_to_end(
    repo: Repo, github_env, tmp_path, blocking_twin_judge
) -> None:
    github = FakeGitHub(head=repo.git("rev-parse", "HEAD").strip())
    event = pr_event(repo)
    event["pull_request"]["labels"] = [{"name": "dry-lint: override"}]
    github_env(
        "pull_request", event, judge="command", judge_command=blocking_twin_judge, working_directory=str(repo.root)
    )
    assert action.main(["run"], transport=httpx.MockTransport(github)) == 0
    [body] = github.stickies()
    assert "**Overridden:**" in body and outputs(tmp_path)["overridden"] == "true"


def test_an_inline_ignore_settles_the_pair_before_any_judge_call(
    repo: Repo, github_env, tmp_path, blocking_twin_judge
) -> None:
    source = (repo.root / "src/widgets/caption.py").read_text()
    repo.write(
        "src/widgets/caption.py",
        source.replace("    if len(caption_text)", "    # dry-lint: ignore\n    if len(caption_text)", 1),
    )
    repo.commit("this caption rule is deliberately separate")
    github = FakeGitHub(head=repo.git("rev-parse", "HEAD").strip())
    github_env(
        "pull_request",
        pr_event(repo),
        judge="command",
        judge_command=blocking_twin_judge,
        working_directory=str(repo.root),
    )
    assert action.main(["run"], transport=httpx.MockTransport(github)) == 0
    [body] = github.stickies()
    assert "✨ No duplicated concepts" in body and "| Settled by a rule | 1 |" in body and judge_calls(tmp_path) == 0

    quiet = FakeGitHub(head=github.head)
    github_env(
        "pull_request",
        pr_event(repo),
        judge="command",
        judge_command=blocking_twin_judge,
        working_directory=str(repo.root),
        comment_on_clean="false",
    )
    assert action.main(["run"], transport=httpx.MockTransport(quiet)) == 0
    assert quiet.stickies() == []


def test_the_fail_at_input_raises_the_bar_so_lower_findings_only_warn(
    repo: Repo, github_env, tmp_path, twin_judge, capsys
) -> None:
    github = FakeGitHub(head=repo.git("rev-parse", "HEAD").strip())
    github_env(
        "pull_request",
        pr_event(repo),
        judge="command",
        judge_command=twin_judge,
        working_directory=str(repo.root),
        fail_at="0.91",
    )
    assert action.main(["run"], transport=httpx.MockTransport(github)) == 0
    assert "::warning file=src/widgets/caption.py,line=1" in capsys.readouterr().out
    [body] = github.stickies()
    assert "**Blocking:**" not in body
    assert outputs(tmp_path)["blocking"] == "0" and outputs(tmp_path)["findings"] == "1"


def test_the_fail_at_input_reaches_every_dry_lint_command(github_env, tmp_path) -> None:
    github_env("pull_request", pull_request(), key="secret", fail_at="0.95")
    with (
        patch.object(action, "dry_lint", side_effect=cli_writes_comment(tmp_path, [])) as cli,
        patch.object(sticky, "main", return_value=0),
    ):
        action.main(["run"])
    args = cli.call_args_list[0].args
    assert args[args.index("--fail-at") + 1] == "0.95"


@pytest.mark.parametrize("key", ["ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"])
def test_any_judge_key_turns_judging_on_and_dry_lint_picks_the_preset(github_env, tmp_path, monkeypatch, key) -> None:
    github_env("pull_request", pull_request())
    monkeypatch.setenv(key, "secret")
    with (
        patch.object(action, "dry_lint", side_effect=cli_writes_comment(tmp_path, [ANNOTATION])) as cli,
        patch.object(sticky, "main", return_value=0) as post,
    ):
        action.main(["run"])
    args = cli.call_args_list[0].args
    assert "--judge" not in args and args[args.index("--format") + 1] == "text"
    assert cli.call_args_list[1].args[0] == "report"
    post.assert_called_once()


def test_preset_and_budget_inputs_pass_through_only_when_set(github_env, tmp_path) -> None:
    github_env("pull_request", pull_request(), key="secret", preset="jev", budget_usd="0.5")
    with (
        patch.object(action, "dry_lint", side_effect=cli_writes_comment(tmp_path, [])) as cli,
        patch.object(sticky, "main", return_value=0),
    ):
        action.main(["run"])
    args = cli.call_args_list[0].args
    assert args[args.index("--preset") + 1] == "jev" and args[args.index("--budget-usd") + 1] == "0.5"
    github_env("pull_request", pull_request(), key="secret", preset="", budget_usd="")
    with (
        patch.object(action, "dry_lint", side_effect=cli_writes_comment(tmp_path, [])) as cli,
        patch.object(sticky, "main", return_value=0),
    ):
        action.main(["run"])
    assert "--preset" not in cli.call_args_list[0].args and "--budget-usd" not in cli.call_args_list[0].args


def test_shallow_comparison_does_not_download_old_history_or_other_branches(tmp_path):
    remote = Repo(tmp_path / "remote")
    for i in range(40):
        remote.write("src/history.py", f"value = {i}\n")
        remote.commit()
    oldest = remote.git("rev-list", "--max-parents=0", "HEAD")
    base = remote.git("rev-parse", "HEAD")
    remote.git("checkout", "-b", "junk")
    remote.write("junk.bin", "unrelated branch content")
    remote.commit()
    junk = remote.git("rev-parse", "HEAD:junk.bin")
    remote.git("checkout", "-b", "feature", base)
    remote.write("src/new.py", "def new():\n    return 42\n")
    remote.commit()
    clone = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", "--branch", "feature", remote.root.as_uri(), str(clone)], check=True
    )
    ensure_history(clone, base)
    from dry_lint.detector import changed_lines
    from dry_lint.git import git

    assert changed_lines(clone, base) == {"src/new.py": {1, 2}}
    assert git(clone, "rev-parse", "--is-shallow-repository") == "true"
    for missing in (oldest, junk):
        assert not git(clone, "cat-file", "-t", missing, check=False)


@pytest.mark.parametrize("depths, succeeds", [((2,), False), ((32,), True)])
def test_shallow_history_is_bounded_and_uses_the_real_merge_base(repo, tmp_path, monkeypatch, depths, succeeds):
    from dry_lint.detector import changed_lines
    from dry_lint.git import git

    original_base = repo.git("rev-parse", "main")
    for i in range(3):
        repo.write("src/new.py", f"value = {i}\n")
        repo.commit()
    repo.git("checkout", "main")
    repo.write("src/base_only.py", "value = 5\n")
    repo.commit()
    clone = tmp_path / "bounded"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", "--branch", "feature", repo.root.as_uri(), str(clone)], check=True
    )
    monkeypatch.setattr(action, "HISTORY_DEPTHS", depths)
    if not succeeds:
        with pytest.raises(ValueError, match="No merge base"):
            ensure_history(clone, "origin/main")
        assert git(clone, "rev-parse", "--is-shallow-repository") == "true"
    else:
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
        monkeypatch.setenv("GIT_CONFIG_KEY_0", "fetch.prune")
        monkeypatch.setenv("GIT_CONFIG_VALUE_0", "false")
        with patch.object(action, "git", wraps=git) as calls:
            ensure_history(clone, "origin/main")
        fetch = next(c for c in calls.call_args_list if "fetch" in c.args)
        config = fetch.kwargs["env"]
        assert config["GIT_CONFIG_COUNT"] == "3" and config["GIT_CONFIG_KEY_0"] == "fetch.prune"
        assert config["GIT_CONFIG_KEY_1"] == "http.https://github.com/.extraheader"
        assert "test-token" not in str(fetch.args)
        assert not git(clone, "config", "--local", "--get", "http.https://github.com/.extraheader", check=False)
        assert git(clone, "merge-base", "origin/main", "HEAD") == original_base
        assert "src/base_only.py" not in changed_lines(clone, "origin/main")


def test_settings_that_turn_judging_off_keep_the_action_quiet_even_with_keys(github_env, tmp_path, capsys) -> None:
    github_env("pull_request", pull_request(), key="secret")
    unjudged = cli_writes_comment(tmp_path, [ANNOTATION], code=0, judge=None)
    with patch.object(action, "dry_lint", side_effect=unjudged) as cli, patch.object(sticky, "main") as post:
        assert action.main(["run"]) == 0
    assert [c.args[0] for c in cli.call_args_list] == ["check"]  # no annotations rendered
    post.assert_not_called()
    assert "listed unjudged" in capsys.readouterr().out
    assert outputs(tmp_path)["findings"] == "0"


def test_an_unreadable_report_counts_as_unjudged(tmp_path: Path) -> None:
    assert action.judged(tmp_path / "missing.json") is False
    (tmp_path / "bad.json").write_text("{")
    assert action.judged(tmp_path / "bad.json") is False


def test_fetch_replaces_inherited_auth_headers_without_persisting_token(repo, monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    headers = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            headers.append(self.headers.get_all("Authorization"))
            self.send_response(403)
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{server.server_port}"
    repo.git("remote", "add", "origin", url + "/repo")
    repo.git("config", f"http.{url}/.extraheader", "Authorization: old-checkout-token")
    monkeypatch.setenv("GITHUB_SERVER_URL", url)
    monkeypatch.setenv("GITHUB_TOKEN", "new-token")
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        with pytest.raises(subprocess.CalledProcessError):
            action.fetch_history(repo.root, "HEAD", depth=2)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert headers == [["basic eC1hY2Nlc3MtdG9rZW46bmV3LXRva2Vu"]]
    assert repo.git("config", "--get", f"http.{url}/.extraheader") == "Authorization: old-checkout-token"


# The repository's ledger: folded on the default branch, shown on every pull request.

MAIN_PUSH = {"ref": "refs/heads/main", "before": BASE, "after": HEAD, "repository": {"default_branch": "main"}}


@pytest.mark.parametrize("event_name, event, expected", [
    ("push", MAIN_PUSH, "main"),
    ("push", {**MAIN_PUSH, "ref": "refs/heads/feature"}, ""),
    ("push", {"ref": "refs/heads/main"}, ""),
    ("pull_request", MAIN_PUSH, ""),
])  # fmt: skip
def test_only_a_push_to_the_default_branch_folds_the_ledger(event_name, event, expected) -> None:
    assert default_branch(event_name, event) == expected


def merged_ledger(*reports) -> str:
    ledger = PullLedger()
    for n, report in enumerate(reports):
        ledger = ledger.advance([report], run=str(n))
    return f"<!-- dry-lint -->\nreport\n{ledger.snapshot()}"


def saved_ledger() -> RepositoryLedger:
    return RepositoryLedger.model_validate_json(action.ledger_path().read_text())


def test_folding_counts_each_pull_request_merged_since_the_ledger_began_once(github_env, tmp_path) -> None:
    github_env("push", MAIN_PUSH)
    action.ledger_path().parent.mkdir(parents=True)
    action.ledger_path().write_text(
        RepositoryLedger(repository="acme/shop", since="2026-11-01T00:00:00+00:00", pulls=[6]).model_dump_json()
    )
    report = tmp_path / "report.json"
    report.write_text(push(HEAD, usd=0.01).model_dump_json())
    github = FakeGitHub(
        merged=[
            {"number": 2, "merged_at": "2026-10-30T00:00:00Z", "merge_commit_sha": "e" * 40},  # before the ledger
            {"number": 3, "merged_at": "2026-10-31T00:00:00Z", "merge_commit_sha": HEAD},  # this push merged it
            {"number": 4, "merged_at": "2026-11-02T00:00:00Z", "merge_commit_sha": "f" * 40},
            {"number": 5, "merged_at": "2026-11-02T00:00:00Z", "merge_commit_sha": "f" * 40},  # never commented
            {"number": 6, "merged_at": "2026-11-02T00:00:00Z", "merge_commit_sha": "f" * 40},  # already counted
            {"number": 8, "merged_at": None},  # closed without merging
        ],
        elsewhere={
            2: [merged_ledger(push("a" * 40, finding("duplicate")), push("b" * 40))],
            3: [merged_ledger(push("a" * 40, finding("duplicate")), push("b" * 40))],
            4: [merged_ledger(push("a" * 40, finding("duplicate"))), "a person's comment"],
            6: [merged_ledger(push("a" * 40, finding("duplicate")), push("b" * 40))],
        },
    )
    assert action.fold("acme/shop", "main", HEAD, report, httpx.MockTransport(github)) == "folded"
    ledger = saved_ledger()
    assert ledger.pulls == [6, 3, 4] and ledger.unaccounted == [5]
    assert (ledger.kept_out, ledger.merged_open, ledger.pushes) == (1, 1, 3)
    assert round(ledger.tally.usd, 3) == 0.016 and ledger.runs == ["55"]

    # The next push looks back over the same pull requests, and changes nothing but its own run.
    assert action.fold("acme/shop", "main", "d" * 40, report, httpx.MockTransport(github)) == "folded"
    assert saved_ledger().model_copy(update={"runs": ["55"]}) == ledger


def test_a_new_ledger_counts_the_pull_request_this_push_merged(github_env, tmp_path) -> None:
    github_env("push", MAIN_PUSH)
    github = FakeGitHub(
        merged=[{"number": 3, "merged_at": "2026-10-31T00:00:00Z", "merge_commit_sha": HEAD}],
        elsewhere={3: [merged_ledger(push("a" * 40, finding("duplicate")), push("b" * 40))]},
    )
    action.fold("acme/shop", "main", HEAD, tmp_path / "no-report.json", httpx.MockTransport(github))
    ledger = saved_ledger()
    assert ledger.pulls == [3] and ledger.kept_out == 1 and ledger.repository == "acme/shop"


def test_folding_without_the_pull_requests_still_counts_this_run(github_env, tmp_path, monkeypatch, capsys) -> None:
    github_env("push", MAIN_PUSH)
    report = tmp_path / "report.json"
    report.write_text(push(HEAD, usd=0.01).model_dump_json())
    github = FakeGitHub(pulls_status=403)
    assert action.fold("acme/shop", "main", HEAD, report, httpx.MockTransport(github)) == "partial"
    assert "Could not read merged pull requests" in capsys.readouterr().out
    monkeypatch.delenv("GITHUB_TOKEN")
    monkeypatch.setenv("GITHUB_RUN_ID", "56")
    assert action.fold("acme/shop", "main", HEAD, report, httpx.MockTransport(github)) == "folded"
    assert saved_ledger().tally.runs == 2 and saved_ledger().pulls == []


def test_a_merged_pull_requests_ledger_reaches_the_next_pull_requests_comment(
    repo: Repo, github_env, tmp_path, twin_judge, monkeypatch
) -> None:
    head = repo.git("rev-parse", "HEAD").strip()
    github = FakeGitHub(head=head)
    github_env(
        "pull_request", pr_event(repo), judge="command", judge_command=twin_judge, working_directory=str(repo.root)
    )
    action.main(["run"], transport=httpx.MockTransport(github))
    [sticky_body] = github.stickies()

    # The pull request merges: the push to main folds its ledger into the repository's.
    merged = FakeGitHub(
        [sticky_body], head=head, merged=[{"number": 7, "merged_at": "2026-11-03T00:00:00Z", "merge_commit_sha": head}]
    )
    github_env(
        "push",
        {**MAIN_PUSH, "before": repo.git("rev-parse", "main").strip(), "after": head},
        judge="command",
        judge_command=twin_judge,
        working_directory=str(repo.root),
    )
    monkeypatch.setenv("GITHUB_RUN_ID", "60")
    action.main(["run"], transport=httpx.MockTransport(merged))
    ledger = saved_ledger()
    assert ledger.pulls == [7] and ledger.merged_open == 1 and ledger.tally.runs == 2

    # The next pull request's comment shows the repository's totals.
    following = FakeGitHub(head=head)
    github_env(
        "pull_request", pr_event(repo), judge="command", judge_command=twin_judge, working_directory=str(repo.root)
    )
    monkeypatch.setenv("GITHUB_RUN_ID", "61")
    action.main(["run"], transport=httpx.MockTransport(following))
    assert "<sub>🏆 `acme/shop` since " in following.stickies()[0]


# The global counter: each merged pull request's counts, once, unless the repository opts out.


def test_merged_pull_requests_are_shared_with_the_counter_under_a_key_the_name_does_not_give(
    github_env, tmp_path, capsys
) -> None:
    github_env("push", MAIN_PUSH)
    github = FakeGitHub(
        merged=[{"number": 3, "merged_at": "2026-10-31T00:00:00Z", "merge_commit_sha": HEAD}],
        elsewhere={3: [merged_ledger(push("a" * 40, finding("duplicate")), push("b" * 40))]},
    )
    action.fold("acme/shop", "main", HEAD, tmp_path / "no-report.json", httpx.MockTransport(github))
    action.fold("acme/shop", "main", "d" * 40, tmp_path / "no-report.json", httpx.MockTransport(github))
    [sent] = github.counted
    assert sent["repository"] == counter_key("4242") and "acme" not in json.dumps(sent)
    assert hashlib.sha256(b"acme/shop").hexdigest() not in json.dumps(sent)  # the name, even hashed, is not sent
    assert f"counter key is {sent['repository']}; its sign is " in capsys.readouterr().out
    assert {k: sent[k] for k in ("pull", "kept_out", "caught", "dismissed", "merged_open", "pushes", "runs")} == {
        "pull": 3,
        "kept_out": 1,
        "caught": 1,
        "dismissed": 0,
        "merged_open": 0,
        "pushes": 2,
        "runs": 2,
    }
    assert sent["usd"] == 0.004 and sent["version"] and saved_ledger().outbox == []


def test_an_unavailable_counter_is_retried_on_the_next_push(github_env, tmp_path, capsys) -> None:
    github_env("push", MAIN_PUSH)
    github = FakeGitHub(
        merged=[{"number": 3, "merged_at": "2026-10-31T00:00:00Z", "merge_commit_sha": HEAD}],
        elsewhere={3: [merged_ledger(push("a" * 40, finding("duplicate")))]},
        counter_status=503,
    )
    assert action.fold("acme/shop", "main", HEAD, tmp_path / "no-report.json", httpx.MockTransport(github)) == "folded"
    assert "global counter is unavailable" in capsys.readouterr().out and len(saved_ledger().outbox) == 1
    github.counter_status = 200
    action.fold("acme/shop", "main", "d" * 40, tmp_path / "no-report.json", httpx.MockTransport(github))
    assert [sent["pull"] for sent in github.counted] == [3] and saved_ledger().outbox == []


def test_without_a_repository_id_nothing_is_shared_but_the_ledger_still_counts(
    github_env, tmp_path, monkeypatch, capsys
) -> None:
    github_env("push", MAIN_PUSH)
    monkeypatch.delenv("GITHUB_REPOSITORY_ID")
    github = FakeGitHub(
        merged=[{"number": 3, "merged_at": "2026-10-31T00:00:00Z", "merge_commit_sha": HEAD}],
        elsewhere={3: [merged_ledger(push("a" * 40, finding("duplicate")))]},
    )
    action.fold("acme/shop", "main", HEAD, tmp_path / "no-report.json", httpx.MockTransport(github))
    assert github.counted == [] and saved_ledger().pulls == [3] and saved_ledger().outbox == []
    assert "counter key" not in capsys.readouterr().out


def test_a_repository_that_opts_out_shares_nothing(github_env, tmp_path) -> None:
    github_env("push", MAIN_PUSH, share_totals="false")
    action.ledger_path().parent.mkdir(parents=True)
    queued = RepositoryLedger(repository="acme/shop", outbox=[{"pull": 1}])
    action.ledger_path().write_text(queued.model_dump_json())
    github = FakeGitHub(
        merged=[{"number": 3, "merged_at": "2026-10-31T00:00:00Z", "merge_commit_sha": HEAD}],
        elsewhere={3: [merged_ledger(push("a" * 40, finding("duplicate")))]},
    )
    action.fold("acme/shop", "main", HEAD, tmp_path / "no-report.json", httpx.MockTransport(github))
    assert github.counted == [] and saved_ledger().outbox == [] and saved_ledger().pulls == [3]


def test_a_baselined_pull_request_that_removes_accepted_debt_is_credited_in_its_sticky(
    repo: Repo, tmp_path: Path, twin_judge: str, github_env
) -> None:
    assert run_cli(repo, tmp_path, "--init", "--judge", "command", "--judge-command", twin_judge, command="sweep") == 0
    repo.commit("adopt")
    repo.git("checkout", "-q", "-B", "main")
    repo.git("checkout", "-q", "-b", "cleanup")
    repo.write("src/widgets/caption.py", "from src.text import shorten_text\n")
    repo.commit()
    github_env(
        "pull_request",
        pr_event(repo),
        working_directory=str(repo.root),
        judge="command",
        judge_command=twin_judge,
        baseline=".dry-lint/baseline.json",
        require_complete="true",
    )
    github = FakeGitHub(head=repo.git("rev-parse", "HEAD").strip())
    assert action.main(["run"], transport=httpx.MockTransport(github)) == 0
    [body] = github.stickies()
    assert "**1 pair**<br><sub>1 from the accepted backlog</sub>" in body
    assert "`shorten_text` ≈ `preview_caption_text` · accepted backlog, cleaned up in push 1: one side removed" in body
    ledger = PullLedger.read(body)
    assert ledger is not None and ledger.count("kept-out") == 0 and len(ledger.backlog) == 1


def test_budget_exhaustion_publishes_an_agent_review_task(repo: Repo, github_env) -> None:
    github_env(
        "pull_request",
        pr_event(repo),
        working_directory=str(repo.root),
        key="test",
        require_complete="true",
        budget_usd="0",
    )
    github = FakeGitHub(head=repo.git("rev-parse", "HEAD").strip())
    assert action.main(["run"], transport=httpx.MockTransport(github)) == 1
    comment = github.stickies()[0]
    assert "review required" in comment and "coding agent" in comment
    assert "distinct-from" in comment and "src/widgets/caption.py" in comment
    assert "Judging is incomplete" not in comment
