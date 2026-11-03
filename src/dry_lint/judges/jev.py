"""
Jev (TypeSafe's System One decision model) as the judge: three typed questions per pair, about 0.3 s each.

Prompt `reuse-v2`, code only. Measured on a 250-pair gold set drawn from 2,012 candidates in 600 gigaverse-ai pull
requests, labelled by three vendors' models (docs/benchmark.md): AUC 0.97; at score >= 0.8, 94% precision and 73%
recall. Adding call
counts and the family of look-alikes to the state did not help, so the state is just the two functions.
The benchmark numbers belong to this exact wording: change it and re-measure.
"""

import os
from concurrent.futures import ThreadPoolExecutor

import httpx

from dry_lint.judges import label_for
from dry_lint.models import Candidate, Verdict
from dry_lint.settings import Settings

PROMPT_VERSION = "reuse-v2"
API_URL = "https://api.typesafe.ai/v1/systemone"
CODE_LIMIT = 3000

QUESTIONS = {
    "same_concept": {
        "type": "noul",
        "instructions": (
            "new_function was written or changed in a pull request; existing_function already exists elsewhere in the "
            "codebase. Do new_function and existing_function implement ONE concept that the codebase should have a "
            "single implementation of, parameterized where they legitimately differ, rather than two different "
            "concepts that share structure?"
        ),
        "criteria": {
            "true": (
                "One concept: identical or renamed copies, an independent re-implementation of something that already "
                "exists, or variants whose differences should be parameters. Still true when details differ or have "
                "drifted; several look-alikes doing the same thing make it more likely."
            ),
            "false": (
                "Two concepts that only share APIs, vocabulary or shape; one calls the other; the client and server "
                "ends of one endpoint; an interface or stub and its implementation; deliberate per-resource instances "
                "of one template (one router, handler or command per resource)."
            ),
        },
    },
    "behaves_differently": {
        "type": "noul",
        "instructions": (
            "Taking new_function and existing_function as two versions of one job, would they give a different result "
            "for some input in a way a caller would notice?"
        ),
        "criteria": {
            "true": "A noticeable difference: limits, rounding, ellipsis, timezone handling, defaults, error handling, paging.",
            "false": "Same results for the inputs they share, or they do different jobs.",
        },
    },
    "owner": {
        "type": "choice",
        "instructions": "If these should become one implementation, which should own it?",
        "criteria": {
            "existing": "existing_function: it is established (more call sites or a shared module); new_function should call it",
            "new": "new_function: it is the better or more widely used home; existing_function should call it",
            "shared": "neither: a new shared helper, usually in common, should own it and both should call it",
            "none": "they should stay separate",
        },
    },
}


def state(candidate: Candidate) -> dict:
    def side(function) -> dict:
        module = function.path.removesuffix(".py").replace("/", ".")
        return {"name": function.qualname.split("::")[1], "module": module, "code": function.code[:CODE_LIMIT]}

    return {"new_function": side(candidate.new), "existing_function": side(candidate.existing)}


class JevJudge:
    name = "jev"
    version = PROMPT_VERSION

    def __init__(self, api_key: str | None = None, model: str = "jev-latest", url: str = API_URL, workers: int = 8,
                 transport: httpx.BaseTransport | None = None):
        self.api_key = api_key or os.environ.get("TYPESAFE_AI_API_KEY", "")
        if not self.api_key:
            raise ValueError("The Jev judge needs TYPESAFE_AI_API_KEY")
        self.model, self.url, self.workers, self.transport = model, url, workers, transport

    def _ask(self, client: httpx.Client, candidate: Candidate, settings: Settings) -> Verdict:
        body = {"model": self.model, "state": state(candidate), "questions": QUESTIONS}
        response = client.post(self.url, json=body, headers={"Authorization": f"Bearer {self.api_key}"})
        response.raise_for_status()
        answers = response.json()["answers"]
        same = float(answers["same_concept"]["noul"])
        differs = float(answers["behaves_differently"]["noul"])
        owner = answers["owner"]
        score = same * (1 - float(owner.get("probabilities", {}).get("none", 0.0)))
        return Verdict(label=label_for(score, differs, settings), score=round(score, 3),
                       behaves_differently=round(differs, 3), owner=owner.get("choice", ""), judge=self.name,
                       judge_version=self.version)

    def judge(self, candidates: list[Candidate], settings: Settings) -> list[Verdict]:
        with httpx.Client(timeout=30, transport=self.transport) as client, ThreadPoolExecutor(self.workers) as pool:
            return list(pool.map(lambda c: self._ask(client, c, settings), candidates))
