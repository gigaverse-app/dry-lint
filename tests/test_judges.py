import json
import shlex
import sys
from pathlib import Path

import anthropic
import httpx
import httpx2
import pytest

from dry_lint.judges import label_for, make_escalation, make_judge
from dry_lint.judges.anthropic import AnthropicJudge
from dry_lint.judges.command import PROMPT_VERSION, CommandJudge, parse_verdict
from dry_lint.judges.gemini import API_URL as GEMINI_URL
from dry_lint.judges.gemini import GeminiJudge
from dry_lint.judges.http import HttpJudge
from dry_lint.judges.jev import API_URL, QUESTIONS, JevJudge, state
from dry_lint.models import Candidate
from dry_lint.settings import Escalation, PluginChoice, Settings

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
    with pytest.raises(ValueError, match="Unknown judge 'oracle'; available: anthropic, claude-code, codex, command, gemini, jev"):
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
    # Invoke Python explicitly: Windows neither executes shebangs nor preserves unquoted backslashes in shlex.
    return shlex.join([sys.executable, str(path)])


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
    with pytest.raises(ValueError, match="without a JSON verdict"):
        CommandJudge(script(tmp_path, "print('no idea')\n")).judge([CANDIDATE], Settings())


def test_command_judge_prompt_names_both_sides() -> None:
    prompt = CommandJudge("llm").stdin(CANDIDATE)
    assert "# NEW: src/widgets/caption.py::clip" in prompt and "# EXISTING: src/text.py::shorten" in prompt
    assert "<<" not in prompt


def test_command_judge_runs_in_parallel_but_answers_in_order(tmp_path: Path) -> None:
    command = script(tmp_path, (
        "import json, sys, time\nprompt = sys.stdin.read()\nfirst = 'first_one' in prompt\n"
        "time.sleep(0.3 if first else 0)\n"
        "print(json.dumps({'label': 'duplicate', 'score': 0.9 if first else 0.1}))\n"
    ))
    slow = CANDIDATE.model_copy(update={"new": CANDIDATE.new.model_copy(update={"name": "first_one"})})
    assert [v.score for v in CommandJudge(command, workers=2).judge([slow, CANDIDATE], Settings())] == [0.9, 0.1]


def test_parse_verdict_takes_the_first_verdict_object_among_other_braces() -> None:
    text = ('The pair {a, b} is: {"label": "duplicate", "score": 0.9}\n'
            'Note: {"label": "separate", "score": 0.1} would apply if {x} differed. {not json}')
    verdict = parse_verdict(text, "g", "v")
    assert (verdict.label, verdict.score) == ("duplicate", 0.9)
    with pytest.raises(ValueError, match="without a JSON verdict"):
        parse_verdict('{"score": 0.9} and {broken', "g", "v")


def test_parse_verdict_reads_the_json_inside_any_text() -> None:
    verdict = parse_verdict('Sure: {"label": "drifted", "score": 0.82, "behaves_differently": 0.7} done', "g", "v")
    assert (verdict.label, verdict.score, verdict.behaves_differently, verdict.judge, verdict.judge_version) == (
        "drifted", 0.82, 0.7, "g", "v")


def gemini_answer(text: str, requests: list):
    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text[:9]}, {"text": text[9:]}]}}]})
    return httpx.MockTransport(answer)


def test_the_gemini_judge_asks_the_dry_prompt_and_reads_its_verdict() -> None:
    requests = []
    reply = '```json\n{"label": "duplicate", "score": 0.93, "owner": "existing", "why": "same truncation"}\n```'
    judge = GeminiJudge(model="gemini-x", api_key="secret", transport=gemini_answer(reply, requests))
    [verdict] = judge.judge([CANDIDATE], Settings())
    assert (verdict.label, verdict.score, verdict.owner, verdict.why) == ("duplicate", 0.93, "existing", "same truncation")
    assert (verdict.judge, verdict.judge_version) == ("gemini", f"{PROMPT_VERSION}:gemini-x")
    body = json.loads(requests[0].content)
    assert str(requests[0].url) == GEMINI_URL.format(model="gemini-x") and requests[0].headers["x-goog-api-key"] == "secret"
    assert "# NEW: src/widgets/caption.py::clip" in body["contents"][0]["parts"][0]["text"]
    assert body["generationConfig"] == {"temperature": 0}


def test_the_gemini_judge_needs_a_key_and_surfaces_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        GeminiJudge()
    failing = GeminiJudge(api_key="k", transport=httpx.MockTransport(lambda request: httpx.Response(429)))
    with pytest.raises(httpx.HTTPStatusError):
        failing.judge([CANDIDATE], Settings())
    with pytest.raises(ValueError, match="without a JSON verdict"):
        GeminiJudge(api_key="k", transport=gemini_answer("I cannot tell.", [])).judge([CANDIDATE], Settings())


def test_escalation_is_claude_sonnet_when_its_key_is_set_and_otherwise_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "key")
    assert make_escalation(Settings()) is None  # a Gemini key alone does not turn escalation on
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
    escalation = make_escalation(Settings())
    assert isinstance(escalation, AnthropicJudge) and escalation.model == "claude-sonnet-5-5"
    assert make_escalation(Settings(escalate=Escalation(use="gemini", model="gemini-y"))).model == "gemini-y"
    assert make_escalation(Settings(escalate=Escalation(use="none"))) is None
    assert make_escalation(Settings(escalate=None)) is None


