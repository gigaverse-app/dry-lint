"""
Any program as the judge, through a command: one candidate in on stdin, one JSON verdict out on stdout.

    dry-lint check --judge command --judge-command "claude -p --model haiku"

    [tool.dry-lint]
    judge = { use = "command", command = "claude -p --model haiku", version = "haiku-1" }

With `input = "prompt"` (the default) the command gets the DRY prompt below, so any LLM CLI works as is. With
`input = "candidate"` it gets the candidate as one line of JSON (the `Candidate` model, as in candidates.json),
for judges written as programs. Either way it must print one JSON object, and text around it is ignored:
{"label": "duplicate" | "drifted" | "separate", "score": 0-1, "behaves_differently": 0-1,
"owner": "new" | "existing" | "shared" | "", "why": "one sentence"}.
"""

import json
import re
import shlex
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from dry_lint.models import Candidate, Verdict
from dry_lint.settings import Settings

PROMPT = """You review a pull request for duplicated concepts (DRY). Two Python functions from one codebase:
NEW was written or changed in the pull request; EXISTING already exists elsewhere.

Decide whether reconciling them reveals ONE concept with legitimate variations (it should have one implementation,
parameterized where they differ) or TWO different concepts that happen to share structure or APIs.
One concept includes identical copies, renamed copies, independent re-implementations of the same concept, and
variants whose differences should be parameters, even when details differ or have drifted.
Two concepts includes: one calls the other; the client and server ends of one endpoint; an interface or stub and
its implementation; deliberate per-resource instances of one template.

Answer with one JSON object only:
{"label": "duplicate" | "drifted" | "separate", "score": <0-1, your confidence it is one concept>,
 "owner": "new" | "existing" | "shared" | "", "why": "<one concrete sentence>"}
Use "drifted" when it is one concept and the two already give different results a caller would notice.

# NEW: <<new_name>>
<<new_code>>

# EXISTING: <<existing_name>>
<<existing_code>>
"""


PROMPT_VERSION = "dry-v1"  # bump when PROMPT changes meaning, so the store knows its answers changed


def prompt(candidate: Candidate) -> str:
    """The DRY question about one pair, for any judge that answers in text."""
    return (PROMPT.replace("<<new_name>>", candidate.new.qualname).replace("<<new_code>>", candidate.new.code)
            .replace("<<existing_name>>", candidate.existing.qualname).replace("<<existing_code>>", candidate.existing.code))


def parse_verdict(text: str, judge: str, version: str) -> Verdict:
    """The first JSON object with a `label` in a text answer, as a verdict; text and other objects around it are ignored."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            answer, _ = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(answer, dict) and "label" in answer:
            break
    else:
        raise ValueError(f"The judge {judge} answered without a JSON verdict: {text[:200]!r}")
    return Verdict(label=answer["label"], score=float(answer.get("score", 1.0)),
                   behaves_differently=float(answer.get("behaves_differently", 0.0)), owner=answer.get("owner", ""),
                   why=answer.get("why", ""), judge=judge, judge_version=version)


class CommandJudge:
    def __init__(self, command: str = "", input: Literal["prompt", "candidate"] = "prompt", version: str = "1",
                 name: str | None = None, timeout: float = 180, workers: int = 4) -> None:
        if not command:
            raise ValueError("The command judge needs a command (--judge-command, or `command` in its settings)")
        self.command, self.input, self.version, self.timeout, self.workers = command, input, version, timeout, workers
        self.name = name or f"command:{Path(shlex.split(command)[0]).name}"

    def stdin(self, candidate: Candidate) -> str:
        return candidate.model_dump_json() + "\n" if self.input == "candidate" else prompt(candidate)

    def ask(self, candidate: Candidate) -> Verdict:
        out = subprocess.run(shlex.split(self.command), input=self.stdin(candidate), capture_output=True, text=True,
                             timeout=self.timeout, check=True).stdout
        return parse_verdict(out, self.name, self.version)

    def judge(self, candidates: list[Candidate], settings: Settings) -> list[Verdict]:
        """One verdict per candidate, in order; up to `workers` commands run at once."""
        with ThreadPoolExecutor(self.workers) as pool:
            return list(pool.map(self.ask, candidates))
