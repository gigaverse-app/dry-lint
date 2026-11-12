import json
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from dry_lint import __version__
from dry_lint.bench import GoldFunction, GoldPair
from dry_lint.cli import main, parser, run_info, settings_for
from dry_lint.judges.jev import JevJudge
from dry_lint.models import CandidatesFile

from conftest import EXISTING, Repo, judge_calls
from conftest import TWIN as TWIN_SOURCE
from conftest import run_cli as run

TWIN = "src/widgets/caption.py::preview_caption_text"


def test_check_fails_and_annotates_an_error_for_a_blocking_reimplementation(
    repo: Repo, tmp_path: Path, blocking_twin_judge: str, capsys
) -> None:
    code = run(
        repo,
        tmp_path,
        "--base",
        "main",
        "--judge",
        "command",
        "--judge-command",
        blocking_twin_judge,
        "--format",
        "github",
    )
    assert code == 1
    out = capsys.readouterr().out
    assert out.startswith("::error file=src/widgets/caption.py,line=1,") and "src/text.py::shorten_text" in out


def test_a_reported_duplicate_below_fail_at_warns_without_failing(
    repo: Repo, tmp_path: Path, twin_judge: str, capsys
) -> None:
    code = run(
        repo,
        tmp_path,
        "--base",
        "main",
        "--judge",
        "command",
        "--judge-command",
        twin_judge,
        "--format",
        "github",
        "--fail-at",
        "0.9",
    )
    assert code == 0
    assert capsys.readouterr().out.startswith("::warning file=src/widgets/caption.py,line=1,")
    (repo.root / ".dry-lint.toml").write_text("fail_at = 0.9\n")
    assert run(repo, tmp_path, "--base", "main", "--judge", "command", "--judge-command", twin_judge) == 0
    assert (
        run(repo, tmp_path, "--base", "main", "--judge", "command", "--judge-command", twin_judge, "--fail-at", "0.8")
        == 1
    )


def test_by_default_every_reported_duplicate_fails(repo: Repo, tmp_path: Path, twin_judge: str) -> None:
    assert run(repo, tmp_path, "--base", "main", "--judge", "command", "--judge-command", twin_judge) == 1


def test_verdicts_are_remembered_so_the_judge_is_asked_once(
    repo: Repo, tmp_path: Path, twin_judge: str, capsys
) -> None:
    args = ("--base", "main", "--judge", "command", "--judge-command", twin_judge, "--format", "json")
    run(repo, tmp_path, *args)
    first = judge_calls(tmp_path)
    assert first >= 1
    capsys.readouterr()
    run(repo, tmp_path, *args)
    report = json.loads(capsys.readouterr().out)
    assert judge_calls(tmp_path) == first
    assert all(f["cached"] for f in report["findings"])
    assert any(
        f["reported"] and f["candidate"]["new"]["path"] + "::" + f["candidate"]["new"]["name"] == TWIN
        for f in report["findings"]
    )
    assert len(list((tmp_path / "store").glob("*.json"))) == first


def test_warn_only_reports_without_failing_and_writes_the_comment_and_report(
    repo: Repo, tmp_path: Path, twin_judge: str
) -> None:
    comment, report = tmp_path / "comment.md", tmp_path / "report.json"
    code = run(
        repo,
        tmp_path,
        "--base",
        "main",
        "--judge",
        "command",
        "--judge-command",
        twin_judge,
        "--warn-only",
        "--output",
        str(comment),
        "--report",
        str(report),
    )
    assert code == 0
    assert comment.read_text().startswith("<!-- dry-lint -->") and f"`{TWIN.split('::')[1]}`" in comment.read_text()
    assert "blocking" not in comment.read_text()
    written = json.loads(report.read_text())
    assert written["schema"] == 19 and any(f["reported"] for f in written["findings"])


