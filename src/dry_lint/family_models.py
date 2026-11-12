"""Independent schema-1 family questions; nomination is never a duplicate verdict."""

from typing import TYPE_CHECKING, Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dry_lint.function_index import digest
from dry_lint.operation_families import OperationOwner, OperationRegion

if TYPE_CHECKING:
    from dry_lint.operation_families import FamilyNomination

Text = Annotated[str, Field(min_length=1, max_length=6000)]


class FamilyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True, serialize_by_alias=True)


class FamilyFile(FamilyModel):
    schema_version: Literal[1] = Field(default=1, alias="schema")


class SourceReference(FamilyModel):
    owner_id: Text
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end_line < self.start_line:
            raise ValueError("Source anchor lines must be ordered")
        return self


class SourceAnchor(SourceReference):
    source: str = Field(min_length=1, max_length=32000)


def reference_key(reference: SourceReference) -> tuple[str, int, int]:
    return reference.owner_id, reference.start_line, reference.end_line


def check_reference(reference: SourceReference, member: "FamilyMember") -> None:
    function = member.function
    if (
        reference.owner_id != member.owner_id
        or not function.line <= reference.start_line <= reference.end_line <= function.end_line
    ):
        raise ValueError("Unknown owner or out-of-bounds source anchor")


def check_anchor(anchor: SourceAnchor, member: "FamilyMember") -> None:
    """Bind claims to exact source, not a model's plausible-looking line numbers."""
    check_reference(anchor, member)
    function = member.function
    lines = function.code.splitlines()
    expected = "\n".join(lines[anchor.start_line - function.line : anchor.end_line - function.line + 1])
    if anchor.source != expected:
        raise ValueError("Source anchor does not exactly match owner source")


class FamilyMember(OperationOwner):
    """A nominated owner plus the complete-line highlights the judge must quote, within bounded source."""

    model_config = FamilyModel.model_config
    owner_id: Text
    source_id: str = ""
    regions: list[OperationRegion] = Field(default_factory=list, max_length=16)
    local_callers: list[str] = Field(default_factory=list)
    operations: list[SourceAnchor] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def grounded(self) -> Self:
        function = self.function
        if function.line < 1 or function.lines != len(function.code.splitlines()):
            raise ValueError("Full owner source must have exact line coordinates")
        if not function.code.strip() or len(function.code.encode()) > 32_000:
            raise ValueError("Owner source exceeds the bounded full-function contract")
        if len(function.context.encode()) > 16_000:
            raise ValueError("Owner helper/delegate context exceeds the bounded contract")
        for anchor in self.operations:
            check_anchor(anchor, self)
        for region in self.regions:
            region.check(function)
            if not any(
                a.start_line == region.span.line and a.end_line == region.span.end_line for a in self.operations
            ):
                raise ValueError("Every exact operation slice needs its complete-line highlight")
        return self


class FamilyRequest(FamilyFile):
    nomination_version: Text
    nomination_id: str = ""
    operation_id: str = ""
    canonical_operation: str = ""
    members: list[FamilyMember] = Field(min_length=2, max_length=12)

    @model_validator(mode="after")
    def independent(self) -> Self:
        ids = [member.owner_id for member in self.members]
        names = [member.function.qualname for member in self.members]
        if len(set(ids)) != len(ids) or len(set(names)) != len(names):
            raise ValueError("Family members must have unique IDs and independent native owners")
        if len(self.model_dump_json().encode()) > 1_048_576:
            raise ValueError("Family question exceeds the bounded full-source contract")
        return self

    @property
    def key(self) -> str:
        """Order and every source/context/operation field participate, including rejected siblings."""
        return digest(self.model_dump(mode="json"))


def request_from_nomination(
    nomination: "FamilyNomination", *, nomination_version: str = "python-operation-families:1"
) -> FamilyRequest:
    """Keep exact AST slices AND deliberate complete-line highlights; never infer owner positivity."""
    members = []
    for owner in nomination.owners:
        lines = owner.function.code.splitlines()
        highlights = [
            SourceAnchor(
                owner_id=owner.owner_id,
                start_line=region.span.line,
                end_line=region.span.end_line,
                source="\n".join(
                    lines[region.span.line - owner.function.line : region.span.end_line - owner.function.line + 1]
                ),
            )
            for region in owner.regions
        ]
        members.append(
            FamilyMember(
                owner_id=owner.owner_id,
                source_id=owner.source_id,
                function=owner.function,
                operations=highlights,
                regions=[region.model_copy(deep=True) for region in owner.regions],
                local_callers=owner.local_callers,
            )
        )
    return FamilyRequest(
        nomination_version=nomination_version,
        nomination_id=nomination.nomination_id,
        operation_id=nomination.operation_id,
        canonical_operation=nomination.canonical_operation,
        members=members,
    )


