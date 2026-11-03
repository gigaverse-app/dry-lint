"""
Claude as a judge, through the Messages API, with the command judge's DRY prompt. No CLI to install.

    escalate = "anthropic"                                           # ANTHROPIC_API_KEY; claude-sonnet-5-5
    escalate = { use = "anthropic", model = "claude-opus-5-5" }

Claude Sonnet 5.5 is the default second judge: compared with GPT-5.5, Gemini 3.1 Pro, Gemini 2.5 Pro and Claude
Opus 5.5 on the same gold pairs it was among the most precise, the most consistent between runs, and the fastest
(docs/benchmark.md).
"""

from dry_lint.judges.http import HttpJudge

API_URL = "https://api.anthropic.com/v1/messages"


class AnthropicJudge(HttpJudge):
    name = "anthropic"
    key_variable = "ANTHROPIC_API_KEY"
    default_model = "claude-sonnet-5-5"

    def request(self, text: str) -> tuple[str, dict, dict]:
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        return API_URL, headers, {"model": self.model, "max_tokens": 1024, "messages": [{"role": "user", "content": text}]}

    def answer(self, body: dict) -> str:
        return "".join(block.get("text", "") for block in body["content"] if block.get("type") == "text")
