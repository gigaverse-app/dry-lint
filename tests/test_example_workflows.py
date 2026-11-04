"""The example workflows adopters copy: valid steps, and a check that a label or a push to main cannot weaken."""

import re
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.mark.parametrize("name", ["dry-lint.yml", "dry-lint-judge.yml"])
def test_every_step_uses_an_action_reference_and_nothing_else(name: str) -> None:
    uses = re.findall(r"^\s*-?\s*uses:\s*(.*)$", (EXAMPLES / name).read_text(), re.MULTILINE)
    assert uses and all(re.fullmatch(r"[\w.-]+/[\w.-]+@[\w.-]+(\s+#.*)?", ref.strip()) for ref in uses), uses


def test_the_pull_request_check_runs_on_every_label_change_and_is_never_skipped() -> None:
    workflow = (EXAMPLES / "dry-lint.yml").read_text()
    assert re.search(r"types: \[[^]]*\blabeled\b[^]]*\bunlabeled\b", workflow)
    # A job skipped by `if` reports success, so it would turn a red required check green.
    assert not re.search(r"^\s+if:", workflow, re.MULTILINE)


def test_only_pull_request_runs_are_cancelled_never_the_runs_on_main() -> None:
    workflow = (EXAMPLES / "dry-lint.yml").read_text()
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in workflow
    assert "github.run_id" in workflow  # a push's group is its own run, so pushes never cancel each other
