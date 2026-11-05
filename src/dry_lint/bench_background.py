"""Frozen sparse corpora for goldens: preserve IDF and competitors without copying source bodies."""

import hashlib
import sys
from collections import Counter
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dry_lint.function_index import decode_snapshot, encode_snapshot, extraction_contract, repository_name
from dry_lint.index import TfidfIndex
from dry_lint.models import Function
from dry_lint.settings import Choice, Settings

PositiveCount = Annotated[int, Field(strict=True, gt=0)]


class BackgroundDocument(BaseModel):
    """One sparse matrix row; identity and code digest tie it to an immutable source function."""

    model_config = ConfigDict(extra="forbid")
    id: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    counts: dict[str, PositiveCount]

    def tokens(self) -> list[str]:
        return [token for token, count in self.counts.items() for _ in range(count)]


class BenchBackground(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["dry-lint/bench-background"] = "dry-lint/bench-background"
    schema_version: Literal[1] = Field(default=1, alias="schema")
    repository: str
    revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    extraction_contract: str
    python_version: str
    extractors: list[Choice]
    scope: dict[str, list[str]]
    max_df: float = Field(default=0.3, gt=0, le=1)
    document_frequency: dict[str, PositiveCount]
    documents: list[BackgroundDocument]

    @model_validator(mode="after")
    def consistent_frequencies(self) -> Self:
        repository_name(self.repository)
        actual = Counter(token for document in self.documents for token in document.counts)
        if dict(actual) != self.document_frequency:
            raise ValueError("Background document frequencies disagree with sparse rows")
        return self

    @classmethod
    def capture(
        cls, functions: list[Function], repository: str, revision: str, settings: Settings, max_df: float = 0.3
    ) -> Self:
        return cls(
            repository=repository,
            revision=revision,
            extraction_contract=extraction_contract(settings),
            python_version=sys.version.split()[0],
            extractors=settings.extractors,
            scope={"include": settings.include, "exclude": settings.exclude},
            max_df=max_df,
            document_frequency=dict(sorted(Counter(t for f in functions for t in set(f.tokens)).items())),
            documents=[
                BackgroundDocument(
                    id=f.qualname,
                    source_sha256=hashlib.sha256(f.code.encode()).hexdigest(),
                    counts=dict(Counter(f.tokens)),
                )
                for f in functions
            ],
        )

    def index(self) -> TfidfIndex:
        """Replay frozen tokens, without applying today's tokenizer to yesterday's source."""
        return TfidfIndex([document.tokens() for document in self.documents], self.max_df)

    def encode(self) -> bytes:
        return encode_snapshot(self.model_dump(mode="json", by_alias=True), sort_keys=False)

    @classmethod
    def decode(cls, data: bytes) -> Self:
        return cls.model_validate(decode_snapshot(data, "benchmark background"))
