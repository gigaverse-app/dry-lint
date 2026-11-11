"""The LangChain judge, with real LangChain and the real SDK against a local stand-in for the Messages API."""

import json
import sys
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from dry_lint.costs import price, usage_cost
from dry_lint.discovery import reservation_cost
from dry_lint.judges import make_judge
from dry_lint.judges.command import OPERATIONS_ANSWER, OPERATIONS_PROMPT, OPERATIONS_RULES, OPERATIONS_SOURCES
from dry_lint.judges.langchain import (
    CALL_THE_TOOL,
    STRUCTURED_PROMPT,
    STRUCTURED_RULES,
    ConsolidationOwner,
    DiagnosedVerdictPromptSchema,
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
STRUCTURED = resolve(Settings(preset="balanced"))


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
        self.cache = (0, 2300)  # tokens this response wrote to and read from the prompt cache
        self.delay = 0.0
        self.fail_after: int | None = None  # every request after this many gets a 500
        self.started: list[float] = []
        self.finished: list[float] = []
        self.requests: list[dict] = []
        self.keys: list[str] = []
        api = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                api.started.append(time.monotonic())
                time.sleep(api.delay)
                with lock:
                    api.requests.append(body)
                    api.keys.append(self.headers["x-api-key"] or self.headers["authorization"].removeprefix("Bearer "))
                    reply = api.replies[min(len(api.requests) - 1, len(api.replies) - 1)]
                    failing = api.fail_after is not None and len(api.requests) > api.fail_after
                    status = 500 if failing else api.status
                data = json.dumps(
                    {
                        "id": "msg_1",
                        "type": "message" if status == 200 else "error",
                        "role": "assistant",
                        "model": body["model"],
                        "stop_sequence": None,
                        "usage": {
                            "input_tokens": 900,
                            "output_tokens": 120,
                            "cache_creation_input_tokens": api.cache[0],
                            "cache_read_input_tokens": api.cache[1],
                        },
                        "error": {"type": "api_error", "message": "boom"},
                        **reply,
                    }
                ).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                api.finished.append(time.monotonic())

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
    # It never says which bands are reported: told that, the model scored real partial duplicates just below.
    assert "eported" not in fields["score"]["description"]
    assert "score that sub-operation" in fields["score"]["description"]
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
    # The model may think first, so the tool is offered, not forced; the request says to call it.
    assert request["thinking"] == {"type": "adaptive"} and "tool_choice" not in request
    assert list(tool["input_schema"]["properties"]) == ["reasoning", "score", "label", "owner"]
    assert "0.6-0.7: established" in tool["input_schema"]["properties"]["score"]["description"]
    [message] = request["messages"]
    rules, sources = message["content"]
    # One user turn, in the measured order: the rules, then the pair. Only the pair differs between requests.
    assert message["role"] == "user" and rules["text"] + sources["text"] == STRUCTURED_PROMPT.replace(
        "<<new_name>>", CANDIDATE.new.qualname
    ).replace("<<new_code>>", CANDIDATE.new.code).replace("<<existing_name>>", CANDIDATE.existing.qualname).replace(
        "<<existing_code>>", CANDIDATE.existing.code
    ) + CALL_THE_TOOL.format(tool="DuplicateVerdictPromptSchema")
    assert "def clip(text, n)" in sources["text"] and "def shorten(text, limit)" in sources["text"]
    assert "Answer one JSON object" not in rules["text"] + sources["text"]
    assert (answer.label, answer.score, answer.owner, answer.why) == (
        "duplicate",
        0.8,
        "existing",
        "both slice to a limit",
    )
    assert answer.judge == "langchain-operations"
    assert answer.judge_version == "dry-operations-v3+schema-3:claude-haiku-5-5:low"


@pytest.mark.parametrize(
    ("score", "said", "label"),
    [
        (0.45, "separate", "duplicate"),  # at or above drop_below the score decides, whatever the model's label
        (0.4, "duplicate", "duplicate"),
        (0.39, "duplicate", "separate"),
        (0.2, "separate", "separate"),
        (0.6, "drifted", "drifted"),  # the model's label still tells drifted from duplicate
        (0.1, "drifted", "separate"),
    ],
)
def test_the_label_follows_the_score_and_this_judges_thresholds(api: Api, score, said, label) -> None:
    api.replies = [verdict(score, said)]
    [answer] = api.judge().judge([CANDIDATE], STRUCTURED)

    assert (answer.label, answer.score) == (label, score)
    assert STRUCTURED.duplicate_at(answer, STRUCTURED.report_at) == (score >= 0.4)
    # It warns from 0.4 and blocks only from 0.5, where Opus confirmed 88% of its reports on real commits.
    assert STRUCTURED.duplicate_at(answer, STRUCTURED.fail_at) == (score >= 0.5)


def test_a_score_outside_the_range_is_clamped_and_no_owner_is_empty(api: Api) -> None:
    api.replies = [verdict(1.4), verdict(-0.2, "separate", "none")]
    high, low = api.judge(workers=1).judge([CANDIDATE, CANDIDATE], STRUCTURED)

    assert (high.score, low.score, low.label, low.owner) == (1.0, 0.0, "separate", "")


def test_answers_keep_their_order_and_usage_adds_up_across_workers(api: Api) -> None:
    api.replies = [verdict(0.8)]
    judge = api.judge(workers=4)
    answers = judge.judge([CANDIDATE] * 6, STRUCTURED)

    assert len(answers) == len(api.requests) == 6
    assert judge.tokens == {
        "input": 6 * 900,
        "output": 6 * 120,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 6 * 2300,
    }


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
    # Asked twice, the second time with the call forced; both were paid for and both are counted.
    assert len(api.requests) == 2 and judge.fallbacks == 1
    assert (judge.tokens["input"], judge.tokens["output"]) == (2 * 900, 2 * 120)


def test_a_provider_failure_is_a_judge_error_the_scheduler_can_record(api: Api) -> None:
    api.status = 500
    with pytest.raises(ValueError, match="LangChain request failed"):
        api.judge().judge([CANDIDATE], STRUCTURED)
    assert len(api.requests) == 1  # no retry by default: a retry would spend outside the reservation


def test_the_version_names_what_changes_the_answers(api: Api) -> None:
    assert api.judge().version == "dry-operations-v3+schema-3:claude-haiku-5-5:low"
    assert (
        api.judge(model="claude-sonnet-5-5", effort=None).version
        == "dry-operations-v3+schema-3:claude-sonnet-5-5:default"
    )
    assert api.judge(max_tokens=4096).version.endswith(":low:output=4096")
    assert api.judge(thinking=False).version.endswith(":low:no-thinking")
    assert api.judge(diagnostics=True).version.endswith(":low:diagnostics")
    api.judge(effort=None).judge([CANDIDATE], STRUCTURED)
    assert "output_config" not in api.requests[-1]


def test_it_needs_a_key_langchain_and_sane_options(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="needs ANTHROPIC_API_KEY"):
        LangChainJudge(base_url=api.url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-the-environment")
    LangChainJudge(base_url=api.url).judge([CANDIDATE], STRUCTURED)
    assert api.keys == ["from-the-environment"]
    with pytest.raises(ValueError, match="needs a positive output limit"):
        api.judge(max_tokens=0)
    monkeypatch.setitem(sys.modules, "langchain_anthropic", None)
    with pytest.raises(ValueError, match=r"pip install 'dry-lint\[anthropic\]'"):
        api.judge()


def test_an_answer_in_prose_is_asked_again_with_the_tool_forced(api: Api) -> None:
    prose = {"stop_reason": "end_turn", "content": [{"type": "text", "text": "They look like duplicates to me."}]}
    api.replies = [prose, verdict(0.7)]
    judge = api.judge()

    [answer] = judge.judge([CANDIDATE], STRUCTURED)

    first, second = api.requests
    # INVARIANT: a forced tool call switches thinking off, and thinking is where this judge finds a third of its
    # duplicates. So forcing is only the fallback, and it asks the same question.
    assert "tool_choice" not in first and "thinking" in first
    assert (
        second["tool_choice"] == {"type": "tool", "name": "DuplicateVerdictPromptSchema"} and "thinking" not in second
    )
    assert first["messages"] == second["messages"]
    assert (answer.score, answer.label, judge.fallbacks) == (0.7, "duplicate", 1)
    # The prose answer was paid for too. Its usage comes from the response itself, though no verdict came of it.
    assert (judge.tokens["input"], judge.tokens["output"]) == (2 * 900, 2 * 120)


def test_a_provider_failure_on_the_forced_request_is_a_judge_error_too(api: Api) -> None:
    api.replies = [{"stop_reason": "end_turn", "content": [{"type": "text", "text": "Duplicates, I think."}]}]
    api.fail_after = 1
    judge = api.judge()

    with pytest.raises(ValueError, match="LangChain request failed"):
        judge.judge([CANDIDATE], STRUCTURED)
    assert len(api.requests) == 2 and judge.fallbacks == 1
    assert (judge.tokens["input"], judge.tokens["output"]) == (900, 120)  # the prose answer, which was paid for


def test_without_thinking_the_tool_is_forced_at_once(api: Api) -> None:
    judge = api.judge(thinking=False)
    judge.judge([CANDIDATE], STRUCTURED)

    [request] = api.requests
    assert (
        request["tool_choice"] == {"type": "tool", "name": "DuplicateVerdictPromptSchema"} and "thinking" not in request
    )
    assert "Answer by calling" not in str(request["messages"]) and judge.fallbacks == 0


def test_diagnostics_ask_what_was_hard_after_the_verdict(api: Api) -> None:
    fields = list(DiagnosedVerdictPromptSchema.model_fields)
    # After the verdict, so they cannot move it.
    assert fields == ["reasoning", "score", "label", "owner", "difficulty", "missing_information"]
    filled = {
        "reasoning": "both slice to a limit",
        "score": 0.8,
        "label": "duplicate",
        "owner": "existing",
        "difficulty": "none",
        "missing_information": "the callers of shorten",
    }
    call = {"type": "tool_use", "id": "toolu_1", "name": "DiagnosedVerdictPromptSchema", "input": filled}
    api.replies = [{"stop_reason": "tool_use", "content": [call]}]
    judge = api.judge(diagnostics=True)

    [answer] = judge.judge([CANDIDATE], STRUCTURED)

    [request] = api.requests
    assert request["tools"][0]["name"] == "DiagnosedVerdictPromptSchema"
    assert "DiagnosedVerdictPromptSchema" in request["messages"][0]["content"][1]["text"]
    assert answer.why == "both slice to a limit\nHard: none\nMissing: the callers of shorten"
    assert "missing_information" in judge.input_text(CANDIDATE)  # reserved for, like everything the model reads
    assert api.judge().input_text(CANDIDATE) != judge.input_text(CANDIDATE)


def test_the_rules_and_the_schema_are_one_cached_prefix_and_the_pair_is_not(api: Api) -> None:
    other = CANDIDATE.model_copy(
        update={"existing": function("src/names.py", "def initials(name):\n    return name[:1]\n")}
    )
    api.judge(workers=1).judge([CANDIDATE, other], STRUCTURED)

    first, second = api.requests
    (rules, pair), (rules_again, other_pair) = first["messages"][0]["content"], second["messages"][0]["content"]
    # INVARIANT: caching is a prefix match over tools, then messages. Everything up to the marked block must be
    # byte-identical in every request, and nothing that varies may come before it.
    assert rules == rules_again == {"type": "text", "text": STRUCTURED_RULES, "cache_control": {"type": "ephemeral"}}
    assert first["tools"] == second["tools"] and "system" not in first
    assert "cache_control" not in pair and pair != other_pair
    assert CANDIDATE.new.qualname not in rules["text"]


def test_the_first_request_finishes_before_the_others_start_so_they_read_its_cache(api: Api) -> None:
    api.delay = 0.3
    judge = api.judge(workers=4)
    judge.judge([CANDIDATE] * 4, STRUCTURED)

    started, finished = sorted(api.started), sorted(api.finished)
    # INVARIANT: one request writes the cached prefix alone; asked together, all four would pay to write it.
    assert started[1] >= finished[0]
    assert started[3] < finished[1]  # after that they run side by side


def test_cache_writes_and_reads_are_counted_and_priced_at_their_own_rates(api: Api) -> None:
    judge = api.judge(workers=1)
    api.cache = (2300, 0)  # the first request writes the prefix
    judge.judge([CANDIDATE], STRUCTURED)
    api.cache = (0, 2300)  # later ones read it
    judge.judge([CANDIDATE, CANDIDATE], STRUCTURED)

    assert judge.tokens == {
        "input": 3 * 900,
        "output": 3 * 120,
        "cache_creation_input_tokens": 2300,
        "cache_read_input_tokens": 2 * 2300,
    }
    rates = price(judge, STRUCTURED)
    # The provider's `input_tokens` is the uncached part only; a read costs a tenth of it, a write a quarter more.
    assert usage_cost(judge.tokens, rates) == pytest.approx(
        ((3 * 900 + 1.25 * 2300 + 0.1 * 2 * 2300) * rates[0] + 3 * 120 * rates[1]) / 1e6
    )
    assert usage_cost(judge.tokens, rates) < usage_cost({"input": 3 * (900 + 2300), "output": 3 * 120}, rates)


def test_balanced_is_this_judge_with_its_own_thresholds_and_the_text_setup_keeps_a_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = resolve(Settings(preset="balanced-text"))
    assert (STRUCTURED.judge.use, STRUCTURED.judge.options()) == (
        "langchain",
        {"model": "claude-haiku-5-5", "effort": "low", "max_tokens": 2048},
    )
    assert (STRUCTURED.drop_below, STRUCTURED.report_at, STRUCTURED.fail_at) == (0.4, 0.4, 0.5)
    assert STRUCTURED.escalate is None
    # What balanced was until this judge: the text answer and its thresholds, for an adopter who stays on it.
    assert (text.judge.use, text.judge.options()["prompt_policy"]) == ("anthropic", "shared-operations")
    assert (text.drop_below, text.report_at, text.fail_at) == (0.5, 0.5, 0.5)
    assert STRUCTURED.discovery == text.discovery and STRUCTURED.budget == text.budget
    # The CLI still answers in text, so the subscription preset keeps the text judge's thresholds.
    subscription = resolve(Settings(preset="balanced-subscription"))
    assert subscription.judge.use == "claude-code"
    assert (subscription.drop_below, subscription.report_at, subscription.fail_at) == (0.5, 0.5, 0.5)
    assert AUTO_ORDER[:2] == ("balanced", "balanced-subscription") and "balanced-text" not in AUTO_ORDER
    assert PRESETS["balanced"].automatic and PRESETS["balanced"].measured and not PRESETS["balanced-text"].automatic
    assert "balanced-structured" not in PRESETS
    monkeypatch.setenv("ANTHROPIC_API_KEY", "adopter-key")
    judge = make_judge(STRUCTURED.judge)
    assert isinstance(judge, LangChainJudge)
    # Priced by its model with an output ceiling, so the discovery scheduler can reserve for it, and the
    # reservation covers what the model really reads: the question, both functions and the whole schema.
    assert "0.6-0.7: established" in judge.input_text(CANDIDATE) and "def clip(text, n)" in judge.input_text(CANDIDATE)
    assert reservation_cost(judge, CANDIDATE, STRUCTURED) > 0
