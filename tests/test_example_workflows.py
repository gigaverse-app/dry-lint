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


def test_a_fork_run_never_reports_as_the_required_check() -> None:
    """A fork's job only detects, so it must not be named `dry-lint`, the check a branch rule requires."""
    workflow = (EXAMPLES / "dry-lint.yml").read_text()
    name = " ".join(re.search(r"^    name: >-\n((?:      .*\n)+)", workflow, re.MULTILINE).group(1).split())
    assert name == (
        "${{ github.event_name == 'pull_request' && github.event.pull_request.head.repo.full_name "
        "!= github.event.pull_request.base.repo.full_name && 'dry-lint detect' || 'dry-lint' }}"
    )


def test_the_bootstrap_initializes_from_a_push_and_ships_the_hidden_folder() -> None:
    workflow = (EXAMPLES / "dry-lint-bootstrap.yml").read_text()
    # Runs on the branch that adds it, and again whenever the settings change, e.g. a new pattern.
    assert "paths: [.github/workflows/dry-lint-bootstrap.yml, .dry-lint.toml]" in workflow
    assert '--repository-id "$GITHUB_REPOSITORY_ID"' in workflow  # the README sign, as the local route gives it
    assert "pip install 'dry-lint>=1,<2'" in workflow  # the same major version as @v1 and rev: v1
    assert "dry-lint sweep --init" in workflow and "contents: read" in workflow
    assert "include-hidden-files: true" in workflow  # upload-artifact skips .dry-lint/ otherwise
    assert "persist-credentials: false" in workflow
