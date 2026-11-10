"""
Claude as a judge through LangChain, answering in a schema instead of free text
(`pip install 'dry-lint[langchain]'`), with the command judge's DRY prompt.

    judge = { use = "langchain", model = "claude-haiku-5-5" }        # ANTHROPIC_API_KEY in the environment
    preset = "balanced-structured"                                    # the same judge, with its measured thresholds

The answer is a `DuplicateVerdictPromptSchema`, which the provider's constrained decoding guarantees: there is no
JSON to find in prose and none to repair. Two measured choices (docs/benchmark.md#structured-answers) matter:

- **The reason comes first.** With the decision first the model commits before it has compared the two functions,
  and recall on labelled duplicates fell from 87% to 48-58%.
- **The label follows the score.** This judge's scores sit lower than the text judge's and its own label lags
  them, so the label is derived from the score and the settings' thresholds, as Jev's is. Its thresholds are
  therefore its own: 0.3 here means what 0.5 means for the text judge.

LangChain traces prompts, which contain your source, to LangSmith when you set its tracing variables
(`LANGSMITH_TRACING`, `LANGSMITH_API_KEY`). dry-lint never sets them; whether to trace is the adopter's choice.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any, Literal

from pydantic import BaseModel, Field

from dry_lint.judges.command import PROMPT_POLICIES, prompt
from dry_lint.models import Candidate, Verdict
from dry_lint.settings import Settings

SCHEMA_VERSION = "schema-1"


class DuplicateVerdictPromptSchema(BaseModel):
    """The verdict on one NEW/EXISTING pair. Work through `why` before deciding the score."""

    # INVARIANT: `why` stays the first field. Fields are generated in order, and a decision written before the
    # reasoning costs a third of the recall. tests/test_langchain_judge.py locks the order.
    why: str = Field(
        description="Name the shared operation and its contract and variation, or explain why the apparent overlap "
        "is already delegated or semantically distinct."
    )
    label: Literal["duplicate", "drifted", "separate"]
    score: float = Field(description="0-1 confidence in actionable shared behavior")
    owner: Literal["new", "existing", "shared", ""]


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
        prompt_policy: str = "shared-operations",
        max_tokens: int = 2048,
        max_retries: int = 0,
        base_url: str | None = None,
    ) -> None:
        if prompt_policy not in PROMPT_POLICIES or max_tokens < 1:
            raise ValueError("Unknown prompt policy or nonpositive output limit")
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as error:  # an optional extra
            raise ValueError("The langchain judge needs LangChain: pip install 'dry-lint[langchain]'") from error
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise ValueError("The langchain judge needs ANTHROPIC_API_KEY")
        self.model, self.effort, self.workers = model, effort, workers
        self.prompt_policy, self.max_tokens = prompt_policy, max_tokens
        self.version = f"{PROMPT_POLICIES[prompt_policy][0]}+{SCHEMA_VERSION}:{model}:{effort or 'default'}"
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
        # json_schema, not LangChain's default tool call: a forced tool call lost 4-8% of answers to missing fields.
        self.chain = llm.with_structured_output(DuplicateVerdictPromptSchema, method="json_schema", include_raw=True)
        self.tokens = {"input": 0, "output": 0}
        self._usage_lock = Lock()

    def _ask(self, candidate: Candidate, settings: Settings) -> Verdict:
        try:
            answer = self.chain.invoke(prompt(candidate, policy=self.prompt_policy))
        except Exception as error:  # LangChain wraps provider errors in its own types
            raise ValueError(f"LangChain request failed: {type(error).__name__}") from error
        usage = answer["raw"].usage_metadata or {}
        with self._usage_lock:
            self.tokens["input"] += usage.get("input_tokens", 0)
            self.tokens["output"] += usage.get("output_tokens", 0)
        parsed = answer["parsed"]
        if parsed is None:
            # Only an answer cut off at the output limit, or a refusal, leaves the schema unfilled.
            raise ValueError(f"{self.model} gave no complete verdict for {candidate.new.qualname}")
        score = min(1.0, max(0.0, parsed.score))
        # The score decides whether the pair is separate; the model's own label only tells duplicate from drifted.
        label = "separate" if score < settings.drop_below else "drifted" if parsed.label == "drifted" else "duplicate"
        return Verdict(
            label=label, score=score, owner=parsed.owner, why=parsed.why, judge=self.name, judge_version=self.version
        )

    def judge(self, candidates: list[Candidate], settings: Settings) -> list[Verdict]:
        with ThreadPoolExecutor(self.workers) as pool:
            return list(pool.map(lambda candidate: self._ask(candidate, settings), candidates))
