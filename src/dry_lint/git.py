"""The one way dry-lint asks git anything."""

import subprocess
from pathlib import Path


def git(root: Path, *args: str, check: bool = True, env: dict[str, str] | None = None) -> str:
    """Stripped stdout of a git command in `root`; with `check=False`, "" when it fails instead of raising."""
    out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=check, env=env)
    return out.stdout.strip() if out.returncode == 0 else ""
