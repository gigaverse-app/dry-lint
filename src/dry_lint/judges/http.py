"""What every LLM judge behind an HTTP API shares: the DRY prompt in, one JSON verdict out, a few pairs at once."""

import os
from concurrent.futures import ThreadPoolExecutor

import httpx

from dry_lint.judges.command import PROMPT_VERSION, parse_verdict, prompt
from dry_lint.models import Candidate, Verdict
from dry_lint.settings import Settings


class HttpJudge:
    """A judge is `name`, its API key's environment variable, and how to ask and read one answer."""

    name = ""
    key_variable = ""
    default_model = ""

    def __init__(self, model: str = "", api_key: str | None = None, workers: int = 4, timeout: float = 120,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.api_key = api_key or os.environ.get(self.key_variable, "")
        if not self.api_key:
            raise ValueError(f"The {self.name} judge needs {self.key_variable}")
        self.model = model or self.default_model
        self.workers, self.timeout, self.transport = workers, timeout, transport
        self.version = f"{PROMPT_VERSION}:{self.model}"

    def request(self, text: str) -> tuple[str, dict, dict]:
        """The URL, headers and JSON body that ask the model `text`."""
        raise NotImplementedError

    def answer(self, body: dict) -> str:
        """The model's text, from the response body."""
        raise NotImplementedError

    def _ask(self, client: httpx.Client, candidate: Candidate) -> Verdict:
        url, headers, body = self.request(prompt(candidate))
        response = client.post(url, json=body, headers=headers)
        response.raise_for_status()
        return parse_verdict(self.answer(response.json()), self.name, self.version)

    def judge(self, candidates: list[Candidate], settings: Settings) -> list[Verdict]:
        with httpx.Client(timeout=self.timeout, transport=self.transport) as client, ThreadPoolExecutor(self.workers) as pool:
            return list(pool.map(lambda c: self._ask(client, c), candidates))
