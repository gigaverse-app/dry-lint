"""
The verdict store: one record per pair a judge has decided, so the same question is never asked twice.

It is a cache of machine answers, not a reviewed file: keep it outside the repository (a CI artifact, object
storage, a small table). Losing it only means re-judging. A record is reused when nothing that matters changed:

- both structure hashes match (comments, formatting and renames do not change them); or
- the verdict was "not a duplicate" and the pair is not meaningfully closer than when it was judged, so the
  answer can only have become more true.

A duplicate verdict reopens on any logic change, because that change may be the fix, or more drift.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from dry_lint.detector import Candidate
from dry_lint.functions import BEHAVIOUR_FINGERPRINT_VERSION, structure_hash

Label = Literal["duplicate", "drifted", "separate"]


class Verdict(BaseModel):
    """A judge's answer for one pair."""

    label: Label
    score: float = Field(description="0-1: how sure the judge is that this is one concept with two implementations.")
    behaves_differently: float = Field(default=0.0, description="0-1: whether callers would notice a difference.")
    owner: str = Field(
        default="", description="Which side should own the single implementation: new, existing, shared."
    )
    why: str = ""
    judge: str = Field(description="Judge and prompt version, e.g. 'jev:reuse-v2'.")


class Record(BaseModel):
    """A verdict, with the state of the pair when it was judged."""

    a: str
    b: str
    a_hash: str
    b_hash: str
    similarity_when_judged: float
    similarity_version: str | None = None
    verdict: Verdict
    judged_at: str = Field(default_factory=lambda: datetime.now(UTC).date().isoformat())


def key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


class VerdictStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.records: dict[tuple[str, str], Record] = {}
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    record = Record.model_validate_json(line)
                    self.records[key(record.a, record.b)] = record

    def lookup(self, candidate: Candidate, reopen_margin: float) -> Verdict | None:
        """The stored verdict if it still holds for this pair as it is now, else None (ask the judge)."""
        record = self.records.get(key(candidate.new.qualname, candidate.existing.qualname))
        if record is None:
            return None
        hashes = {record.a: record.a_hash, record.b: record.b_hash}
        now = {
            candidate.new.qualname: structure_hash(candidate.new),
            candidate.existing.qualname: structure_hash(candidate.existing),
        }
        if hashes == now:
            return record.verdict
        # Changed code cannot reuse a distance comparison measured with a different fingerprint.
        if record.similarity_version != BEHAVIOUR_FINGERPRINT_VERSION:
            return None
        not_closer = candidate.similarity <= record.similarity_when_judged + reopen_margin
        if record.verdict.label == "separate" and not_closer:
            return record.verdict
        return None

    def remember(self, candidate: Candidate, verdict: Verdict) -> None:
        a, b = key(candidate.new.qualname, candidate.existing.qualname)
        hashes = {
            candidate.new.qualname: structure_hash(candidate.new),
            candidate.existing.qualname: structure_hash(candidate.existing),
        }
        self.records[(a, b)] = Record(
            a=a,
            b=b,
            a_hash=hashes[a],
            b_hash=hashes[b],
            similarity_when_judged=candidate.similarity,
            similarity_version=BEHAVIOUR_FINGERPRINT_VERSION,
            verdict=verdict,
        )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = (record.model_dump_json() for _, record in sorted(self.records.items()))
        self.path.write_text("\n".join(lines) + ("\n" if self.records else ""))

    def export(self) -> list[dict]:
        return [json.loads(record.model_dump_json()) for record in self.records.values()]
