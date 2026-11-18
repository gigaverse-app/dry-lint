import subprocess
from pathlib import Path

from dry_lint.git import git

# U+0441 encodes as d1 81; 0x81 has no cp1252 character, so a locale-decoded read lost the whole output.
SOURCE = "NAME = 'с' # ✓ é\n"


def test_git_output_is_utf8_whatever_the_locale(tmp_path: Path) -> None:
    for args in (["init", "-q"], ["config", "user.email", "t@example.test"], ["config", "user.name", "T"]):
        subprocess.run(["git", *args], cwd=tmp_path, check=True)
    (tmp_path / "module.py").write_bytes(SOURCE.encode())
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "unicode"], cwd=tmp_path, check=True)
    assert git(tmp_path, "show", "HEAD:module.py") == SOURCE.strip()
