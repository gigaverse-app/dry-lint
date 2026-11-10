"""The LangChain judge, with real LangChain and the real SDK against a local stand-in for the Messages API."""

import json
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from dry_lint.discovery import reservation_cost
from dry_lint.judges import make_judge
from dry_lint.judges.command import OPERATIONS_ANSWER, OPERATIONS_PROMPT, OPERATIONS_RULES, OPERATIONS_SOURCES
from dry_lint.judges.langchain import (
    STRUCTURED_PROMPT,
    ConsolidationOwner,
    DuplicateVerdictPromptSchema,
    DuplicationLabel,
    LangChainJudge,
)
from dry_lint.models import Candidate
from dry_lint.presets import AUTO_ORDER, PRESETS, resolve
from dry_lint.settings import Settings

from conftest import function

CANDIDATE = Candidate(
    new=function("src/widgets/caption.py", "def clip(text, n):\n    return text[:n]\n"),
    existing=function("src/text.py", "def shorten(text, limit):\n    return text[:limit]\n"),
    similarity=0.8,
)
STRUCTURED = resolve(Settings(preset="balanced-structured"))


def verdict(
    score: float, label: str = "duplicate", owner: str = "existing", why: str = "both slice to a limit"
) -> dict:
    """A tool call filling the schema, as the provider returns it for `with_structured_output`."""
    filled = {"reasoning": why, "score": score, "label": label, "owner": owner}
    return {
        "stop_reason": "tool_use",
        "content": [{"type": "tool_use", "id": "toolu_1", "name": "DuplicateVerdictPromptSchema", "input": filled}],
    }


class Api:
    """Answers every Messages call with the next of `replies` (the last one repeats) and keeps the requests."""

    def __init__(self) -> None:
        self.replies: list[dict] = [verdict(0.8)]
        self.status = 200
        self.requests: list[dict] = []
        self.keys: list[str] = []
        api = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                with lock:
                    api.requests.append(body)
                    api.keys.append(self.headers["x-api-key"] or self.headers["authorization"].removeprefix("Bearer "))
                    reply = api.replies[min(len(api.requests) - 1, len(api.replies) - 1)]
                data = json.dumps(
                    {
                        "id": "msg_1",
                        "type": "message" if api.status == 200 else "error",
                        "role": "assistant",
                        "model": body["model"],
                        "stop_sequence": None,
                        "usage": {"input_tokens": 900, "output_tokens": 120},
                        "error": {"type": "api_error", "message": "boom"},
                        **reply,
                    }
                ).encode()
                self.send_response(api.status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args: object) -> None:
                pass

        lock = threading.Lock()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def judge(self, **options: object) -> LangChainJudge:
        return LangChainJudge(api_key="adopter-key", base_url=self.url, **options)


@pytest.fixture
def api() -> Iterator[Api]:
    api = Api()
    yield api
    api.server.shutdown()
    api.server.server_close()


def test_the_reasoning_is_the_schemas_first_field() -> None:
    # INVARIANT: fields are generated in order. Deciding before reasoning cost a third of the measured recall.
    assert list(DuplicateVerdictPromptSchema.model_fields) == ["reasoning", "score", "label", "owner"]


def test_the_schema_is_prompt_text_enums_descriptions_and_a_score_rubric() -> None:
    schema = DuplicateVerdictPromptSchema.model_json_schema()
    assert "independently implement the same operation" in schema["description"]
    fields = schema["properties"]
    # Every field tells the model what to write; none is a bare type.
    assert all(len(fields[name]["description"]) > 150 for name in ("reasoning", "score", "label", "owner"))
    # The score is anchored: each band says what evidence earns it, and where reporting starts.
    for band in ("0.0-0.1", "0.2-0.3", "0.4-0.5", "0.6-0.7", "0.8-0.9", "1.0"):
        assert band + ":" in fields["score"]["description"]
    assert (
        "Not reported" in fields["score"]["description"] and "Reported to the author" in fields["score"]["description"]
    )
    # Closed choices are enums the provider can enforce, not strings to be guessed.
    assert [label.value for label in DuplicationLabel] == ["duplicate", "drifted", "separate"]
    assert [owner.value for owner in ConsolidationOwner] == ["new", "existing", "shared", "none"]
    assert schema["$defs"]["DuplicationLabel"]["enum"] == ["duplicate", "drifted", "separate"]
    assert schema["$defs"]["ConsolidationOwner"]["enum"] == ["new", "existing", "shared", "none"]
    assert schema["required"] == ["reasoning", "score", "label", "owner"]


