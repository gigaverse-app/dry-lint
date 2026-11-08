"""Immutable source coordinates and recorded judgments; no source code is stored in the sticky ledger."""

from pydantic import BaseModel, Field, ValidationError, field_validator

from dry_lint.function_index import repository_name
from dry_lint.models import Function, Run, Verdict, qualified, validated_repository_path
from dry_lint.report import Finding, source_url


class SourceReference(BaseModel):
    repository: str
    revision: str = Field(pattern=r"^[a-fA-F0-9]{40}$")
    path: str
    name: str
    owner: str | None = None
    line: int = Field(ge=1)
    end_line: int = Field(ge=1)

    _repository = field_validator("repository")(repository_name)

    _path = field_validator("path")(validated_repository_path)

    @classmethod
    def of(cls, function: Function, run: Run) -> "SourceReference":
        origin = function.origin or run
        return cls(
            repository=origin.repository,
            revision=origin.head,
            path=function.path,
            name=function.name,
            owner=function.owner,
            line=function.line,
            end_line=function.end_line,
        )

    @property
    def qualified(self) -> str:
        return qualified(self.owner, self.name)

    def url(self) -> str:
        return source_url(
            Function(path=self.path, name=self.name, owner=self.owner, line=self.line, end_line=self.end_line, code=""),
            Run(repository=self.repository, head=self.revision),
        )


class PairEvidence(BaseModel):
    a: SourceReference
    b: SourceReference
    similarity: float
    verdict: Verdict | None = None
    cached: bool = False

    @classmethod
    def of(cls, finding: Finding, run: Run) -> "PairEvidence | None":
        try:
            return cls(
                a=SourceReference.of(finding.candidate.new, run),
                b=SourceReference.of(finding.candidate.existing, run),
                similarity=finding.candidate.similarity,
                verdict=finding.verdict,
                cached=finding.cached,
            )
        except ValidationError:
            return None
