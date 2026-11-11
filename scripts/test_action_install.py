"""Exercise the shipped installer with real uv installs; run separately from the offline test suite."""
# The consumer-install job runs this script, which installs the action and its package by path:
# gv:test-dependency: action.yml
# gv:test-dependency: scripts/install-action.sh
# gv:test-dependency: src/**

import os
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ConsumerInstallTests(unittest.TestCase):
    def test_consumer_settings_do_not_change_the_tool(self) -> None:
        for configuration in ("pyproject.toml", "uv.toml", "package.json"):
            with (
                self.subTest(configuration=configuration),
                tempfile.TemporaryDirectory(prefix="dry-lint-") as directory,
            ):
                root = Path(directory)
                consumer = root / "consumer"
                consumer.mkdir()
                subprocess.run(["git", "init", "--quiet", str(consumer)], check=True)
                config = consumer / configuration
                conflict = 'constraint-dependencies = ["pydantic<2.14"]\n'
                config.write_text(
                    {
                        "pyproject.toml": '[project]\nname = "consumer"\nversion = "0"\n[tool.uv]\n' + conflict,
                        "uv.toml": conflict,
                        "package.json": '{"name":"consumer","private":true}',
                    }[configuration]
                )
                before = config.read_bytes()
                (consumer / ".python-version").write_text("3.9\n")
                marker = consumer / ".venv" / "leave-me-alone"
                marker.parent.mkdir()
                marker.write_text("consumer environment")
                runner = root / "runner"
                runner.mkdir()
                github_path = root / "github-path"
                plugin = root / "sample-plugin"
                (plugin / "sample_plugin").mkdir(parents=True)
                (plugin / "sample_plugin" / "__init__.py").write_text('NAME = "installed"\n')
                (plugin / "pyproject.toml").write_text(
                    '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n'
                    '[project]\nname = "sample-plugin"\nversion = "0.1.0"\n'
                )
                env = dict(
                    os.environ,
                    GITHUB_ACTION_PATH=ROOT.as_posix(),
                    RUNNER_TEMP=runner.as_posix(),
                    GITHUB_PATH=github_path.as_posix(),
                    PLUGINS=f"\r\n{plugin.as_posix()}\r\n  \r\n" if configuration == "uv.toml" else "",
                )
                requested_python = "3.14" if configuration == "package.json" else "3.13"
                if requested_python == "3.14":
                    env["DRY_LINT_PYTHON_VERSION"] = requested_python
                subprocess.run(
                    [shutil.which("bash"), (ROOT / "scripts/install-action.sh").as_posix()],
                    cwd=consumer,
                    env=env,
                    check=True,
                )
                installed_bin = Path(github_path.read_text().strip())
                python = installed_bin / ("python.exe" if os.name == "nt" else "python")
                self.assertTrue(python.is_file(), f"GITHUB_PATH must expose the installed Python: {installed_bin}")
                # Import through the installed interpreter, including the optional package and locked parsers.
                lock = tomllib.loads((ROOT / "uv.lock").read_text())
                versions = {
                    p["name"]: p["version"]
                    for p in lock["package"]
                    if p["name"] in {"pydantic", "tree-sitter", "tree-sitter-typescript"}
                }
                subprocess.run(
                    [
                        str(python),
                        "-c",
                        "import sys, dry_lint; from importlib.metadata import version; "
                        f"assert sys.version_info[:2] == {tuple(map(int, requested_python.split('.')))!r}; "
                        f"assert all(version(k) == v for k, v in {versions!r}.items()); "
                        + (
                            "import sample_plugin; assert sample_plugin.NAME == 'installed'"
                            if configuration == "uv.toml"
                            else ""
                        ),
                    ],
                    check=True,
                    cwd=consumer,
                )
                subprocess.run([str(python), "-m", "dry_lint", "config"], check=True, cwd=consumer, capture_output=True)
                self.assertEqual(config.read_bytes(), before)
                self.assertEqual(marker.read_text(), "consumer environment")
                self.assertFalse((consumer / "uv.lock").exists())


if __name__ == "__main__":
    unittest.main()