def test_without_a_judge_candidates_are_listed_and_never_fail(repo: Repo, tmp_path: Path, capsys) -> None:
    assert run(repo, tmp_path, "--base", "main") == 0
    out = capsys.readouterr().out
    assert "preview_caption_text looks like src/text.py::shorten_text (candidate)" in out
    assert not (tmp_path / "store").exists()


def test_staged_check_sees_only_the_staged_change(repo: Repo, tmp_path: Path, capsys) -> None:
    repo.write(
        "src/more.py",
        "def shorten_label(label, size):\n    if len(label) <= size:\n        return label\n"
        "    trimmed = label[: size - 1].rstrip()\n    return trimmed.rstrip('.,;') + '…'\n",
    )
    repo.git("add", "src/more.py")
    assert run(repo, tmp_path, "--staged", "--judge", "none", "--format", "text") == 0
    out = capsys.readouterr().out
    assert "src/more.py:1: shorten_label looks like" in out and "caption.py:1:" not in out


def hook_baseline(repo: Repo) -> list[str]:
    """The hook's arguments as adopters configure it: the settings file's preset, with a committed baseline."""
    from dry_lint.baseline import Baseline, contract

    repo.write(".dry-lint.toml", 'preset = "jev"\n')
    settings = settings_for(repo.root, parser().parse_args(["check", "--root", str(repo.root)]))
    baseline = Baseline(contract=contract(settings), started_at="main", checked_at="main", entries=[])
    repo.write(".dry-lint/baseline.json", baseline.model_dump_json())
    repo.commit("adopt dry-lint")
    return ["--staged", "--preset", "jev", "--baseline", ".dry-lint/baseline.json"]


@pytest.mark.parametrize(
    "stage",
    [
        {},  # `pre-commit run --all-files` in CI: a clean checkout stages nothing
        {"README.md": "docs\n"},  # no supported source file
        {"src/text.py": EXISTING + "\n# a comment, so no function changes\n"},  # source, but no changed function
    ],
    ids=["nothing", "no-source", "no-changed-function"],
)
def test_the_hook_passes_without_a_key_when_the_staged_change_has_nothing_to_judge(repo, tmp_path, capsys, stage):
    args = hook_baseline(repo)
    for path, source in stage.items():
        repo.write(path, source)
        repo.git("add", path)
    assert run(repo, tmp_path, *args) == 0
    captured = capsys.readouterr()
    assert "judging: preset jev · no pair to judge, so no judge ran" in captured.out and not captured.err
    assert not (tmp_path / "store").exists()


def test_the_hook_still_requires_the_key_once_the_staged_change_has_a_pair_to_judge(repo, tmp_path, capsys) -> None:
    args = hook_baseline(repo)
    repo.write("src/more.py", TWIN_SOURCE)
    repo.git("add", "src/more.py")
    assert run(repo, tmp_path, *args) == 2
    assert capsys.readouterr().err.strip() == "dry-lint: The Jev judge needs TYPESAFE_AI_API_KEY"


def test_ci_still_requires_the_key_when_its_change_has_nothing_to_judge(repo, tmp_path, capsys) -> None:
    # A missing or misnamed secret must turn the adoption pull request's check red, though it changes no function.
    args = hook_baseline(repo)
    assert run(repo, tmp_path, *[a for a in args if a != "--staged"], "--base", "HEAD~1") == 2
    assert "needs TYPESAFE_AI_API_KEY" in capsys.readouterr().err


def test_an_idle_hook_run_still_credits_a_pair_the_agent_removed(repo, tmp_path, blocking_twin_judge) -> None:
    from dry_lint.commits import Journal

    repo.write("src/more.py", TWIN_SOURCE)
    repo.git("add", "src/more.py")
    assert run(repo, tmp_path, "--staged", "--judge", "command", "--judge-command", blocking_twin_judge) == 1
    assert Journal.load(repo.root).blocked
    repo.write("src/more.py", "from src.text import shorten_text as preview_caption_text\n")
    repo.git("add", "src/more.py")
    assert run(repo, tmp_path, "--staged", "--preset", "jev") == 0  # no key, and none needed
    journal = Journal.load(repo.root)
    assert not journal.blocked and {pair.state for pair in journal.pending.values()} == {"not-reported"}


