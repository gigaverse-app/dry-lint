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
