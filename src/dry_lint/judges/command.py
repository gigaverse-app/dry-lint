"""
Any LLM as the judge, through a command: the prompt goes to its stdin, a JSON verdict comes back on stdout.

    dry-lint judge candidates.json --judge-command "claude -p --model haiku"

The command must print one JSON object: {"label": "duplicate" | "drifted" | "separate", "score": 0-1,
"owner": "new" | "existing" | "shared" | "", "why": "one sentence"}. Text around the object is ignored.
"""

import json
import re
import shlex
import subprocess

from dry_lint.detector import Candidate
from dry_lint.settings import Settings
from dry_lint.store import Verdict

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


class CommandJudge:
    def __init__(self, command: str, timeout: float = 180) -> None:
        self.command, self.timeout = command, timeout
        self.name = f"command:{shlex.split(command)[0]}"

    def prompt(self, candidate: Candidate) -> str:
        return (PROMPT.replace("<<new_name>>", candidate.new.qualname).replace("<<new_code>>", candidate.new.code)
                .replace("<<existing_name>>", candidate.existing.qualname).replace("<<existing_code>>", candidate.existing.code))

    def judge(self, candidates: list[Candidate], settings: Settings) -> list[Verdict]:
        verdicts = []
        for candidate in candidates:
            out = subprocess.run(shlex.split(self.command), input=self.prompt(candidate), capture_output=True,
                                 text=True, timeout=self.timeout, check=True).stdout
            match = re.search(r"\{.*\}", out, re.S)
            if match is None:
                raise ValueError(f"The judge command printed no JSON verdict: {out[:200]!r}")
            answer = json.loads(match.group(0))
            verdicts.append(Verdict(label=answer["label"], score=float(answer.get("score", 1.0)),
                                    owner=answer.get("owner", ""), why=answer.get("why", ""), judge=self.name))
        return verdicts