def test_staged_judging_reads_index_even_when_working_copy_was_repaired(repo, tmp_path, blocking_twin_judge, capsys):
    repo.write("src/more.py", TWIN_SOURCE)
    repo.git("add", "src/more.py")
    repaired = "from src.text import shorten_text as preview_caption_text\n"
    repo.write("src/more.py", repaired)
    assert run(repo, tmp_path, "--staged", "--judge", "command", "--judge-command", blocking_twin_judge) == 1
    assert "preview_caption_text" in capsys.readouterr().out
    assert (repo.root / "src/more.py").read_text() == repaired
    repo.git("add", "src/more.py")
    assert run(repo, tmp_path, "--staged", "--judge", "command", "--judge-command", blocking_twin_judge) == 0


def test_optional_env_file_loads_only_credentials_and_preserves_exported_values(repo, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "exported-test-value")
    monkeypatch.delenv("TYPESAFE_AI_API_KEY", raising=False)
    repo.write("local.env", 'ANTHROPIC_API_KEY="local-test-value"\nTYPESAFE_AI_API_KEY = "test-value"\nGIT_DIR=wrong\n')
    import os

    before = os.environ.get("GIT_DIR")
    assert main(["config", "--root", str(repo.root), "--env-file", "local.env", "--preset", "none"]) == 0
    assert os.environ["ANTHROPIC_API_KEY"] == "exported-test-value"
    assert os.environ["TYPESAFE_AI_API_KEY"] == "test-value"
    assert os.environ.get("GIT_DIR") == before
    assert main(["config", "--root", str(repo.root), "--env-file", "absent.env", "--preset", "none"]) == 0


def test_staged_workspace_is_rejected_instead_of_reading_unstaged_peers(repo, tmp_path, capsys):
    assert run(repo, tmp_path, "--staged", "--repo", f"owner/primary={repo.root}") == 2
    assert "single repository" in capsys.readouterr().err


def test_staged_typescript_reads_the_index_and_excludes_unstaged_sources(repo, tmp_path, blocking_twin_judge, capsys):
    source = (
        "export function shorten_text(text: string, limit: number): string {\n"
        "  if (text.length <= limit) return text;\n"
        '  return text.slice(0, limit - 1).trimEnd() + "…";\n}\n'
    )
    repo.write("src/text.ts", source)
    repo.commit("feat: add TypeScript helper")
    repo.write("src/caption.ts", source.replace("shorten_text", "preview_caption_text"))
    repo.git("add", "src/caption.ts")
    repo.write("src/caption.ts", 'export { shorten_text as preview_caption_text } from "./text";\n')
    assert run(repo, tmp_path, "--staged", "--judge", "command", "--judge-command", blocking_twin_judge) == 1
    assert "src/caption.ts" in capsys.readouterr().out
    repo.git("reset", "HEAD", "--", "src/caption.ts")
    assert run(repo, tmp_path, "--staged", "--judge", "command", "--judge-command", blocking_twin_judge) == 0


def test_scan_lists_the_repository_backlog(repo: Repo, tmp_path: Path, capsys) -> None:
    assert main(["scan", "--root", str(repo.root), "--judge", "none", "--limit", "5"]) == 0
    captured = capsys.readouterr()
    assert "shorten_text" in captured.out and "preview_caption_text" in captured.out
    assert "raise --limit" not in captured.err  # everything was shown


def test_scan_says_when_its_limit_hides_pairs_and_keeps_json_parseable(repo: Repo, capsys) -> None:
    loader = "def load_{0}(store, key):\n    rows = store.read_rows(key)\n    return [row.decode() for row in rows]\n"
    repo.write("src/users.py", loader.format("users"))
    repo.write("src/accounts.py", loader.format("accounts"))
    repo.commit()
    assert main(["scan", "--root", str(repo.root), "--judge", "none", "--limit", "1", "--format", "json"]) == 0
    captured = capsys.readouterr()
    assert len(json.loads(captured.out)["findings"]) == 1
    assert re.search(r"showing the 1 closest of [2-9]\d* look-alike pairs; raise --limit", captured.err)


