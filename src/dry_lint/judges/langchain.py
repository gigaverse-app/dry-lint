"""
Claude as a judge through LangChain, answering in a schema instead of free text
(`pip install 'dry-lint[langchain]'`).

    judge = { use = "langchain", model = "claude-haiku-5-5" }        # ANTHROPIC_API_KEY in the environment
    preset = "balanced-structured"                                    # the same judge, with its measured thresholds

It asks the shared-operations question (`OPERATIONS_RULES` in judges/command.py) and gets a
`DuplicateVerdictPromptSchema` back through `with_structured_output`. The schema is prompt text: the model reads
its docstring, its field names, its field descriptions and its enum values, in field order. What was measured
(docs/benchmark.md#structured-answers) is therefore written into it:

- **The reasoning comes first.** With the decision first the model commits before it has compared the two
  functions, and recall on labelled duplicates fell from 87% to 48-58%.
- **Everything is spelled out.** A first schema with bare literals and one-line descriptions lost 4-8% of answers
  to missing fields. This one, with enums, full descriptions and a score rubric, lost none of 1,412.
- **The score has a rubric,** so 0.4 means the same thing in every answer, and the label agrees with it.

Its scores are stricter than the text judge's, so its thresholds are its own (presets.py).

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
from dry_lint.models import Candidate, Verdict
from dry_lint.settings import Settings

SCHEMA_VERSION = "schema-2"
# The question and the two sources, without the text judges' "answer one JSON object" block: here the schema is
# the only statement of the answer's format, and two formats in one request contradict each other.
STRUCTURED_PROMPT = (
    OPERATIONS_RULES
    + "For partial duplication, limit your reasoning to the shared sub-operation; do not claim both whole functions\n"
    "do the same thing. Prefer separate when the source does not establish a useful common operation.\n\n"
    + OPERATIONS_SOURCES
)


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
    score: float = Field(
        description=(
            "Confidence, from 0.0 to 1.0, that one concrete reusable operation is independently implemented in "
            "both functions and is worth sharing. Score the evidence for that operation, not its size or the "
            "amount of code saved. Use this rubric and pick the band your reasoning supports:\n"
            "0.0-0.1: nothing shared beyond names, types, imports, API calls, loop shapes or the business domain.\n"
            "0.2-0.3: a resemblance, but no extractable operation: both already delegate the matching behaviour to "
            "the same helper or owner, or the overlap is generic syntax, an interface, a stub or a "
            "resource-specific template.\n"
            "0.4-0.5: a shared operation is plausible but not established: its contract, ordering, failure "
            "handling or ownership differs or cannot be told from the source shown. Not reported.\n"
            "0.6-0.7: established. You named a concrete operation that both functions implement independently, "
            "with matching steps and contract, and a sensible shared owner or helper with parameters for the "
            "variation. Reported to the author.\n"
            "0.8-0.9: the same operation with the same steps, inputs, outputs and failure handling; any "
            "difference is cosmetic or one clear parameter.\n"
            "1.0: identical or renamed code."
        )
    )
    label: DuplicationLabel = Field(
        description=(
            "Must agree with the score. 'separate' when the score is below 0.6. 'duplicate' when the score is 0.6 "
            "or higher and both implementations give the same outcome on comparable inputs. 'drifted' when the "
            "score is 0.6 or higher and the two implementations of that SAME operation give conflicting outcomes "
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
    ) -> None:
        if max_tokens < 1:
            raise ValueError("The langchain judge needs a positive output limit")
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as error:  # an optional extra
            raise ValueError("The langchain judge needs LangChain: pip install 'dry-lint[langchain]'") from error
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise ValueError("The langchain judge needs ANTHROPIC_API_KEY")
        self.model, self.effort, self.workers, self.max_tokens = model, effort, workers, max_tokens
        self.version = f"{OPERATIONS_VERSION}+{SCHEMA_VERSION}:{model}:{effort or 'default'}"
        if max_tokens != 2048:
            self.version += f":output={max_tokens}"
        options: dict[str, Any] = {"output_config": {"effort": effort}} if effort else {}
        if base_url:
            options["anthropic_api_url"] = base_url
        llm = ChatAnthropic(
            model=model,
            max_tokens=max_tokens,
            anthropic_api_key=key,
            default_request_timeout=timeout,
            max_retries=max_retries,
            **options,
        )
        # The mode is named, not left to LangChain's default: every number in the benchmark is a tool call's.
        self.chain = llm.with_structured_output(
            DuplicateVerdictPromptSchema, method="function_calling", include_raw=True
        )
        self.tokens = {"input": 0, "output": 0}
        self._usage_lock = Lock()

    def input_text(self, candidate: Candidate) -> str:
        """Everything the model reads, for cost estimates and reservations: the question and the schema."""
        return prompt(candidate, template=STRUCTURED_PROMPT) + json.dumps(
            DuplicateVerdictPromptSchema.model_json_schema()
        )

    def _ask(self, candidate: Candidate, settings: Settings) -> Verdict:
        try:
            answer = self.chain.invoke(prompt(candidate, template=STRUCTURED_PROMPT))
        except Exception as error:  # LangChain wraps provider errors in its own types
            raise ValueError(f"LangChain request failed: {type(error).__name__}") from error
        # The usage of this response, as the API returned it; never a difference of shared counters.
        usage = answer["raw"].usage_metadata or {}
        with self._usage_lock:
            self.tokens["input"] += usage.get("input_tokens", 0)
            self.tokens["output"] += usage.get("output_tokens", 0)
        parsed = answer["parsed"]
        if parsed is None:
            # Only an answer cut off at the output limit, or a refusal, leaves the schema unfilled.
            raise ValueError(f"{self.model} gave no complete verdict for {candidate.new.qualname}")
        score = min(1.0, max(0.0, parsed.score))
        # The score decides whether the pair is separate, at this run's thresholds; the model's own label only
        # tells duplicate from drifted.
        separate = score < settings.drop_below
        label = "separate" if separate else "drifted" if parsed.label is DuplicationLabel.DRIFTED else "duplicate"
        owner = "" if parsed.owner is ConsolidationOwner.NONE else parsed.owner.value
        return Verdict(
            label=label, score=score, owner=owner, why=parsed.reasoning, judge=self.name, judge_version=self.version
        )

    def judge(self, candidates: list[Candidate], settings: Settings) -> list[Verdict]:
        with ThreadPoolExecutor(self.workers) as pool:
            return list(pool.map(lambda candidate: self._ask(candidate, settings), candidates))
