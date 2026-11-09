"""The environment a composite action step sees, shared by the action's tests.

A plain module, not a test module: tests import `github_env` and `outputs` from here instead of
loading another test module as a plugin, which made every test depend on that module's imports.
"""

import json
from pathlib import Path

import pytest

from conftest import clear_judge_credentials


@pytest.fixture
def github_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The environment a composite action step sees, with its output files in tmp_path."""

    def set_event(name: str, payload: dict, **inputs: str) -> Path:
        event = tmp_path / "event.json"
        event.write_text(json.dumps(payload))
        values = {
            "GITHUB_EVENT_NAME": name,
            "GITHUB_EVENT_PATH": str(event),
            "GITHUB_REPOSITORY": "acme/shop",
            "GITHUB_REPOSITORY_ID": "4242",
            "GITHUB_RUN_ID": "55",
            "GITHUB_OUTPUT": str(tmp_path / "output"),
            "GITHUB_TOKEN": "token",
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
            "RUNNER_TEMP": str(tmp_path / "runner"),
            "INPUT_COMMENT": "true",
            "INPUT_CHECK_RUN": "true",
            "INPUT_WORKING_DIRECTORY": str(tmp_path),
        }
        values.update({f"INPUT_{k.upper()}": v for k, v in inputs.items() if k != "key"})
        # Hermetic: a developer's or Claude Code's own keys must never reach a judge from a test.
        clear_judge_credentials(monkeypatch)
        monkeypatch.delenv("GITHUB_RUN_ATTEMPT", raising=False)  # set when the tests themselves run in Actions
        if "key" in inputs:
            values["TYPESAFE_AI_API_KEY"] = inputs["key"]
        for name_, value in values.items():
            monkeypatch.setenv(name_, value)
        return tmp_path

    return set_event


def outputs(tmp_path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in (tmp_path / "output").read_text().splitlines())
