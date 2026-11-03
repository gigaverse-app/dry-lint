"""
Gemini as a judge, through its REST API: the DRY prompt in, one JSON verdict out. No CLI to install.

    escalate = { use = "gemini", model = "gemini-3.1-pro-preview" }    # GEMINI_API_KEY in the environment

As the escalation judge for first scores in [0.6, 0.91), on the gold set it raised precision at fail_at = 0.8 from
75% to 91% and recall from 59% to 71%, for about one Gemini call every three pull requests (docs/benchmark.md).
"""

import os
from concurrent.futures import ThreadPoolExecutor

import httpx

from dry_lint.judges.command import PROMPT_VERSION, parse_verdict, prompt
from dry_lint.models import Candidate, Verdict
from dry_lint.settings import Settings

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-3.1-pro-preview"


class GeminiJudge:
    name = "gemini"

    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None, workers: int = 4, timeout: float = 120,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not self.api_key:
            raise ValueError("The Gemini judge needs GEMINI_API_KEY")
        self.model, self.workers, self.timeout, self.transport = model, workers, timeout, transport
        self.version = f"{PROMPT_VERSION}:{model}"

    def _ask(self, client: httpx.Client, candidate: Candidate) -> Verdict:
        body = {"contents": [{"parts": [{"text": prompt(candidate)}]}], "generationConfig": {"temperature": 0}}
        response = client.post(API_URL.format(model=self.model), json=body, headers={"x-goog-api-key": self.api_key})
        response.raise_for_status()
        text = "".join(part.get("text", "") for part in response.json()["candidates"][0]["content"]["parts"])
        return parse_verdict(text, self.name, self.version)

    def judge(self, candidates: list[Candidate], settings: Settings) -> list[Verdict]:
        with httpx.Client(timeout=self.timeout, transport=self.transport) as client, ThreadPoolExecutor(self.workers) as pool:
            return list(pool.map(lambda c: self._ask(client, c), candidates))