class BoundClaim(FamilyModel):
    text: Text
    evidence: list[SourceReference] = Field(min_length=1, max_length=24)


class MemberAssessment(FamilyModel):
    owner_id: Text
    status: Literal["confirmed", "rejected", "unknown"]
    reason: Text
    anchors: list[SourceAnchor] = Field(default_factory=list, max_length=16)
    caller_differences: BoundClaim | None = None
    ordering: BoundClaim | None = None
    exceptions: BoundClaim | None = None
    existing_reuse: BoundClaim | None = None
    migration: BoundClaim | None = None

    @model_validator(mode="after")
    def complete(self) -> Self:
        details = (self.caller_differences, self.ordering, self.exceptions, self.existing_reuse, self.migration)
        if self.status == "confirmed" and (not self.anchors or any(detail is None for detail in details)):
            raise ValueError(
                "Confirmed members need exact regions and caller differences/ordering/exceptions/reuse/migration"
            )
        if self.status != "confirmed" and (self.anchors or any(detail is not None for detail in details)):
            raise ValueError("Unconfirmed members cannot carry confirmed extraction claims")
        return self


class HelperInterface(FamilyModel):
    signature: BoundClaim
    inputs: BoundClaim
    outputs: BoundClaim
    side_effects: BoundClaim


class CommonOperation(FamilyModel):
    operation: BoundClaim
    shared_contract: BoundClaim
    helper: HelperInterface


class FamilyAnswer(FamilyFile):
    # A judge's validated family verdict, not adopter configuration declaring deliberate look-alikes.
    decision: Literal["consolidate", "separate", "unknown"]
    reason: Text
    members: list[MemberAssessment] = Field(min_length=2, max_length=12)
    common: CommonOperation | None = None

    @model_validator(mode="after")
    def affirmative_evidence(self) -> Self:
        confirmed = [m for m in self.members if m.status == "confirmed"]
        if self.decision == "consolidate":
            if len(confirmed) < 2 or self.common is None:
                raise ValueError("Consolidation needs at least two explicitly confirmed owners and a common contract")
        elif confirmed or self.common is not None:
            raise ValueError("An unconfirmed answer cannot establish a common operation")
        return self


def validate_answer(request: FamilyRequest, answer: FamilyAnswer) -> FamilyAnswer:
    """Mechanical grounding only: this does not independently establish semantic correctness or pair golds."""
    owners = {member.owner_id: member for member in request.members}
    ids = [member.owner_id for member in answer.members]
    if len(ids) != len(set(ids)) or set(ids) != set(owners):
        raise ValueError("Answer must classify every requested owner exactly once, without unknown IDs")
    confirmed = {member.owner_id for member in answer.members if member.status == "confirmed"}

    def claim(value: BoundClaim, allowed: set[str], *, cover: bool = False) -> None:
        cited = {anchor.owner_id for anchor in value.evidence}
        if not cited <= allowed or cover and cited != allowed:
            raise ValueError("Unbound claim: evidence must cite its owners")
        for anchor in value.evidence:
            check_reference(anchor, owners[anchor.owner_id])

    for member in answer.members:
        native = owners[member.owner_id]
        for anchor in member.anchors:
            check_anchor(anchor, native)
            if anchor not in native.operations:
                raise ValueError("Confirmed regions must match complete nominated operation spans")
        for detail in (
            member.caller_differences,
            member.ordering,
            member.exceptions,
            member.existing_reuse,
            member.migration,
        ):
            if detail is not None:
                claim(detail, {member.owner_id})
    if answer.common is not None:
        for value in (answer.common.operation, answer.common.shared_contract):
            claim(value, confirmed, cover=True)
            for anchor in value.evidence:
                assessed = next(member for member in answer.members if member.owner_id == anchor.owner_id)
                if reference_key(anchor) not in {reference_key(a) for a in assessed.anchors}:
                    raise ValueError("Common operation/contract must bind to each confirmed complete region")
        for value in (
            answer.common.helper.signature,
            answer.common.helper.inputs,
            answer.common.helper.outputs,
            answer.common.helper.side_effects,
        ):
            claim(value, confirmed, cover=True)
    return answer


class FamilyUsage(FamilyModel):
    input: int = Field(ge=0, strict=True)
    output: int = Field(ge=0, strict=True)
    cache_creation_input_tokens: int = Field(default=0, ge=0, strict=True)
    cache_read_input_tokens: int = Field(default=0, ge=0, strict=True)


class FamilyResponse(FamilyFile):
    text: str
    usage: FamilyUsage | None = None
    stop_reason: str
    response_id: str = ""
    model: str = ""


class FamilyRecord(FamilyFile):
    key: str
    request_key: str
    judge: str
    judge_version: str
    answer: FamilyAnswer
    response: FamilyResponse
    actual_usd: float | None = Field(default=None, ge=0)
