import json
import sys
from pathlib import Path

import httpx
import pytest

from dry_lint.judges import label_for, make_judge
from dry_lint.judges.command import CommandJudge
from dry_lint.judges.jev import API_URL, QUESTIONS, JevJudge, state
from dry_lint.models import Candidate
from dry_lint.settings import PluginChoice, Settings

from conftest import function

CANDIDATE = Candidate(
    new=function("src/widgets/caption.py", "def clip(text, n):\n    return text[:n]\n"),
    existing=function("src/text.py", "def shorten(text, limit):\n    return text[:limit]\n"),
    similarity=0.8,
)


@pytest.mark.parametrize("score, differs, label", [
    (0.59, 0.0, "separate"), (0.6, 0.0, "duplicate"), (0.95, 0.79, "duplicate"), (0.95, 0.8, "drifted"), (0.3, 0.99, "separate"),
])  # fmt: skip
def test_label_for_applies_the_drop_and_drift_thresholds(score, differs, label) -> None:
    assert label_for(score, differs, Settings()) == label


def test_auto_judge_is_jev_with_a_key_and_none_without(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TYPESAFE_AI_API_KEY", raising=False)
    assert make_judge(PluginChoice(use="auto")) is None
    assert make_judge(PluginChoice(use="none")) is None
    monkeypatch.setenv("TYPESAFE_AI_API_KEY", "key")
    assert isinstance(make_judge(PluginChoice(use="auto", workers=2)), JevJudge)
    assert make_judge(PluginChoice(use="auto", workers=2)).workers == 2


def test_make_judge_builds_a_command_judge_from_its_options_and_rejects_bad_choices() -> None:
    judge = make_judge(PluginChoice(use="command", command="/usr/bin/my-llm --json", version="v3"))
    assert (judge.name, judge.version) == ("command:my-llm", "v3")
    assert make_judge(PluginChoice(use="command", command="llm", name="house-llm")).name == "house-llm"
    with pytest.raises(ValueError, match="--judge-command"):
        make_judge(PluginChoice(use="command"))
    with pytest.raises(ValueError, match="Unknown judge 'oracle'; available: command, jev"):
        make_judge(PluginChoice(use="oracle"))


def test_jev_needs_an_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TYPESAFE_AI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="TYPESAFE_AI_API_KEY"):
        JevJudge()


def test_jev_state_is_the_two_functions_by_name_module_and_code() -> None:
    assert state(CANDIDATE) == {
        "new_function": {"name": "clip", "module": "src.widgets.caption", "code": CANDIDATE.new.code},
        "existing_function": {"name": "shorten", "module": "src.text", "code": CANDIDATE.existing.code},
    }


@pytest.mark.parametrize("same, differs, p_none, label, score", [
    (0.9, 0.1, 0.0, "duplicate", 0.9),
    (0.9, 0.85, 0.1, "drifted", 0.81),
    (0.9, 0.1, 0.5, "separate", 0.45),
])  # fmt: skip
def test_jev_scores_one_concept_discounted_by_the_chance_they_should_stay_separate(same, differs, p_none, label, score):
    requests = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"answers": {
            "same_concept": {"noul": same}, "behaves_differently": {"noul": differs},
            "owner": {"choice": "existing", "probabilities": {"existing": 1 - p_none, "none": p_none}},
        }})

    judge = JevJudge(api_key="secret", transport=httpx.MockTransport(answer))
    [verdict] = judge.judge([CANDIDATE], Settings())
    assert (verdict.label, verdict.score, verdict.owner) == (label, score, "existing")
    assert (verdict.judge, verdict.judge_version) == ("jev", "reuse-v2")
    body = json.loads(requests[0].content)
    assert str(requests[0].url) == API_URL and requests[0].headers["Authorization"] == "Bearer secret"
    assert body == {"model": "jev-latest", "state": state(CANDIDATE), "questions": QUESTIONS}


def test_jev_errors_surface_instead_of_becoming_verdicts() -> None:
    judge = JevJudge(api_key="secret", transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    with pytest.raises(httpx.HTTPStatusError):
        judge.judge([CANDIDATE], Settings())


def script(tmp_path: Path, body: str) -> str:
    path = tmp_path / "judge.py"
    path.write_text(body)
    return f'"{sys.executable}" "{path}"'


def test_command_judge_sends_both_functions_and_reads_the_json_verdict(tmp_path: Path) -> None:
    command = script(tmp_path, (
        "import json, sys\nprompt = sys.stdin.read()\n"
        "ok = 'src/text.py::shorten' in prompt and 'return text[:n]' in prompt\n"
        "print('thinking...', json.dumps({'label': 'duplicate', 'score': 0.93 if ok else 0, 'owner': 'existing', "
        "'why': 'same truncation'}), 'done')\n"
    ))
    [verdict] = CommandJudge(command).judge([CANDIDATE], Settings())
    assert (verdict.label, verdict.score, verdict.owner, verdict.why) == ("duplicate", 0.93, "existing", "same truncation")
    assert (verdict.judge, verdict.judge_version, verdict.behaves_differently) == (f"command:{Path(sys.executable).name}", "1", 0.0)


def test_command_judge_can_take_the_candidate_as_json(tmp_path: Path) -> None:
    command = script(tmp_path, (
        "import json, sys\npair = json.loads(sys.stdin.readline())\n"
        "print(json.dumps({'label': 'drifted', 'score': pair['similarity'], 'behaves_differently': 0.9, "
        "'why': pair['existing']['name']}))\n"
    ))
    [verdict] = CommandJudge(command, input="candidate").judge([CANDIDATE], Settings())
    assert (verdict.label, verdict.score, verdict.behaves_differently, verdict.why) == ("drifted", 0.8, 0.9, "shorten")
    assert CommandJudge("x", input="candidate").stdin(CANDIDATE) == CANDIDATE.model_dump_json() + "\n"


def test_command_judge_rejects_output_without_a_verdict(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no JSON verdict"):
        CommandJudge(script(tmp_path, "print('no idea')\n")).judge([CANDIDATE], Settings())


def test_command_judge_prompt_names_both_sides() -> None:
    prompt = CommandJudge("llm").stdin(CANDIDATE)
    assert "# NEW: src/widgets/caption.py::clip" in prompt and "# EXISTING: src/text.py::shorten" in prompt
    assert "<<" not in prompt
