"""
Judges that run on a subscription instead of an API key, through the vendor's own CLI.

    escalate = "claude-code"                     # a Claude Pro, Max or Team subscription: `claude` CLI, logged in
    escalate = { use = "codex", model = "" }      # a ChatGPT subscription: `codex` CLI, logged in

A call through a subscription uses the same model as the API, so it is counted against `budget.usd` at that model's
list price; subscriptions are rate-limited too, so each run also asks them at most `budget.subscription_calls`
times. If the CLI fails (an expired login, a limit reached), the pairs keep the first judge's answer and are asked
again on the next run. In CI, log the CLI in with a token:
`claude setup-token` makes a long-lived CLAUDE_CODE_OAUTH_TOKEN for the `claude-code` judge.
"""

import json
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from dry_lint.family_models import FamilyRequest, FamilyResponse, FamilyUsage
from dry_lint.judges.anthropic_family import MAX_INPUT_BYTES, FamilyPromptJudge
from dry_lint.judges.command import PROMPT_VERSION, CommandJudge, parse_verdict, prompt
from dry_lint.models import Candidate, Verdict

API_KEY_VARIABLES = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
# Replaces Claude Code's own, so the CLI answers the DRY prompt as the API does (the API call has no system prompt).
SYSTEM_PROMPT = "Answer the question exactly as asked, in the format asked for."


def claude_command(cli: str, model: str, output_format: str) -> str:
    """`claude -p` with every tool, session, slash command and MCP server off."""
    return (
        f"{cli} -p --model {model} --tools '' --no-session-persistence --disable-slash-commands "
        f"--strict-mcp-config --output-format {output_format} --system-prompt {shlex.quote(SYSTEM_PROMPT)}"
    )


def subscription_environment() -> dict[str, str]:
    """dry-lint's environment without API keys: one would bill the API instead of the subscription."""
    return {name: value for name, value in os.environ.items() if name not in API_KEY_VARIABLES}


class ClaudeCodeJudge(CommandJudge):
    """Claude through `claude -p`, with every tool off, on the subscription the CLI is logged in with."""

    subscription = True

    def __init__(
        self, model: str = "claude-sonnet-5-5", cli: str = "claude", timeout: float = 300, workers: int = 2
    ) -> None:
        super().__init__(
            command=claude_command(cli, model, "text"),
            version=f"{PROMPT_VERSION}:{model}",
            name="claude-code",
            timeout=timeout,
            workers=workers,
        )
        self.model = model
        self.environment = subscription_environment()


class ClaudeCodeFamilyJudge(FamilyPromptJudge):
    """Operation-family questions through `claude -p` on the subscription the CLI is logged in with.

    The paid prompt is the same `family_prompt` the API judge sends; one call, no retries. In CI, log the CLI in
    with CLAUDE_CODE_OAUTH_TOKEN. The CLI reports its stop reason and token usage, so admission settles exactly
    as it does for the API judge.
    """

    name = "claude-code-family"
    subscription = True

    def __init__(
        self,
        model: str = "claude-sonnet-5-5",
        cli: str = "claude",
        max_tokens: int = 8192,
        max_input_bytes: int = MAX_INPUT_BYTES,
        timeout: float = 600,
    ) -> None:
        super().__init__(model, max_tokens, max_input_bytes, timeout, transport="claude-code")
        self.command = claude_command(cli, model, "json")
        self.available = shutil.which(shlex.split(cli)[0]) is not None

    def judge_family(self, request: FamilyRequest) -> FamilyResponse:
        environment = {**subscription_environment(), "CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(self.max_tokens)}
        out = subprocess.run(
            shlex.split(self.command),
            input=self.input_text(request),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=self.timeout,
            env=environment,
            check=True,
        )
        result = json.loads(out.stdout)
        if result.get("is_error"):
            raise RuntimeError(f"claude CLI did not answer: {result.get('terminal_reason') or result.get('subtype')}")
        usage = result.get("usage") or {}
        return FamilyResponse(
            text=result.get("result") or "",
            usage=FamilyUsage(
                input=usage.get("input_tokens", 0),
                output=usage.get("output_tokens", 0),
                cache_creation_input_tokens=usage.get("cache_creation_input_tokens", 0),
                cache_read_input_tokens=usage.get("cache_read_input_tokens", 0),
            )
            if "input_tokens" in usage
            else None,
            stop_reason=result.get("stop_reason") or "unknown",
            response_id=result.get("session_id") or "",
            model=self.model,
        )


class CodexJudge(CommandJudge):
    """GPT through `codex exec` in a read-only sandbox, in an empty folder, on the ChatGPT subscription it is logged in with."""

    subscription = True

    def __init__(self, model: str = "", cli: str = "codex", timeout: float = 300, workers: int = 2) -> None:
        flags = f" -m {model}" if model else ""
        super().__init__(
            command=f"{cli} exec{flags} --sandbox read-only --skip-git-repo-check --ephemeral",
            version=f"{PROMPT_VERSION}:{model or 'account-default'}",
            name="codex",
            timeout=timeout,
            workers=workers,
        )
        self.model = model

    def ask(self, candidate: Candidate) -> Verdict:
        with tempfile.TemporaryDirectory() as folder:
            answer = Path(folder) / "answer.txt"
            subprocess.run(
                [*shlex.split(self.command), "-o", str(answer), "-"],
                input=prompt(candidate),
                cwd=folder,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=True,
            )
            return parse_verdict(answer.read_text(), self.name, self.version)
