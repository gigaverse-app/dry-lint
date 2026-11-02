"""Judges decide whether a candidate pair is one concept implemented twice. They run apart from the detector."""

import os
from typing import Protocol

from dry_lint.detector import Candidate
from dry_lint.settings import Settings
from dry_lint.store import Verdict


class Judge(Protocol):
    name: str

    def judge(self, candidates: list[Candidate], settings: Settings) -> list[Verdict]: ...


def label_for(score: float, behaves_differently: float, settings: Settings) -> str:
    if score < settings.drop_below:
        return "separate"
    return "drifted" if behaves_differently >= settings.drift_at else "duplicate"


def make_judge(name: str, command: str | None = None) -> Judge | None:
    """The judge to use: "jev", "command", "none", or "auto" (Jev when TYPESAFE_AI_API_KEY is set, else none)."""
    if name == "auto":
        name = "jev" if os.environ.get("TYPESAFE_AI_API_KEY") else "none"
    if name == "none":
        return None
    if name == "jev":
        from dry_lint.judges.jev import JevJudge

        return JevJudge()
    if name == "command":
        if not command:
            raise ValueError("--judge command needs --judge-command")
        from dry_lint.judges.command import CommandJudge

        return CommandJudge(command)
    raise ValueError(f"Unknown judge: {name}")
