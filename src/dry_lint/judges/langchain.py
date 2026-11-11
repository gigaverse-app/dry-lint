"""
Claude as a judge through LangChain, answering in a schema instead of free text
(`pip install 'dry-lint[anthropic]'`). It is the judge of the `balanced` preset.

    judge = { use = "langchain", model = "claude-haiku-5-5" }        # ANTHROPIC_API_KEY in the environment
    preset = "balanced"                                               # this judge, with its measured thresholds

It asks the shared-operations question (`OPERATIONS_RULES` in judges/command.py) and gets a
`DuplicateVerdictPromptSchema` back through `with_structured_output`. The schema is prompt text: the model reads
its docstring, its field names, its field descriptions and its enum values, in field order. What was measured
(docs/benchmark.md#structured-answers) is therefore written into it:

- **The reasoning comes first.** With the decision first the model commits before it has compared the two
  functions, and recall on labelled duplicates fell from 87% to 48-58%.
- **Everything is spelled out.** A first schema with bare literals and one-line descriptions lost 4-8% of answers
  to missing fields. This one, with enums, full descriptions and a score rubric, lost none of 1,412.
- **The score has a rubric,** so 0.4 means the same thing in every answer, and the label agrees with it.
  The rubric does not say which bands are reported, and scores a shared sub-operation by itself.
- **The model thinks first.** A forced tool call switches thinking off, and then this judge found 95
  confirmed duplicates on real commits where it finds 121 with thinking. So the tool is offered, the
  request says to call it, and forcing is only the fallback (2 of 1,362 pairs).
- **It lists how the copies differ,** between the reasoning and the score, so a report shows drift a reviewer
  would otherwise have to find. On 748 labelled pairs it moved neither the ranking nor reporting at 0.4.

Its scores spread over the rubric where the text judge's are nearly yes or no, so its thresholds are its
own (presets.py). `diagnostics = true` adds two fields after the verdict, what was hard and what was
missing: read over many pairs, they show which rule the judge trips on.

The schema and the rules are the same in every request, so they are sent as one cached prefix: the tool
definition, then the rules as the first block of the user turn, marked `cache_control`. Every call after the first
reads about 2,300 tokens from the cache at a tenth of the input price. The two sources follow, uncached.

LangChain traces prompts, which contain your source, to LangSmith when you set its tracing variables
(`LANGSMITH_TRACING`, `LANGSMITH_API_KEY`). dry-lint never sets them; whether to trace is the adopter's choice.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from enum import StrEnum
from threading import Lock
from typing import Any

from pydantic import BaseModel, Field

from dry_lint.judges.command import OPERATIONS_RULES, OPERATIONS_SOURCES, OPERATIONS_VERSION, prompt
from dry_lint.models import Candidate, Difference, Verdict
from dry_lint.settings import Settings

SCHEMA_VERSION = "schema-4"  # schema-4 adds `differences`; strict_version re-asks schema-3 answers once
MAX_DIFFERENCES = 5
# The question, without the text judges' "answer one JSON object" block: here the schema is the only statement of
# the answer's format, and two formats in one request contradict each other.
STRUCTURED_RULES = (
    OPERATIONS_RULES
    + "For partial duplication, limit your reasoning to the shared sub-operation; do not claim both whole functions\n"
    "do the same thing. Prefer separate when the source does not establish a useful common operation.\n\n"
)
# What the model reads, in order: the rules, then the two sources. Sent as two blocks of one user turn.
STRUCTURED_PROMPT = STRUCTURED_RULES + OPERATIONS_SOURCES


class DuplicationLabel(StrEnum):
    """What the pair is, decided after the reasoning and consistent with the score."""

    DUPLICATE = "duplicate"
    DRIFTED = "drifted"
    SEPARATE = "separate"


class ConsolidationOwner(StrEnum):
    """Where the single implementation of the shared operation should live."""

    NEW = "new"
    EXISTING = "existing"
    SHARED = "shared"
    NONE = "none"


# The class name, docstring and descriptions are prompt text, written as measured (docs/benchmark.md#differences).
class BehaviourDifference(BaseModel):
    """One decision the two functions make differently in the part they share."""

    what: str = Field(description="The decision the two functions make differently, in a few words.")
    new_does: str = Field(description="What NEW does, in one short phrase.")
    existing_does: str = Field(description="What EXISTING does, in one short phrase.")
    consequence: str = Field(
        description="What observably differs as a result. If that depends on code you cannot see, say so."
    )


class DuplicateVerdictPromptSchema(BaseModel):
    """Your verdict on whether NEW and EXISTING independently implement the same operation.

    Fill the fields in order. Write the reasoning first and derive the score and label from it; never choose
    a label and then justify it. Judge only what the two sources establish.
    """

    # INVARIANT: `reasoning` stays the first field. Fields are generated in order, and a decision written before
    # the comparison costs a third of the recall. tests/test_langchain_judge.py locks the order.
    reasoning: str = Field(
        description=(
            "Compare the two functions before deciding anything. In two to five sentences: (1) name the candidate "
            "shared operation, or say that there is none; (2) compare its executable steps, inputs, outputs, "
            "ordering and failure handling in NEW and in EXISTING; (3) say whether both already delegate it to "
            "the same helper or owner; (4) name the legitimate variation a shared helper would take as "
            "parameters. For a partial overlap, describe only the shared sub-operation, not the whole functions."
        )
    )
    # After the reasoning, before the score: listing how the copies differ moved AUC and false reports at 0.4 by
    # less than their noise, and the last sentence keeps a recorded difference from turning into a lower score.
    differences: list[BehaviourDifference] = Field(
        description=(
            "List the behavioural differences in the part the two functions share. Empty when they share nothing "
            "or behave the same. At most five. A difference is recorded, never a reason to lower the score."
        )
    )
    # The rubric does not say which bands are reported: told that, the model scored real partial duplicates just
    # under the line. It scores the shared part itself, so a sub-operation is not marked down for its surroundings.
    score: float = Field(
        description=(
            "Confidence, from 0.0 to 1.0, that one concrete reusable operation is independently implemented in "
            "both functions. Score the shared operation itself: when two otherwise different functions contain the "
            "same sub-operation, score that sub-operation, not how much of the functions it covers or how "
            "different the rest is. Do not lower the score because the operation is small, because the "
            "surrounding workflows differ, or because you doubt anyone will refactor it. Use this rubric and pick "
            "the band your reasoning supports:\n"
            "0.0-0.1: nothing shared beyond names, types, imports, API calls, loop shapes or the business domain.\n"
            "0.2-0.3: a resemblance only. You cannot name an operation that both implement: the matching "
            "behaviour is already delegated by both to the same helper or owner, or the overlap is generic syntax, "
            "an interface, a stub or a resource-specific template.\n"
            "0.4-0.5: you can name a concrete operation that appears in both, but the evidence is incomplete: its "
            "steps, ordering, failure handling or contract differ in ways a parameter may not cover, or part of it "
            "cannot be told from the source shown.\n"
            "0.6-0.7: established. Both functions independently implement the named operation, whole or as a "
            "sub-operation, with matching steps and contract, and one helper with parameters for the variation "
            "could serve both.\n"
            "0.8-0.9: the same operation with the same steps, inputs, outputs and failure handling; any "
            "difference is cosmetic or one clear parameter.\n"
            "1.0: identical or renamed code."
        )
    )
    label: DuplicationLabel = Field(
        description=(
            "Must agree with the score. 'separate' when the score is below 0.4. 'duplicate' when the score is 0.4 "
            "or higher and both implementations give the same outcome on comparable inputs. 'drifted' when the "
            "score is 0.4 or higher and the two implementations of that SAME operation give conflicting outcomes "
            "on comparable inputs; legitimate domain variation or different enclosing workflows is not drift."
        )
    )
    owner: ConsolidationOwner = Field(
        description=(
            "Where the shared operation should live: 'existing' when NEW should call EXISTING or its helper; "
            "'new' when EXISTING should adopt NEW's implementation; 'shared' when both should call a helper "
            "extracted from them; 'none' when the label is separate."
        )
    )


class DiagnosedVerdictPromptSchema(DuplicateVerdictPromptSchema):
    """Your verdict on whether NEW and EXISTING independently implement the same operation.

    Fill the fields in order. Write the reasoning first and derive the score and label from it; never choose
    a label and then justify it. Judge only what the two sources establish. The last two fields are about the
    judging itself and do not change the verdict: they tell the maintainers of this task what was hard.
    """

    # After the verdict, so they cannot move it. Read them over many pairs to see which rule the judge trips on.
    difficulty: str = Field(
        description=(
            "What made this pair hard to judge, in one sentence: the tension between rules or the ambiguity in "
            "the source. Write 'none' when the verdict was clear."
        )
    )
    missing_information: str = Field(
        description=(
            "Only what would have CHANGED your verdict had you seen it, in one sentence: for example the body of "
            "a helper both call. Write 'none' when the two sources were enough to decide, which is the usual case."
        )
    )


# With thinking on, the tool cannot be forced, so the request says how to answer. Without this line the model
# answered in prose in three of five probes; with it, 2 of 1,362 real pairs needed the forced call.
CALL_THE_TOOL = "\nAnswer by calling the `{tool}` tool exactly once. Do not answer in text.\n"
USAGE_KINDS = {
    "input": "input_tokens",
    "output": "output_tokens",
    "cache_creation_input_tokens": "cache_creation_input_tokens",
    "cache_read_input_tokens": "cache_read_input_tokens",
}


class LangChainJudge:
    name = "langchain-operations"
    subscription = False
    strict_version = True  # another model, effort or schema is another judge: its answers are never reused

    def __init__(
        self,
        model: str = "claude-haiku-5-5",
        api_key: str | None = None,
        effort: str | None = "low",
        workers: int = 4,
        timeout: float = 120,
        max_tokens: int = 2048,
        max_retries: int = 0,
        base_url: str | None = None,
        thinking: bool = True,
        diagnostics: bool = False,
    ) -> None:
        if max_tokens < 1:
            raise ValueError("The langchain judge needs a positive output limit")
        try:
            from langchain_anthropic import ChatAnthropic
            from langchain_core.callbacks import BaseCallbackHandler
        except ImportError as error:  # an optional extra
            raise ValueError("The langchain judge needs LangChain: pip install 'dry-lint[anthropic]'") from error
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise ValueError("The langchain judge needs ANTHROPIC_API_KEY")
        self.model, self.effort, self.workers, self.max_tokens = model, effort, workers, max_tokens
        self.thinking = thinking
        self.schema = DiagnosedVerdictPromptSchema if diagnostics else DuplicateVerdictPromptSchema
        self.version = f"{OPERATIONS_VERSION}+{SCHEMA_VERSION}:{model}:{effort or 'default'}"
        if not thinking:
            self.version += ":no-thinking"
        if diagnostics:
            self.version += ":diagnostics"
        if max_tokens != 2048:
            self.version += f":output={max_tokens}"
        options: dict[str, Any] = {"output_config": {"effort": effort}} if effort else {}
        if base_url:
            options["anthropic_api_url"] = base_url
        options.update(
            model=model, max_tokens=max_tokens, anthropic_api_key=key, default_request_timeout=timeout,
            max_retries=max_retries,
        )  # fmt: skip
        # The mode is named, not left to LangChain's default: every number in the benchmark is a tool call's.
        # A forced tool call switches thinking off, and without thinking this judge misses a third of the
        # duplicates it otherwise finds. So the first request lets the model think and call the tool itself; the
        # forced request is only the fallback for an answer that came back as prose.
        structured = {"method": "function_calling", "include_raw": True}
        self.forced = ChatAnthropic(**options).with_structured_output(self.schema, **structured)
        self.chain = self.forced
        if thinking:
            thoughtful = ChatAnthropic(thinking={"type": "adaptive"}, **options)
            self.chain = thoughtful.with_structured_output(self.schema, **structured)
        self.tokens = dict.fromkeys(USAGE_KINDS, 0)
        self.fallbacks = 0
        lock = Lock()
        judge = self

        class Usage(BaseCallbackHandler):
            """Every response's own usage, as the API returned it: also of an answer LangChain then rejects.

            Never a difference of shared counters. The provider's fields are read, not LangChain's summary:
            `input_tokens` there is the uncached part, and cache writes and reads have their own rates.
            """

            def on_llm_end(self, response: Any, **_: Any) -> None:
                for generations in response.generations:
                    for generation in generations:
                        usage = (generation.message.response_metadata or {}).get("usage") or {}
                        with lock:
                            for kind, field in USAGE_KINDS.items():
                                judge.tokens[kind] += usage.get(field) or 0

        self._config = {"callbacks": [Usage()]}
        self._lock = lock
        self._first, self._warm = Lock(), False

    def _sources(self, candidate: Candidate) -> str:
        text = prompt(candidate, template=OPERATIONS_SOURCES)
        return text + CALL_THE_TOOL.format(tool=self.schema.__name__) if self.thinking else text

    def input_text(self, candidate: Candidate) -> str:
        """Everything the model reads, for cost estimates and reservations: the question and the schema."""
        return STRUCTURED_RULES + self._sources(candidate) + json.dumps(self.schema.model_json_schema())

    def messages(self, candidate: Candidate) -> list[Any]:
        """One user turn: the rules as a cached block, then this pair's sources."""
        from langchain_core.messages import HumanMessage

        return [
            HumanMessage(
                content=[
                    {"type": "text", "text": STRUCTURED_RULES, "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": self._sources(candidate)},
                ]
            )
        ]

    def _answer(self, candidate: Candidate) -> Any:
        """The filled schema, or None when neither request produced one."""
        from langchain_core.exceptions import OutputParserException

        messages = self.messages(candidate)
        try:
            parsed, asked = None, False
            if not self._warm:
                # The first request writes the cached prefix; the others wait for it and read it. Asked all at
                # once, every worker would pay to write the same prefix.
                with self._first:
                    if not self._warm:
                        try:
                            parsed, asked = self.chain.invoke(messages, config=self._config)["parsed"], True
                        finally:
                            self._warm = True
            if not asked:
                parsed = self.chain.invoke(messages, config=self._config)["parsed"]
        except OutputParserException:  # thinking was on and the model answered in prose
            parsed = None
        except Exception as error:  # LangChain wraps provider errors in its own types
            raise ValueError(f"LangChain request failed: {type(error).__name__}") from error
        if parsed is None and self.thinking:
            with self._lock:
                self.fallbacks += 1
            try:
                parsed = self.forced.invoke(messages, config=self._config)["parsed"]
            except Exception as error:
                raise ValueError(f"LangChain request failed: {type(error).__name__}") from error
        return parsed

    def _ask(self, candidate: Candidate, settings: Settings) -> Verdict:
        parsed = self._answer(candidate)
        if parsed is None:
            # Only an answer cut off at the output limit, or a refusal, leaves the schema unfilled.
            raise ValueError(f"{self.model} gave no complete verdict for {candidate.new.qualname}")
        score = min(1.0, max(0.0, parsed.score))
        # The score decides whether the pair is separate, at this run's thresholds; the model's own label only
        # tells duplicate from drifted.
        separate = score < settings.drop_below
        label = "separate" if separate else "drifted" if parsed.label is DuplicationLabel.DRIFTED else "duplicate"
        owner = "" if parsed.owner is ConsolidationOwner.NONE else parsed.owner.value
        why = parsed.reasoning
        if isinstance(parsed, DiagnosedVerdictPromptSchema):
            why += f"\nHard: {parsed.difficulty}\nMissing: {parsed.missing_information}"
        # The schema asks for at most five; the store, report.json and every renderer keep the same five.
        differences = [Difference.model_validate(d.model_dump()) for d in parsed.differences[:MAX_DIFFERENCES]]
        return Verdict(
            label=label, score=score, owner=owner, why=why, judge=self.name, judge_version=self.version,
            differences=differences,
        )  # fmt: skip

    def judge(self, candidates: list[Candidate], settings: Settings) -> list[Verdict]:
        with ThreadPoolExecutor(self.workers) as pool:
            return list(pool.map(lambda candidate: self._ask(candidate, settings), candidates))