def claude(reply: dict, requests: list) -> anthropic.DefaultHttpxClient:
    """A real SDK HTTP client whose transport answers every Messages call with `reply`."""

    def answer(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json={"id": "msg_1", "type": "message", "role": "assistant",
                                          "model": "claude-sonnet-5-5", "stop_sequence": None,
                                          "usage": {"input_tokens": 900, "output_tokens": 120}, **reply})

    return anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(answer))


def test_the_anthropic_judge_asks_through_the_sdk_with_refusal_fallbacks_and_reads_its_text() -> None:
    requests = []
    reply = {"stop_reason": "end_turn", "content": [
        {"type": "thinking", "thinking": "", "signature": "s"},
        {"type": "text", "text": '{"label": "drifted", "score": 0.88, "behaves_differently": 0.9, "owner": "shared"}'},
    ]}
    judge = AnthropicJudge(api_key="secret", effort="low", http_client=claude(reply, requests))
    [verdict] = judge.judge([CANDIDATE], Settings())
    assert (verdict.label, verdict.score, verdict.owner, verdict.judge) == ("drifted", 0.88, "shared", "anthropic")
    assert verdict.judge_version == f"{PROMPT_VERSION}:claude-sonnet-5-5:low"
    body = json.loads(requests[0].content)
    assert requests[0].url.path == "/v1/messages" and requests[0].headers["authorization"] == "Bearer secret"
    assert "server-side-fallback-2026-07-01" in requests[0].headers["anthropic-beta"]
    assert (body["model"], body["fallbacks"], body["output_config"]) == ("claude-sonnet-5-5", "default", {"effort": "low"})
    assert "# NEW: src/widgets/caption.py::clip" in body["messages"][0]["content"]
    assert judge.tokens == {"input": 900, "output": 120}


def test_the_anthropic_judge_sends_no_fallbacks_for_models_without_them() -> None:
    requests = []
    reply = {"stop_reason": "end_turn", "content": [{"type": "text", "text": '{"label": "separate", "score": 0.1}'}]}
    AnthropicJudge(model="claude-haiku-5-5", api_key="k", http_client=claude(reply, requests)).judge([CANDIDATE], Settings())
    body = json.loads(requests[0].content)
    assert "fallbacks" not in body and "output_config" not in body


def test_a_declined_pair_raises_instead_of_becoming_a_verdict() -> None:
    reply = {"stop_reason": "refusal", "stop_details": {"type": "refusal", "category": "cyber", "explanation": "x"},
             "content": []}
    with pytest.raises(ValueError, match="declined to judge .*cyber"):
        AnthropicJudge(api_key="k", http_client=claude(reply, [])).judge([CANDIDATE], Settings())


def test_the_anthropic_judge_needs_its_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        AnthropicJudge()


def test_an_http_judge_must_say_how_to_ask_and_how_to_read_an_answer() -> None:
    bare = HttpJudge(api_key="k")
    with pytest.raises(NotImplementedError):
        bare.request("text")
    with pytest.raises(NotImplementedError):
        bare.answer({})


def test_the_claude_code_judge_runs_the_cli_without_tools_and_without_an_api_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "would-bill-the-api")
    monkeypatch.setenv("KEEP_ME", "yes")
    cli = script(tmp_path, (
        "import json, os, sys\nprompt = sys.stdin.read()\n"
        "ok = 'ANTHROPIC_API_KEY' not in os.environ and os.environ.get('KEEP_ME') == 'yes'\n"
        "print(json.dumps({'label': 'duplicate', 'score': 0.9 if ok else 0.0, 'why': ' '.join(sys.argv[1:])}))\n"
    ))
    judge = make_judge(PluginChoice(use="claude-code", cli=cli))
    [verdict] = judge.judge([CANDIDATE], Settings())
    assert (verdict.score, verdict.judge, verdict.judge_version) == (0.9, "claude-code", f"{PROMPT_VERSION}:claude-sonnet-5-5")
    assert "-p --model claude-sonnet-5-5 --tools  --no-session-persistence" in verdict.why
    assert "--system-prompt Answer the question exactly as asked" in verdict.why
    assert judge.subscription and judge.model == "claude-sonnet-5-5"


def test_the_codex_judge_reads_the_last_message_codex_writes(tmp_path: Path) -> None:
    cli = script(tmp_path, (
        "import json, os, sys\nargs = sys.argv[1:]\nprompt = sys.stdin.read()\n"
        "out = args[args.index('-o') + 1]\n"
        "ok = '# NEW: src/widgets/caption.py::clip' in prompt and '--sandbox' in args and os.listdir('.') == []\n"
        "open(out, 'w').write(json.dumps({'label': 'separate', 'score': 0.2 if ok else 0.0, 'why': ' '.join(args)}))\n"
        "print('codex chatter on stdout')\n"
    ))
    judge = make_judge(PluginChoice(use="codex", cli=cli, model="gpt-x"))
    [verdict] = judge.judge([CANDIDATE], Settings())
    assert (verdict.label, verdict.score, verdict.judge, verdict.judge_version) == ("separate", 0.2, "codex", f"{PROMPT_VERSION}:gpt-x")
    assert verdict.why.startswith("exec -m gpt-x --sandbox read-only")
    assert make_judge(PluginChoice(use="codex", cli=cli)).version == f"{PROMPT_VERSION}:account-default"


def test_the_anthropic_judge_says_how_to_install_the_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "anthropic", None)  # as if the optional extra were not installed
    with pytest.raises(ValueError, match="pip install 'dry-lint\\[anthropic\\]'"):
        AnthropicJudge(api_key="k")
