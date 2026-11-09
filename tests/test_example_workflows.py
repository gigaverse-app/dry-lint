"""The example workflows adopters copy: valid steps, and a check that a label or a push to main cannot weaken."""

import re
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
# The audit adopters call rather than copy: its steps ship with each release.
AUDIT = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "audit.yml"


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


def test_the_fork_judge_keeps_zizmor_clean_for_adopters_who_run_it() -> None:
    """zizmor flags workflow_run (dangerous-triggers) and a checkout that keeps its token (artipacked)."""
    workflow = (EXAMPLES / "dry-lint-judge.yml").read_text()
    # The trigger is the design, so it is justified where zizmor reads it rather than restructured away.
    assert re.search(r"^  workflow_run:  # zizmor: ignore\[dangerous-triggers\]$", workflow, re.MULTILINE)
    checkouts = re.findall(r"uses: actions/checkout@\S+\n((?:          .*\n|        with:\n)*)", workflow)
    assert checkouts and all("persist-credentials: false" in step for step in checkouts)


def test_the_bootstrap_initializes_from_a_push_and_ships_the_hidden_folder() -> None:
    workflow = (EXAMPLES / "dry-lint-bootstrap.yml").read_text()
    # Runs on the branch that adds it, and again whenever the settings change, e.g. a new pattern.
    assert "paths: [.github/workflows/dry-lint-bootstrap.yml, .dry-lint.toml]" in workflow
    assert '--repository-id "$GITHUB_REPOSITORY_ID"' in workflow  # the README sign, as the local route gives it
    assert "pip install 'dry-lint[anthropic]>=1,<2'" in workflow  # the same major version as @v1 and rev: v1
    assert "dry-lint sweep --init" in workflow and "contents: read" in workflow
    assert "include-hidden-files: true" in workflow  # upload-artifact skips .dry-lint/ otherwise
    assert "persist-credentials: false" in workflow


@pytest.mark.parametrize("path", [EXAMPLES / "dry-lint-bootstrap.yml", AUDIT])
def test_a_repository_without_a_markdown_readme_needs_no_edit(path: Path) -> None:
    """The progress block goes only into README.md; a README.rst repository runs the workflow unchanged."""
    workflow = path.read_text()
    assert "if [[ -f README.md ]]; then readme=(--readme README.md); fi" in workflow
    assert '"${readme[@]}"' in workflow and "--readme README.md --" not in workflow
    assert "cp -R .dry-lint README.md" not in workflow


def test_the_ratchet_commits_only_files_that_exist() -> None:
    """`git add -- a missing` stages nothing, so a listed optional file that is absent would lose the whole ratchet."""
    workflow = AUDIT.read_text()
    assert "add-paths: ${{ steps.ratchet.outputs.paths }}" in workflow
    listed = re.search(r"for path in (.*); do", workflow).group(1).split()
    assert listed == [".dry-lint/baseline.json", ".dry-lint/progress.json", ".dry-lint/models.json", "README.md"]
    assert 'if [[ -f "$path" ]]; then echo "$path"; fi' in workflow


def test_the_audit_example_calls_dry_lints_audit_and_passes_only_what_it_declares() -> None:
    """
    INVARIANT: adopters call the audit at the major tag instead of copying its steps, and every input and secret an
    adopter passes, commented or not, is one the audit declares: an undeclared one fails the caller at run time.
    """
    example, audit = (EXAMPLES / "dry-lint-audit.yml").read_text(), AUDIT.read_text()
    assert re.search(r"^    uses: gigaverse-app/dry-lint/\.github/workflows/audit\.yml@v1$", example, re.MULTILINE)
    assert not re.search(r"^\s*(?:- )?(?:run|steps):", example, re.MULTILINE)  # no steps of its own to drift
    assert re.search(r"^on:\n  workflow_call:\n", audit, re.MULTILINE)  # only ever called
    assert not re.search(r"^  (?:schedule|push|pull_request|workflow_dispatch):", audit, re.MULTILINE)
    # The audit's declarations, six spaces deep under `inputs:` and `secrets:`, before its permissions and steps.
    declared = set(re.findall(r"^      ([A-Za-z_-]+):$", audit.split("\npermissions:")[0], re.MULTILINE))
    # What the example passes under `with:` and `secrets:`, including the commented-out choices.
    call = example.split("    uses: ", 1)[1]
    passed = set(re.findall(r"^\s+#?\s*([A-Za-z_-]+): (?![>|]?$)", call, re.MULTILINE))
    assert {"TYPESAFE_AI_API_KEY", "ANTHROPIC_API_KEY", "DRY_LINT_RATCHET_TOKEN"} <= passed
    assert {"python-version", "budget-usd", "plugins"} <= passed
    assert passed <= declared, passed - declared
