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

SCHEMA = 8
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
    session: str = ""
    revision: str = ""


class Function(BaseModel):
    """One function or method, by the qualified name dry-lint keys everything on. An extractor fills it in."""

    path: str = Field(description="Path relative to the repository root.")
    name: str = Field(description="The function's own name.")
    owner: str | None = Field(default=None, description="Enclosing class, for methods.")
    line: int
    end_line: int
    code: str
    context: str = Field(default="", description="Bounded source dependencies and policy comments; never executed.")
    context_digest: str = Field(
        default="", description="Full source-file digest, including context beyond the prompt limit."
    )
    origin: Run | None = Field(default=None, description="Source checkout for a multi-repository scan.")
    hash: str = Field(
        default="", description="Changes with runtime logic; the language extractor normalizes safe cosmetic edits."
    )
    tokens: list[str] = Field(
        default_factory=list,
        exclude=True,
        description="Behaviour tokens, for comparers that use them. Not written to files.",
    )
    calls: list[str] | None = Field(
        default=None, exclude=True, description="Names the function calls, from its extractor; None if it cannot tell."
    )
    bases: list[str] = Field(
        default_factory=list,
        exclude=True,
        description="Its class's direct bases, as `module::Class` (see `module_of`); not written to files.",
    )

    @property
    def qualname(self) -> str:
        prefix = f"{self.origin.repository}/" if self.origin and self.origin.repository else ""
        return f"{prefix}{self.path}::{qualified(self.owner, self.name)}"

    @property
    def lines(self) -> int:
        return self.end_line - self.line + 1


def qualified(owner: str | None, name: str) -> str:
    """A function's name as reports show it, without its path: `Owner.name`, or `name` outside a class."""
    return f"{owner}.{name}" if owner else name


def module_of(path: str) -> str:
    """A file's module as a base-class reference names it: its path without the extension, a package by its folder."""
    return str(PurePosixPath(path).with_suffix("")).removesuffix("/__init__").removesuffix("/index")


def repository_path(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts and "\\" not in value and ":" not in value


def validated_repository_path(value: str) -> str:
    if not repository_path(value):
        raise ValueError("path must be repository-relative, without '..'")
    return value


class Consolidation(BaseModel):
    """A preferred home for related implementations, not a requirement to merge unrelated concepts."""

    sources: list[str] = Field(default_factory=lambda: ["*"], min_length=1)
    repository: str = ""
    path: str = Field(min_length=1)
    guidance: str = ""

    @field_validator("path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        return validated_repository_path(value).rstrip("/") or "."

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
    comparer: str = Field(
        default="", description="The comparer and version that measured the similarity, e.g. 'tfidf:1'."
    )
    filtered: str | None = Field(
        default=None, description="Why a rule dropped the pair; None when it goes to the judge."
    )
    similarity_reusable: bool = Field(
        default=False, description="Whether this metric permits reuse after logic changes."
    )
    consolidation: list[Consolidation] = Field(default_factory=list)
    lane: Literal["baseline", "exploration", "relative"] = "baseline"
    parent: str = Field(default="", description="For a relative: the key of the pair whose fix would touch `new`.")

    @property
    def context_hash(self) -> str:
        if not (
            self.new.context
            or self.existing.context
            or self.new.context_digest
            or self.existing.context_digest
            or self.consolidation
        ):
            return ""
        payload = [
            sorted((f.qualname, f.context, f.context_digest) for f in (self.new, self.existing)),
            [target.model_dump() for target in self.consolidation],
        ]
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    @property
    def key(self) -> str:
        return pair_key(self.new.qualname, self.existing.qualname)


def evidence(candidate: Candidate, judge_policy: str = "") -> str:
    """Exact source, context and policy identity, independent of which side changed."""
    payload = [
        sorted((f.qualname, f.code) for f in (candidate.new, candidate.existing)),
        candidate.context_hash,
        judge_policy,
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


class Verdict(BaseModel):
    """A judge's answer for one pair."""

    label: Label
    score: float = Field(description="0-1: how sure the judge is that this is one concept with two implementations.")
    behaves_differently: float = Field(default=0.0, description="0-1: whether callers would notice a difference.")
    owner: str = Field(
        default="", description="Which side should own the single implementation: new, existing, shared."
    )
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
