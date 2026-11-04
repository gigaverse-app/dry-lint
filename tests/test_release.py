"""Releases: release-please bumps every place the version is written, so they always agree."""

import json
import tomllib
from pathlib import Path

from dry_lint import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_every_written_version_is_the_released_one() -> None:
    released = json.loads((ROOT / ".release-please-manifest.json").read_text())["."]
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    locked = next(p["version"] for p in tomllib.loads((ROOT / "uv.lock").read_text())["package"] if p["name"] == "dry-lint")
    assert __version__ == project == locked == released


def test_release_please_bumps_each_file_that_writes_the_version() -> None:
    package = json.loads((ROOT / "release-please-config.json").read_text())["packages"]["."]
    bumped = {entry if isinstance(entry, str) else entry["path"] for entry in package["extra-files"]}
    assert package["release-type"] == "python"  # bumps pyproject.toml itself
    assert bumped == {"src/dry_lint/__init__.py", "uv.lock"}
    assert "x-release-please-version" in (ROOT / "src/dry_lint/__init__.py").read_text()
