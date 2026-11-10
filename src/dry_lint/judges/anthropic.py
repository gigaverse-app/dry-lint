"""
Claude as a judge, through the official Anthropic SDK (`pip install 'dry-lint[anthropic]'`), with the command
judge's DRY prompt.

    escalate = "anthropic"                                           # ANTHROPIC_API_KEY; claude-sonnet-5-5
    escalate = { use = "anthropic", model = "claude-opus-5-5", effort = "medium" }

Claude Sonnet 5.5 is the measured second judge (docs/benchmark.md). Refusals fall back server-side to another model
(`fallbacks: "default"`); a request that is still declined raises, so the pair keeps the first judge's answer.
For a Claude subscription instead of an API key, use the `claude-code` judge (judges/subscription.py).
"""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any

from dry_lint.judges.command import PROMPT_POLICIES, parse_verdict, prompt
from dry_lint.models import Candidate, Verdict
from dry_lint.settings import Settings

FALLBACK_MODELS = {"claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1"}


class AnthropicJudge:
    name = "anthropic"
    subscription = False

    def __init__(
        self,
        model: str = "claude-sonnet-5-5",
        api_key: str | None = None,
        effort: str | None = None,
        workers: int = 4,
        timeout: float = 120,
        http_client: Any = None,
        prompt_policy: str = "shared-operations",
        max_tokens: int = 8000,
        max_retries: int = 2,
        retry_malformed: bool = False,
    ) -> None:
        if prompt_policy not in PROMPT_POLICIES or max_tokens < 1:
            raise ValueError("Unknown prompt policy or nonpositive output limit")
        try:
            import anthropic
        except ImportError as error:  # an optional extra
            raise ValueError("The anthropic judge needs the SDK: pip install 'dry-lint[anthropic]'") from error
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise ValueError(
                "The anthropic judge needs ANTHROPIC_API_KEY (or use the claude-code judge with a subscription)"
            )
        self.model, self.effort, self.workers = model, effort, workers
        self.prompt_policy, self.max_tokens = prompt_policy, max_tokens
        self.retry_malformed = retry_malformed
        # An opt-in policy cannot inherit legacy answers, nor contaminate a rollback to the legacy judge.
        self.name = "anthropic-operations"
        if prompt_policy == "model-contracts":
            self.name = "anthropic-models"
        self.strict_version = True
        self.version = f"{PROMPT_POLICIES[prompt_policy][0]}:{model}" + (f":{effort}" if effort else "")
        if max_tokens != 8000:
            self.version += f":output={max_tokens}"
        self.client = anthropic.Anthropic(
            api_key=key, timeout=timeout, http_client=http_client, max_retries=max_retries
        )
        self.tokens = {"input": 0, "output": 0}
        # Calls run on several threads at once (here and in the campaign scheduler); counts must not race.
        self._usage_lock = Lock()

    def _ask(self, candidate: Candidate, retry: bool = True) -> Verdict:
        import anthropic

        options: dict[str, Any] = {"output_config": {"effort": self.effort}} if self.effort else {}
        if self.model in FALLBACK_MODELS:
            options |= {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt(candidate, policy=self.prompt_policy)}],
                **options,
            )
        except anthropic.APIError as error:
            raise ValueError(f"Anthropic request failed: {type(error).__name__}") from error
        with self._usage_lock:
            self.tokens["input"] += response.usage.input_tokens
            self.tokens["output"] += response.usage.output_tokens
            for name in ("cache_creation_input_tokens", "cache_read_input_tokens"):
                count = getattr(response.usage, name, 0) or 0
                if count:
                    self.tokens[name] = self.tokens.get(name, 0) + count
        if response.stop_reason == "refusal":
            category = getattr(response.stop_details, "category", None)
            raise ValueError(f"{self.model} declined to judge {candidate.new.qualname} ({category})")
        try:
            return parse_verdict("".join(b.text for b in response.content if b.type == "text"), self.name, self.version)
        except ValueError:
            if not retry or not self.retry_malformed:
                raise
            # Recover one malformed answer without inventing a verdict or discarding a large sweep.
            return self._ask(candidate, retry=False)

    def judge(self, candidates: list[Candidate], settings: Settings) -> list[Verdict]:
        with ThreadPoolExecutor(self.workers) as pool:
            return list(pool.map(self._ask, candidates))
