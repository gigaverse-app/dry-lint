"""Global, committed metadata locations, resolved against one filesystem or Git snapshot."""

from collections.abc import Mapping
from pathlib import Path

from dry_lint.git import git

CONFIG_FILES = (".dry-lint/config.toml", ".dry-lint.toml")
FEEDBACK_FILES = (".dry-lint/feedback.json", ".dry-lint-feedback.json")
IGNORE_FILE = ".dry-lint/ignore.yaml"
UNSUPPORTED_IGNORE_FILES = (
    ".dry-lint-ignore.toml",
    ".dry-lint-ignore.yaml",
    ".dry-lint-ignore.yml",
    ".dry-lint/ignore.toml",
    ".dry-lint/ignore.yml",
)
SETTINGS_FILES = (*CONFIG_FILES, "pyproject.toml", IGNORE_FILE, *UNSUPPORTED_IGNORE_FILES)


def location(sources: Mapping[str, object], names: tuple[str, ...]) -> str:
    """One canonical location or its legacy name; a move must not leave two authorities."""
    found = [name for name in names if name in sources]
    if len(found) > 1:
        raise ValueError(
            f"Found multiple versions of the same dry-lint file: {', '.join(found)}. Keep only {names[0]}."
        )
    return found[0] if found else names[0]


def read_files(
    root: Path, names: tuple[str, ...], *, staged: bool = False, revision: str | None = None
) -> dict[str, bytes]:
    """Read only root metadata. Staged/committed reads never fall back to working-tree files."""
    if not staged and revision is None:
        return {name: (root / name).read_bytes() for name in names if (root / name).exists()}
    tracked = set(
        git(root, "ls-files", "--cached", "-z", "--", *names).split("\0")
        if staged
        else git(root, "ls-tree", "-r", "--name-only", "-z", revision, "--", *names).split("\0")
    )
    return {
        name: git(root, "show", f"{'' if staged else revision}:{name}").encode("utf-8")
        for name in names
        if name in tracked
    }