def test_it_asks_the_text_judges_question_without_their_answer_format() -> None:
    # INVARIANT: the text prompt is the three parts joined, so this judge and the text judges ask one question.
    assert OPERATIONS_PROMPT == OPERATIONS_RULES + OPERATIONS_ANSWER + OPERATIONS_SOURCES
    assert STRUCTURED_PROMPT.startswith(OPERATIONS_RULES) and STRUCTURED_PROMPT.endswith(OPERATIONS_SOURCES)
    # The schema is the only statement of the format: two formats in one request contradict each other.
    assert "Answer one JSON object" not in STRUCTURED_PROMPT and '{"label"' not in STRUCTURED_PROMPT
    assert "limit your reasoning to the shared sub-operation" in STRUCTURED_PROMPT


def test_it_sends_the_schema_the_adopters_key_and_both_functions(api: Api) -> None:
    [answer] = api.judge().judge([CANDIDATE], STRUCTURED)

    [request] = api.requests
    assert api.keys == ["adopter-key"]
    assert request["model"] == "claude-haiku-5-5" and request["max_tokens"] == 2048
    assert request["output_config"] == {"effort": "low"}
    [tool] = request["tools"]
    assert tool["name"] == "DuplicateVerdictPromptSchema"
    assert request["tool_choice"] == {"type": "tool", "name": "DuplicateVerdictPromptSchema"}
    assert list(tool["input_schema"]["properties"]) == ["reasoning", "score", "label", "owner"]
    assert "0.6-0.7: established" in tool["input_schema"]["properties"]["score"]["description"]
    [message] = request["messages"]
    assert "def clip(text, n)" in str(message["content"]) and "def shorten(text, limit)" in str(message["content"])
    assert "Answer one JSON object" not in str(message["content"])
    assert (answer.label, answer.score, answer.owner, answer.why) == (
        "duplicate",
        0.8,
        "existing",
        "both slice to a limit",
    )
    assert answer.judge == "langchain-operations"
    assert answer.judge_version == "dry-operations-v3+schema-2:claude-haiku-5-5:low"


@pytest.mark.parametrize(
    ("score", "said", "label"),
    [
        (0.35, "separate", "duplicate"),  # at or above drop_below the score decides, whatever the model's label
        (0.3, "duplicate", "duplicate"),
        (0.29, "duplicate", "separate"),
        (0.2, "separate", "separate"),
        (0.6, "drifted", "drifted"),  # the model's label still tells drifted from duplicate
        (0.1, "drifted", "separate"),
    ],
)
def test_the_label_follows_the_score_and_this_judges_thresholds(api: Api, score, said, label) -> None:
    api.replies = [verdict(score, said)]
    [answer] = api.judge().judge([CANDIDATE], STRUCTURED)

    assert (answer.label, answer.score) == (label, score)
    assert STRUCTURED.duplicate_at(answer, STRUCTURED.report_at) == (score >= 0.3)
    # It warns from 0.3 and blocks only from 0.4, where its reports were almost all confirmed.
    assert STRUCTURED.duplicate_at(answer, STRUCTURED.fail_at) == (score >= 0.4)


def test_a_score_outside_the_range_is_clamped_and_no_owner_is_empty(api: Api) -> None:
    api.replies = [verdict(1.4), verdict(-0.2, "separate", "none")]
    high, low = api.judge(workers=1).judge([CANDIDATE, CANDIDATE], STRUCTURED)

    assert (high.score, low.score, low.label, low.owner) == (1.0, 0.0, "separate", "")


