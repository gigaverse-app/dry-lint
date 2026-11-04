"""The pre-commit hook adopters install by id: it checks staged code for the coding agent, and works with no extra setup."""

import re
import shlex
import tomllib
from pathlib import Path

from dry_lint.cli import parser

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = (ROOT / ".pre-commit-hooks.yaml").read_text()


def field(name: str) -> str:
    return re.search(rf"^\s+{name}: (.*?)(\s+#.*)?$", MANIFEST, re.MULTILINE).group(1)


def test_the_hook_checks_staged_code_with_the_agent_preset_and_the_local_env_file() -> None:
    args = parser().parse_args(shlex.split(field("entry"))[1:])
    assert (args.command, args.staged, args.preset, str(args.env_file)) == ("check", True, "agent", ".env")


def test_a_repository_s_args_override_the_hook_s_preset() -> None:
    # pre-commit appends `args` to the entry, so the last --preset wins.
    args = parser().parse_args([*shlex.split(field("entry"))[1:], "--preset", "agent+haiku"])
    assert args.preset == "agent+haiku"


def test_the_hook_installs_what_its_judges_and_env_file_need() -> None:
    hooks = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["optional-dependencies"]["hooks"]
    assert sorted(re.findall(r'"([^"]+)"', field("additional_dependencies"))) == sorted(hooks)
