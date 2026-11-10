"""The LangChain judge, with real LangChain and the real SDK against a local stand-in for the Messages API."""

import json
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from dry_lint.discovery import reservation_cost
from dry_lint.judges import make_judge
from dry_lint.judges.langchain import DuplicateVerdictPromptSchema, LangChainJudge
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
    return {
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": json.dumps({"why": why, "label": label, "score": score, "owner": owner})}],
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


def test_the_reason_is_the_schemas_first_field() -> None:
    # INVARIANT: fields are generated in order. Deciding before reasoning cost a third of the measured recall.
    assert list(DuplicateVerdictPromptSchema.model_fields) == ["why", "label", "score", "owner"]


def test_it_asks_for_the_schema_with_the_adopters_key_and_the_dry_prompt(api: Api) -> None:
    [answer] = api.judge().judge([CANDIDATE], STRUCTURED)

    [request] = api.requests
    assert api.keys == ["adopter-key"]
    assert request["model"] == "claude-haiku-5-5" and request["max_tokens"] == 2048
    assert request["output_config"]["effort"] == "low"
    schema = request["output_config"]["format"]
    assert schema["type"] == "json_schema"
    assert list(schema["schema"]["properties"]) == schema["schema"]["required"] == ["why", "label", "score", "owner"]
    # A forced tool call lost answers to missing fields; the schema is the output format, not a tool.
    assert "tools" not in request and "tool_choice" not in request
    [message] = request["messages"]
    assert "def clip(text, n)" in str(message["content"]) and "def shorten(text, limit)" in str(message["content"])
    assert (answer.label, answer.score, answer.owner, answer.why) == (
        "duplicate",
        0.8,
        "existing",
        "both slice to a limit",
    )
    assert answer.judge == "langchain-operations"
    assert answer.judge_version == "dry-operations-v3+schema-1:claude-haiku-5-5:low"


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


def test_a_score_outside_the_range_is_clamped(api: Api) -> None:
    api.replies = [verdict(1.4), verdict(-0.2)]
    high, low = api.judge(workers=1).judge([CANDIDATE, CANDIDATE], STRUCTURED)

    assert (high.score, low.score, low.label) == (1.0, 0.0, "separate")


def test_answers_keep_their_order_and_usage_adds_up_across_workers(api: Api) -> None:
    api.replies = [verdict(0.8)]
    judge = api.judge(workers=4)
    answers = judge.judge([CANDIDATE] * 6, STRUCTURED)

    assert len(answers) == len(api.requests) == 6
    assert judge.tokens == {"input": 6 * 900, "output": 6 * 120}


def test_an_answer_cut_off_at_the_output_limit_is_an_error_not_a_verdict(api: Api) -> None:
    api.replies = [{"stop_reason": "max_tokens", "content": [{"type": "text", "text": '{"why": "both functions sli'}]}]
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
    assert api.judge().version == "dry-operations-v3+schema-1:claude-haiku-5-5:low"
    assert (
        api.judge(model="claude-sonnet-5-5", effort=None).version
        == "dry-operations-v3+schema-1:claude-sonnet-5-5:default"
    )
    assert api.judge(max_tokens=4096).version.endswith(":low:output=4096")
    api.judge(effort=None).judge([CANDIDATE], STRUCTURED)
    assert "effort" not in api.requests[-1]["output_config"]


def test_it_needs_a_key_the_extra_and_sane_options(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="needs ANTHROPIC_API_KEY"):
        LangChainJudge(base_url=api.url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-the-environment")
    LangChainJudge(base_url=api.url).judge([CANDIDATE], STRUCTURED)
    assert api.keys == ["from-the-environment"]
    with pytest.raises(ValueError, match="Unknown prompt policy or nonpositive output limit"):
        api.judge(max_tokens=0)
    with pytest.raises(ValueError, match="Unknown prompt policy or nonpositive output limit"):
        api.judge(prompt_policy="nope")
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
    assert (STRUCTURED.drop_below, STRUCTURED.report_at, STRUCTURED.fail_at) == (0.3, 0.3, 0.3)
    assert STRUCTURED.discovery == balanced.discovery and STRUCTURED.budget == balanced.budget
    assert STRUCTURED.escalate is None
    # Chosen by name only, and it says it has not been replayed on pull requests.
    preset = PRESETS["balanced-structured"]
    assert "balanced-structured" not in AUTO_ORDER and not preset.automatic and not preset.measured
    monkeypatch.setenv("ANTHROPIC_API_KEY", "adopter-key")
    judge = make_judge(STRUCTURED.judge)
    assert isinstance(judge, LangChainJudge)
    # Priced by its model with an output ceiling, so the discovery scheduler can reserve for it.
    assert reservation_cost(judge, CANDIDATE, STRUCTURED) > 0