def test_answers_keep_their_order_and_usage_adds_up_across_workers(api: Api) -> None:
    api.replies = [verdict(0.8)]
    judge = api.judge(workers=4)
    answers = judge.judge([CANDIDATE] * 6, STRUCTURED)

    assert len(answers) == len(api.requests) == 6
    assert judge.tokens == {"input": 6 * 900, "output": 6 * 120}


def test_an_answer_cut_off_at_the_output_limit_is_an_error_not_a_verdict(api: Api) -> None:
    cut = {"reasoning": "both functions sli"}  # the limit hit inside the first field
    api.replies = [
        {
            "stop_reason": "max_tokens",
            "content": [{"type": "tool_use", "id": "toolu_1", "name": "DuplicateVerdictPromptSchema", "input": cut}],
        }
    ]
    judge = api.judge()

    with pytest.raises(ValueError, match="gave no complete verdict for src/widgets/caption.py::clip"):
        judge.judge([CANDIDATE], STRUCTURED)
    assert judge.tokens == {"input": 900, "output": 120}  # the call was paid for and is counted


def test_a_provider_failure_is_a_judge_error_the_scheduler_can_record(api: Api) -> None:
    api.status = 500
    with pytest.raises(ValueError, match="LangChain request failed"):
        api.judge().judge([CANDIDATE], STRUCTURED)
    assert len(api.requests) == 1  # no retry by default: a retry would spend outside the reservation


def test_the_version_names_what_changes_the_answers(api: Api) -> None:
    assert api.judge().version == "dry-operations-v3+schema-2:claude-haiku-5-5:low"
    assert (
        api.judge(model="claude-sonnet-5-5", effort=None).version
        == "dry-operations-v3+schema-2:claude-sonnet-5-5:default"
    )
    assert api.judge(max_tokens=4096).version.endswith(":low:output=4096")
    api.judge(effort=None).judge([CANDIDATE], STRUCTURED)
    assert "output_config" not in api.requests[-1]


def test_it_needs_a_key_the_extra_and_sane_options(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="needs ANTHROPIC_API_KEY"):
        LangChainJudge(base_url=api.url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-the-environment")
    LangChainJudge(base_url=api.url).judge([CANDIDATE], STRUCTURED)
    assert api.keys == ["from-the-environment"]
    with pytest.raises(ValueError, match="needs a positive output limit"):
        api.judge(max_tokens=0)
    monkeypatch.setitem(sys.modules, "langchain_anthropic", None)
    with pytest.raises(ValueError, match=r"pip install 'dry-lint\[langchain\]'"):
        api.judge()


def test_balanced_structured_is_balanced_with_this_judge_and_its_own_thresholds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    balanced = resolve(Settings(preset="balanced"))
    assert (STRUCTURED.judge.use, STRUCTURED.judge.options()) == (
        "langchain",
        {"model": "claude-haiku-5-5", "effort": "low", "max_tokens": 2048},
    )
    assert (STRUCTURED.drop_below, STRUCTURED.report_at, STRUCTURED.fail_at) == (0.3, 0.3, 0.4)
    assert STRUCTURED.discovery == balanced.discovery and STRUCTURED.budget == balanced.budget
    assert STRUCTURED.escalate is None
    # Chosen by name only, and it says it has not been replayed on pull requests.
    preset = PRESETS["balanced-structured"]
    assert "balanced-structured" not in AUTO_ORDER and not preset.automatic and not preset.measured
    monkeypatch.setenv("ANTHROPIC_API_KEY", "adopter-key")
    judge = make_judge(STRUCTURED.judge)
    assert isinstance(judge, LangChainJudge)
    # Priced by its model with an output ceiling, so the discovery scheduler can reserve for it, and the
    # reservation covers what the model really reads: the question, both functions and the whole schema.
    assert "0.6-0.7: established" in judge.input_text(CANDIDATE) and "def clip(text, n)" in judge.input_text(CANDIDATE)
    assert reservation_cost(judge, CANDIDATE, STRUCTURED) > 0
