"""
The records dry-lint passes between its steps, and between its two CI jobs. Their JSON form is the file format:

- `candidates.json`, written by `dry-lint detect`: the run, and every pair the comparer proposed;
- one verdict record per pair in the store (store.py);
- `report.json`, written by `dry-lint judge` or `check`: what every reporter renders (report.py).

Each file carries `schema`. Bump it, and keep reading the old one, whenever a field changes meaning.
"""

import hashlib
import json
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA = 4
Label = Literal["duplicate", "drifted", "separate"]


class Versioned(BaseModel):
    """A top-level file: serialized with its `schema` number."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    schema_version: int = Field(default=SCHEMA, alias="schema")


class Run(BaseModel):
    """Where analyzed code came from, so reports link to the right repository and commit."""

    repository: str = ""
    pull_request: int | None = None
    head: str = ""
    base: str = ""


class Function(BaseModel):
    """One function or method, by the qualified name dry-lint keys everything on. An extractor fills it in."""

    path: str = Field(description="Path relative to the repository root.")
    name: str = Field(description="The function's own name.")
    owner: str | None = Field(default=None, description="Enclosing class, for methods.")
    line: int
    end_line: int
    code: str
    context: str = Field(default="", description="Bounded source dependencies and policy comments; never executed.")
    origin: Run | None = Field(default=None, description="Source checkout for a multi-repository scan.")
    hash: str = Field(default="", description="Changes with runtime logic; the language extractor normalizes safe cosmetic edits.")
    tokens: list[str] = Field(default_factory=list, exclude=True,
                              description="Behaviour tokens, for comparers that use them. Not written to files.")
    calls: list[str] | None = Field(default=None, exclude=True,
                                    description="Names the function calls, from its extractor; None if it cannot tell.")

    @property
    def qualname(self) -> str:
        prefix = f"{self.origin.repository}/" if self.origin and self.origin.repository else ""
        return f"{prefix}{self.path}::{self.owner + '.' if self.owner else ''}{self.name}"

    @property
    def lines(self) -> int:
        return self.end_line - self.line + 1


class Consolidation(BaseModel):
    """A preferred home for related implementations, not a requirement to merge unrelated concepts."""

    sources: list[str] = Field(default_factory=lambda: ["*"], min_length=1)
    repository: str = ""
    path: str = Field(min_length=1)
    guidance: str = ""

    @field_validator("path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        if PurePosixPath(value).is_absolute() or ".." in PurePosixPath(value).parts or "\\" in value or ":" in value:
            raise ValueError("consolidation path must be repository-relative, without '..'")
        return value.rstrip("/") or "."

    @property
    def destination(self) -> str:
        return "/".join(part for part in (self.repository, self.path) if part)


def pair_key(a: str, b: str) -> str:
    """A pair's key in the store, the same whichever side changed."""
    first, second = sorted((a, b))
    return hashlib.sha256(f"{first}\n{second}".encode()).hexdigest()[:16]


class Candidate(BaseModel):
    """A changed function and an existing one elsewhere that looks like it does the same job."""

    new: Function
    existing: Function
    similarity: float
    comparer: str = Field(default="", description="The comparer and version that measured the similarity, e.g. 'tfidf:1'.")
    filtered: str | None = Field(default=None, description="Why a rule dropped the pair; None when it goes to the judge.")
    similarity_reusable: bool = Field(default=False, description="Whether this metric permits reuse after logic changes.")
    consolidation: list[Consolidation] = Field(default_factory=list)

    @property
    def context_hash(self) -> str:
        if not (self.new.context or self.existing.context or self.consolidation):
            return ""
        payload = [sorted((f.qualname, f.context) for f in (self.new, self.existing)),
                   [target.model_dump() for target in self.consolidation]]
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    @property
    def key(self) -> str:
        return pair_key(self.new.qualname, self.existing.qualname)


class Verdict(BaseModel):
    """A judge's answer for one pair."""

    label: Label
    score: float = Field(description="0-1: how sure the judge is that this is one concept with two implementations.")
    behaves_differently: float = Field(default=0.0, description="0-1: whether callers would notice a difference.")
    owner: str = Field(default="", description="Which side should own the single implementation: new, existing, shared.")
    why: str = ""
    judge: str = Field(description="The judge's name, e.g. 'jev' or 'command:claude'.")
    judge_version: str = Field(default="", description="Its model and prompt version, e.g. 'reuse-v2'.")
    second_opinion: str | None = Field(default=None, description="The escalation judge whose answer this is, if any.")


class CandidatesFile(Versioned):
    """`candidates.json`: what the detect job hands to the judge job."""

    run: Run = Field(default_factory=Run)
    changed: int = Field(default=0, description="How many functions the change touched.")
    functions: int = Field(default=0, description="How many functions the repository has: what changed ones meet.")
    candidates: list[Candidate] = Field(default_factory=list, description="Proposed pairs, and filtered ones with why.")
