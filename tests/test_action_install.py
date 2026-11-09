"""Exercise uv's real resolver under the configuration that broke AI's action install."""

import shlex
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path


def test_action_install_does_not_apply_consumer_dependency_constraints(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.uv]\nconstraint-dependencies = ["pydantic<2"]\n')
    root = Path(__file__).resolve().parents[1]
    assert 'run: bash "$GITHUB_ACTION_PATH/scripts/install-action.sh"' in (root / "action.yml").read_text()
    action = (root / "scripts/install-action.sh").read_text()
    # Use the shipped install command's global options; only replace its target with an already installed
    # distribution, so the resolver test is offline and cannot modify the test environment.
    install = next(line.strip() for line in action.splitlines() if line.strip().startswith("uv pip install "))
    command = shlex.split(install.partition("--python")[0])
    result = subprocess.run(
        [*command, "--dry-run", "--no-index", "--python", sys.executable, f"pydantic=={version('pydantic')}"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_action_install_includes_the_anthropic_sdk_the_balanced_preset_judges_with(tmp_path: Path) -> None:
    """The recommended preset judges with Claude, so the Action must install the SDK without a `plugins:` input."""
    root = Path(__file__).resolve().parents[1]
    action = (root / "scripts/install-action.sh").read_text()
    # The shipped export command, joined across its continuation line, written to a file here instead.
    lines = iter(action.splitlines())
    export = next(line for line in lines if line.strip().startswith("uv export "))
    while export.rstrip().endswith("\\"):
        export = export.rstrip()[:-1] + " " + next(lines).strip()
    command = [
        arg.replace("$GITHUB_ACTION_PATH", str(root)).replace("$locked", str(tmp_path / "locked.txt"))
        for arg in shlex.split(export)
    ]
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    requirements = (tmp_path / "locked.txt").read_text().splitlines()
    pins = {line.split("==")[0]: line.split(";")[0].strip() for line in requirements if "==" in line}
    assert pins["anthropic"] == f"anthropic=={version('anthropic')}"  # the locked version, as the dev group has it
