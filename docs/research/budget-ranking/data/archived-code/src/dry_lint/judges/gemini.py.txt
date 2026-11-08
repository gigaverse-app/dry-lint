"""
Gemini as a judge, through its REST API, with the command judge's DRY prompt. No CLI to install.

    escalate = { use = "gemini", model = "gemini-3.1-pro-preview" }    # GEMINI_API_KEY in the environment

As the second judge it tied with Claude Sonnet 5.5 on the gold set, but was slower and less consistent between runs
(docs/benchmark.md). Avoid gemini-2.5-pro: it was the least precise and the least stable.
"""

from dry_lint.judges.http import HttpJudge

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiJudge(HttpJudge):
    name = "gemini"
    key_variable = "GEMINI_API_KEY"
    default_model = "gemini-3.1-pro-preview"

    def request(self, text: str) -> tuple[str, dict, dict]:
        body = {"contents": [{"parts": [{"text": text}]}], "generationConfig": {"temperature": 0}}
        return API_URL.format(model=self.model), {"x-goog-api-key": self.api_key}, body

    def answer(self, body: dict) -> str:
        return "".join(part.get("text", "") for part in body["candidates"][0]["content"]["parts"])