def test_scan_refresh_re_judges_answers_from_an_older_judge_version(
    repo: Repo, tmp_path: Path, twin_judge: str
) -> None:
    for version in ("v1", "v1", "v2"):
        (repo.root / ".dry-lint.toml").write_text(
            f'judge = {{ use = "command", command = {json.dumps(twin_judge)}, version = "{version}" }}\n'
        )
        main(
            [
                "scan",
                "--root",
                str(repo.root),
                "--store",
                str(tmp_path / "store"),
                "--limit",
                "1",
                "--refresh",
                "--warn-only",
            ]
        )
    assert judge_calls(tmp_path) == 2


def test_the_two_ci_jobs_hand_over_through_candidates_json(
    repo: Repo, tmp_path: Path, blocking_twin_judge: str, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    event = tmp_path / "event.json"
    head = repo.git("rev-parse", "HEAD").strip()
    event.write_text(json.dumps({"pull_request": {"number": 42, "head": {"sha": head}}}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_REPOSITORY", "octo/repo")
    candidates = tmp_path / "candidates.json"
    assert run(repo, tmp_path, "--base", "main", "--out", str(candidates), command="detect") == 0
    assert "candidate pair(s) to judge" in capsys.readouterr().out
    handed = CandidatesFile.model_validate_json(candidates.read_text())
    assert (handed.run.repository, handed.run.pull_request, handed.run.head, handed.run.base) == (
        "octo/repo",
        42,
        head,
        "main",
    )
    assert handed.changed == 2 and all(c.new.hash and c.existing.hash for c in handed.candidates)
    assert not (tmp_path / "store").exists()  # detect never touches the store

    report = tmp_path / "report.json"
    code = run(
        repo,
        tmp_path,
        "--candidates",
        str(candidates),
        "--judge",
        "command",
        "--judge-command",
        blocking_twin_judge,
        "--report",
        str(report),
        "--warn-only",
        command="judge",
    )
    assert code == 0 and judge_calls(tmp_path) >= 1
    capsys.readouterr()
    assert main(["report", "--root", str(repo.root), "--from", str(report), "--format", "check-run"]) == 1
    body = json.loads(capsys.readouterr().out)
    assert (body["head_sha"], body["conclusion"]) == (head, "failure")
    assert json.loads(report.read_text())["findings"][0]["blocking"] is True
    main(["report", "--root", str(repo.root), "--from", str(report), "--format", "check-run", "--warn-only"])
    assert json.loads(capsys.readouterr().out)["conclusion"] == "neutral"
    assert json.loads(report.read_text())["run"]["pull_request"] == 42


@pytest.mark.parametrize("command", ["check", "detect"])
def test_pr_snapshot_preserves_dirty_checkout_and_primary_repo_identity(
    repo: Repo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str, twin_judge: str
) -> None:
    peer = Repo(tmp_path / "peer")
    peer.write("src/shared.py", EXISTING)
    peer.commit()
    repo.write(".dry-lint.toml", 'store = {use = "dir", path = ".verdicts"}\n')
    repo.commit()
    head = repo.git("rev-parse", "HEAD").strip()
    base = repo.git("rev-parse", "main").strip()
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"head": {"sha": head}}}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    repo.git("checkout", "main")
    repo.write("README.md", "main advanced\n")
    repo.commit()
    repo.git("merge", "--no-ff", "feature", "-m", "synthetic merge")
    repo.write("src/widgets/caption.py", "# staged deletion of the two feature functions\n")
    repo.git("add", "src/widgets/caption.py")
    repo.write("src/widgets/caption.py", "# additional unstaged change\n")
    before = [repo.git(*args) for args in (("diff",), ("diff", "--cached"), ("worktree", "list", "--porcelain"))]
    report = tmp_path / "snapshot.json"
    assert (
        main(
            [
                command,
                "--root",
                str(repo.root),
                "--base",
                base,
                "--judge",
                "command",
                "--judge-command",
                twin_judge,
                "--warn-only",
                "--repo",
                f"owner/primary={repo.root}",
                "--repo",
                f"owner/peer={peer.root}",
                "--report" if command == "check" else "--out",
                str(report),
            ]
        )
        == 0
    )
    assert json.loads(report.read_text())["changed"] == 2
    if command == "check":
        assert list((repo.root / ".verdicts").rglob("*.json"))
    assert [
        repo.git(*args) for args in (("diff",), ("diff", "--cached"), ("worktree", "list", "--porcelain"))
    ] == before


def test_detect_prints_candidates_without_out_and_proposes_the_backlog_with_all(
    repo: Repo, tmp_path: Path, capsys
) -> None:
    assert run(repo, tmp_path, "--base", "main", command="detect") == 0
    assert CandidatesFile.model_validate_json(capsys.readouterr().out).changed == 2
    assert run(repo, tmp_path, "--all", command="detect") == 0
    everything = CandidatesFile.model_validate_json(capsys.readouterr().out)
    assert everything.changed > 30 and any(
        c.existing.name == "shorten_text" or c.new.name == "shorten_text" for c in everything.candidates
    )


def test_explain_shows_the_similarity_the_rule_and_the_stored_verdict(
    repo: Repo, tmp_path: Path, twin_judge: str, capsys
) -> None:
    assert run(repo, tmp_path, "caption.py::preview_caption_text", "text.py::shorten_text", command="explain") == 0
    out = capsys.readouterr().out
    assert out.startswith(f"{TWIN} ~ src/text.py::shorten_text\n  similarity ")
    assert "(tfidf:2)" in out and "shared: " in out and "proposed: #1 of" in out
    assert "rule: none applies" in out and "stored verdict: none" in out
    run(repo, tmp_path, "--base", "main", "--judge", "command", "--judge-command", twin_judge, "--warn-only")
    capsys.readouterr()
    run(repo, tmp_path, "caption.py::preview_caption_text", "text.py::shorten_text", command="explain")
    out = capsys.readouterr().out
    assert (
        "stored verdict: duplicate 0.85 by command:" in out and "reused: yes, neither function's logic changed" in out
    )
    run(repo, tmp_path, "caption.py::register_widget", "filler.py::sync_invoice", command="explain")
    assert "proposed: not among" in capsys.readouterr().out


def test_bench_measures_the_judge_or_the_comparer(repo: Repo, tmp_path: Path, twin_judge: str, capsys) -> None:
    gold = tmp_path / "gold.jsonl"
    twin = GoldPair(
        new=GoldFunction(id=TWIN, code=TWIN_SOURCE),
        existing=GoldFunction(id="src/text.py::shorten_text", code=EXISTING),
        label="duplicate",
    )
    gold.write_text(twin.model_dump_json() + "\n")
    assert (
        run(repo, tmp_path, "--gold", str(gold), "--judge", "command", "--judge-command", twin_judge, command="bench")
        == 0
    )
    assert "1 labelled pairs, 1 duplicates" in capsys.readouterr().out
    assert run(repo, tmp_path, "--gold", str(gold), "--comparer", command="bench") == 0
    assert "partner among the top 3 proposed: 100%" in capsys.readouterr().out
    assert run(repo, tmp_path, "--gold", str(gold), "--comparer", "--format", "json", command="bench") == 0
    assert json.loads(capsys.readouterr().out)["recall"] == 1.0
    assert (
        run(
            repo,
            tmp_path,
            "--gold",
            str(gold),
            "--judge",
            "command",
            "--judge-command",
            twin_judge,
            "--format",
            "json",
            command="bench",
        )
        == 0
    )
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
    assert (
        info.head == repo.git("rev-parse", "HEAD").strip() and info.pull_request is None and info.base == "origin/main"
    )


@pytest.mark.parametrize(
    "repository,pull,ref,session",
    [
        ("acme/shop", {}, "refs/heads/main", "refs/heads/main"),
        ("acme/shop", {}, "refs/tags/main", "refs/tags/main"),
        ("acme/shop", {"number": 7}, "refs/pull/7/merge", ""),
        ("", {}, "refs/heads/main", ""),
    ],
)
def test_action_session_identity_preserves_pr_and_local_ownership(
    repo: Repo, tmp_path: Path, monkeypatch, repository, pull, ref, session
) -> None:
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": pull}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_REPOSITORY", repository)
    monkeypatch.setenv("GITHUB_REF", ref)
    info = run_info(repo.root, None)
    assert info.session == session
    assert info.pull_request == pull.get("number")
    assert info.head == repo.git("rev-parse", "HEAD").strip()


