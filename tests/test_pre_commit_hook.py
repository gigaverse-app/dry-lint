"""The pre-commit hook adopters install by id: it checks staged code for the coding agent, and works with no extra setup."""

import re
import shlex
import tomllib
from pathlib import Path

from dry_lint.cli import parser

ROOT = Path(__file__).resolve().parents[1]
HOOKS = {block.split("\n", 1)[0]: block for block in (ROOT / ".pre-commit-hooks.yaml").read_text().split("- id: ")[1:]}


def field(name: str, hook: str = "dry-lint") -> str:
    return re.search(rf"^\s+{name}: (.*?)(\s+#.*)?$", HOOKS[hook], re.MULTILINE).group(1)


def test_the_hook_checks_staged_code_with_the_agent_preset_and_the_local_env_file() -> None:
    args = parser().parse_args(shlex.split(field("entry"))[1:])
    assert (args.command, args.staged, args.preset, str(args.env_file)) == ("check", True, "agent", ".env")


def test_a_repository_s_args_override_the_hook_s_preset() -> None:
    # pre-commit appends `args` to the entry, so the last --preset wins.
    args = parser().parse_args([*shlex.split(field("entry"))[1:], "--preset", "agent+haiku"])
    assert args.preset == "agent+haiku"


def test_both_hooks_install_what_the_judges_and_env_file_need_into_one_shared_environment() -> None:
    hooks = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["optional-dependencies"]["hooks"]
    for hook in HOOKS:
        assert sorted(re.findall(r'"([^"]+)"', field("additional_dependencies", hook))) == sorted(hooks)


def test_the_trailers_hook_gets_the_commit_message_file_at_the_prepare_commit_msg_stage() -> None:
    assert set(HOOKS) == {"dry-lint", "dry-lint-trailers"}
    assert (field("stages", "dry-lint-trailers"), field("always_run", "dry-lint-trailers")) == (
        "[prepare-commit-msg]",
        "true",
    )
    assert "pass_filenames" not in HOOKS["dry-lint-trailers"]  # pre-commit passes the message file
    args = parser().parse_args([*shlex.split(field("entry", "dry-lint-trailers"))[1:], ".git/COMMIT_EDITMSG"])
    assert (args.command, args.message.as_posix()) == ("trailers", ".git/COMMIT_EDITMSG")
