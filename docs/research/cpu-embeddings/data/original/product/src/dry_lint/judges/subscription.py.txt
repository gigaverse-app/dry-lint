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

import os
import shlex
import subprocess
import tempfile
from pathlib import Path

from dry_lint.judges.command import PROMPT_VERSION, CommandJudge, parse_verdict, prompt
from dry_lint.models import Candidate, Verdict

API_KEY_VARIABLES = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
# Replaces Claude Code's own, so the CLI answers the DRY prompt as the API does (the API call has no system prompt).
SYSTEM_PROMPT = "Answer the question exactly as asked, in the format asked for."


class ClaudeCodeJudge(CommandJudge):
    """Claude through `claude -p`, with every tool off, on the subscription the CLI is logged in with."""

    subscription = True

    def __init__(
        self, model: str = "claude-sonnet-5-5", cli: str = "claude", timeout: float = 300, workers: int = 2
    ) -> None:
        command = (
            f"{cli} -p --model {model} --tools '' --no-session-persistence --disable-slash-commands "
            f"--strict-mcp-config --output-format text --system-prompt {shlex.quote(SYSTEM_PROMPT)}"
        )
        super().__init__(
            command=command, version=f"{PROMPT_VERSION}:{model}", name="claude-code", timeout=timeout, workers=workers
        )
        self.model = model
        # An API key in the environment would bill the API instead of the subscription.
        self.environment = {name: value for name, value in os.environ.items() if name not in API_KEY_VARIABLES}


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