def test_errors_exit_2_with_a_message(tmp_path: Path, capsys) -> None:
    assert main(["check", "--root", str(tmp_path), "--judge", "none"]) == 2
    assert capsys.readouterr().err.startswith("dry-lint: ")


def test_bad_judge_settings_exit_2(repo: Repo, tmp_path: Path, capsys) -> None:
    assert run(repo, tmp_path, "--base", "main", "--judge", "command") == 2
    assert "--judge-command" in capsys.readouterr().err


def test_the_module_runs_as_a_command(repo: Repo) -> None:
    out = subprocess.run([sys.executable, "-m", "dry_lint", "--version"], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == f"dry-lint {__version__}"


def test_judge_failures_exit_2_without_a_traceback(repo: Repo, tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("TYPESAFE_AI_API_KEY", "key")
    with patch.object(JevJudge, "judge", side_effect=httpx.ConnectError("api unreachable")):
        assert run(repo, tmp_path, "--base", "main", "--judge", "jev") == 2
    assert capsys.readouterr().err.startswith("dry-lint: ")
    with patch.object(JevJudge, "judge", side_effect=subprocess.TimeoutExpired("judge", 180)):
        assert run(repo, tmp_path, "--base", "main", "--judge", "jev") == 2
    assert "timed out" in capsys.readouterr().err


def test_config_shows_the_resolved_preset_its_numbers_and_what_unlocks_the_others(
    repo: Repo, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("TYPESAFE_AI_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert main(["config", "--root", str(repo.root)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("preset: balanced - Recommended function review")
    assert "credentials found: TYPESAFE_AI_API_KEY, ANTHROPIC_API_KEY" in out and "756 labelled pairs" in out
    assert "escalate: none" in out
    assert "thresholds: drop below 0.4 - report at 0.4 - fail at 0.5" in out
    assert "budget: $0.04 per pull request at list price" in out
    assert "  * balanced" in out and "jev+claude-code" in out and "[needs CLAUDE_CODE_OAUTH_TOKEN]" in out
    assert "jev+claude-code-sonnet" in out and "[named only]" in out


def test_config_shows_explicit_settings_subscriptions_and_unknown_prices(repo: Repo, capsys) -> None:
    (repo.root / ".dry-lint.toml").write_text(
        'fail_at = 0.75\njudge = { use = "command", command = "my-llm" }\nescalate = { use = "codex" }\n'
    )
    assert main(["config", "--root", str(repo.root)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("preset: custom - your own judge") and "credentials found: none" in out
    assert (
        "judge: command {'command': 'my-llm'} (unknown price)" in out and "codex  on [0.6, 0.91) (subscription)" in out
    )
    assert "(set explicitly: escalate, fail_at, judge)" in out
    assert main(["config", "--root", str(repo.root), "--preset", "none", "--judge", "none"]) == 0
    assert "judge: none (-)" in capsys.readouterr().out
    (repo.root / ".dry-lint.toml").unlink()
    assert main(["config", "--root", str(repo.root), "--judge", "none"]) == 0
    assert capsys.readouterr().out.startswith("preset: none - no judge")


def test_config_shows_which_source_files_the_scope_covers(repo: Repo, capsys) -> None:
    for folder in "abcdefghi":
        repo.write(f"{folder}/module.py", "def f():\n    return 1\n")
    repo.write("README.md", "# not source\n")
    repo.write("top.py", "def g():\n    return 2\n")
    repo.commit()
    assert main(["config", "--root", str(repo.root)]) == 0
    out = capsys.readouterr().out
    assert "scope: include * - exclude */tests/*, tests/*, */migrations/*, */scripts/*" in out
    assert "  13 source files in scope: src 3, . 1, a 1, b 1, c 1, d 1, e 1, f 1, ..." in out
    assert "  0 declared pattern(s)" in out
    (repo.root / ".dry-lint.toml").write_text('include = ["nowhere/*"]\nexclude = []\n')
    assert main(["config", "--root", str(repo.root)]) == 0
    out = capsys.readouterr().out
    assert "scope: include nowhere/* - exclude nothing\n  0 source files in scope\n" in out


def test_preset_and_budget_flags_shape_the_run(repo: Repo, tmp_path: Path, twin_judge: str, capsys) -> None:
    assert (
        run(
            repo,
            tmp_path,
            "--base",
            "main",
            "--judge",
            "command",
            "--judge-command",
            twin_judge,
            "--budget-usd",
            "0",
            "--format",
            "json",
        )
        == 1
    )
    report = json.loads(capsys.readouterr().out)
    assert report["judging"]["preset"] == "custom" and report["judging"]["budget_usd"] == 0
    assert report["judging"]["spend"][0]["usd"] is None  # an unpriced command judge is not budgeted, and not $0
    assert main(["config", "--root", str(repo.root), "--preset", "jev"]) == 0
    assert capsys.readouterr().out.startswith("preset: jev - Jev on every pair")


@pytest.mark.parametrize("with_baseline", [False, True])
def test_exhausted_judging_routes_to_agent_feedback_without_more_paid_calls(
    repo, tmp_path, monkeypatch, capsys, with_baseline
) -> None:
    repo.write(".dry-lint.toml", "[budget]\nusd = 0\n")
    monkeypatch.setenv("TYPESAFE_AI_API_KEY", "test")
    report_path = tmp_path / "report.json"
    args = ["--base", "main", "--judge", "jev", "--require-complete", "--report", str(report_path)]
    if with_baseline:
        from dry_lint.baseline import Baseline, contract

        settings = settings_for(repo.root, parser().parse_args(["check", *args]))
        baseline = Baseline(contract=contract(settings), started_at="main", checked_at="main", entries=[])
        repo.write(".dry-lint/baseline.json", baseline.model_dump_json())
        args.extend(["--baseline", ".dry-lint/baseline.json"])
    assert run(repo, tmp_path, *args) == 0
    assert "coding agent" in capsys.readouterr().out
    from dry_lint.report import Report

    report_data = Report.model_validate_json(report_path.read_text())
    for finding in report_data.findings:
        assert (
            run(
                repo,
                tmp_path,
                "dismiss",
                finding.candidate.key,
                "--from",
                str(report_path),
                "--reason",
                "Independent contracts verified against their callers",
                "--reviewer",
                "coding-agent",
                command="feedback",
            )
            == 0
        )
    assert run(repo, tmp_path, *args) == 0
    assert all(spend.calls == 0 for spend in report_data.judging.spend)


def test_scan_reports_pattern_settled_pairs_as_skipped_by_rule(repo: Repo, capsys) -> None:
    (repo.root / ".dry-lint.toml").write_text(
        '[[patterns]]\nmembers = ["*text.py::*", "*caption.py::*"]\nreason = "kept on purpose"\n'
    )
    assert main(["scan", "--root", str(repo.root), "--judge", "none", "--limit", "5"]) == 0
    out = capsys.readouterr().out
    assert "preview_caption_text looks like" not in out and "1 skipped by rule" in out
