"""The one way dry-lint asks git anything."""

import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def git(root: Path, *args: str, check: bool = True, env: dict[str, str] | None = None) -> str:
    """Stripped stdout of a git command in `root`; with `check=False`, "" when it fails instead of raising."""
    out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=check, env=env)
    return out.stdout.strip() if out.returncode == 0 else ""


@contextmanager
def worktree(root: Path, commit: str) -> Iterator[Path]:
    """Read a detached source snapshot without changing the caller's checkout or index."""
    with tempfile.TemporaryDirectory(prefix="dry-lint-source-") as folder:
        tree = Path(folder) / "tree"
        try:
            git(root, "worktree", "add", "--detach", "--quiet", str(tree), commit)
            yield tree
        finally:
            git(root, "worktree", "remove", "--force", str(tree), check=False)
