"""Execute the self-check's output validation for fork and trusted runs."""

import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

CI = Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"


@pytest.fixture
def output_check() -> dict:
    steps = yaml.safe_load(CI.read_text())["jobs"]["dogfood"]["steps"]
    return next(step for step in steps if step.get("name") == "The action reports its mode and result")


def test_self_check_expects_detection_only_for_fork_pull_requests(output_check: dict) -> None:
    assert " ".join(output_check["env"]["EXPECTED_MODE"].split()) == (
        "${{ github.event_name == 'pull_request' && github.event.pull_request.head.repo.full_name "
        "!= github.event.pull_request.base.repo.full_name && 'detect' || 'single' }}"
    )
    assert output_check["env"]["MODE"] == "${{ steps.dry-lint.outputs.mode }}"
    assert output_check["env"]["CODE"] == "${{ steps.dry-lint.outputs.exit-code }}"


@pytest.mark.parametrize("expected_mode", ["detect", "single"])
@pytest.mark.parametrize("mode", ["detect", "single", "judge", ""])
@pytest.mark.parametrize("code", ["0", "1", "2", ""])
def test_self_check_validates_mode_and_result(output_check: dict, expected_mode: str, mode: str, code: str) -> None:
    result = subprocess.run(
        [shutil.which("bash") or "bash", "-e"],
        input=(
            f"EXPECTED_MODE={shlex.quote(expected_mode)}\nMODE={shlex.quote(mode)}\nCODE={shlex.quote(code)}\n"
            + output_check["run"]
        ).encode(),  # Keep LF line endings when invoking Bash from Windows.
        capture_output=True,
    )
    # A finding (1) is a valid action result; execution errors and missing outputs are not.
    assert (result.returncode == 0) == (mode == expected_mode and code in {"0", "1"}), result.stdout + result.stderr
