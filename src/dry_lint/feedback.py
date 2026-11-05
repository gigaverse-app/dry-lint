"""Reviewed decisions live in a versioned repository file, never in the machine verdict cache."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from dry_lint.models import Candidate, evidence
from dry_lint.store import DirectoryStore

FILENAME = ".dry-lint-feedback.json"


class Decision(BaseModel):
    pair: str
    evidence: str
    action: Literal["dismiss", "fix", "accept"]
    reason: str = Field(min_length=1)
    reviewer: str = Field(min_length=1)
    revision: str
    recorded_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class Feedback(BaseModel):
    schema_version: Literal[1, 2] = Field(default=2, alias="schema")
    decisions: list[Decision] = Field(default_factory=list)

    @classmethod
    def read(cls, path: Path) -> "Feedback":
        return cls.model_validate_json(path.read_bytes()) if path.exists() else cls()

    def apply(self, candidates: list[Candidate]) -> list[Candidate]:
        latest = {d.evidence: d for d in self.decisions}
        dismissed = {key: d for key, d in latest.items() if d.action == "dismiss"}
        return [
            c.model_copy(update={"filtered": f"reviewed dismissal: {dismissed[evidence(c)].reason}"})
            if not c.filtered and evidence(c) in dismissed
            else c
            for c in candidates
        ]

    def accepted(self, candidate: Candidate) -> bool:
        decision = next(
            (d for d in reversed(self.decisions) if d.pair == candidate.key and d.evidence == evidence(candidate)), None
        )
        return decision is not None and decision.action == "accept"

    def write(self, path: Path) -> None:
        DirectoryStore(path.parent).put(path.stem, (self.model_dump_json(indent=2, by_alias=True) + "\n").encode())
