"""Exact, bounded Python operation-family nominations; no verdicts or model calls.

One operation identity owns every member. Similar pairs are never connected into
families. The independent batch schema is a seam for family judges and reporters,
not an extension of pair scores or of the verdict reuse contract.
"""

import ast
import hashlib
import json
import symtable
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from dry_lint.functions import _parse, docstring_statement
from dry_lint.models import Function, Run
from dry_lint.operation_blocks import _NESTED, statement_regions

GENERATOR = "python-operation-families:1"
_SCOPES = (*_NESTED, ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_STRICT = ConfigDict(extra="forbid", allow_inf_nan=False)


class FamilyLimits(BaseModel):
    """Resource ceilings, not evidence that a nomination is a useful extraction."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    max_functions: int = Field(default=100_000, ge=1)
    max_function_bytes: int = Field(default=256 * 1024, ge=1)
    max_source_bytes: int = Field(default=128 * 1024 * 1024, ge=1)
    max_function_nodes: int = Field(default=30_000, ge=1)
    max_region_nodes: int = Field(default=512, ge=1)
    max_region_bytes: int = Field(default=16 * 1024, ge=1)
    max_regions_per_function: int = Field(default=256, ge=1)
    max_regions: int = Field(default=250_000, ge=1)
    max_operation_ids: int = Field(default=100_000, ge=1)
    max_owners: int = Field(default=32, ge=3)
    max_sites_per_owner: int = Field(default=16, ge=1)
    max_callers: int = Field(default=64, ge=1)
    max_candidates: int = Field(default=2048, ge=1)
    max_output_source_bytes: int = Field(default=32 * 1024 * 1024, ge=1)


class SourceSpan(BaseModel):
    """Absolute lines and zero-based UTF-8 byte columns; end is exclusive."""

    model_config = _STRICT
    line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    column: int = Field(ge=0)
    end_column: int = Field(ge=0)


class OperationRegion(BaseModel):
    """One exact operation site. Family questions carry these same records and re-check them against source."""

    model_config = _STRICT
    span: SourceSpan
    code: str = Field(min_length=1, max_length=32000)
    kind: str = Field(min_length=1, max_length=6000)
    statements: int = Field(ge=1)
    bindings: dict[str, str] = Field(default_factory=dict)
    enclosing: list[SourceSpan] = Field(default_factory=list)

    def check(self, function: Function) -> None:
        span = self.span
        if not function.line <= span.line <= span.end_line <= function.end_line:
            raise ValueError("Operation slice lies outside its owner")
        lines = function.code.splitlines(keepends=True)
        selected = [
            line.encode("utf-8") for line in lines[span.line - function.line : span.end_line - function.line + 1]
        ]
        if span.column > len(selected[0]) or span.end_column > len(selected[-1]):
            raise ValueError("Operation byte columns lie outside source")
        selected[-1] = selected[-1][: span.end_column]
        selected[0] = selected[0][span.column :]
        if b"".join(selected).decode("utf-8") != self.code:
            raise ValueError("Operation slice does not match exact UTF8 source columns")


class OperationOwner(BaseModel):
    model_config = _STRICT
    owner_id: str
    source_id: str
    function: Function
    regions: list[OperationRegion]
    local_callers: list[str]


class FamilyBenefit(BaseModel):
    repeated_statements: int
    replacement_statements: int
    shared_statements: int
    shared_owner_overhead: int
    removable_statements: int


class FamilyNomination(BaseModel):
    operation_id: str
    nomination_id: str
    status: Literal["unconfirmed"] = "unconfirmed"
    canonical_operation: str
    owners: list[OperationOwner] = Field(min_length=3)
    benefit: FamilyBenefit


class FamilyStats(BaseModel):
    input_functions: int = 0
    scanned_functions: int = 0
    source_bytes: int = 0
    examined_regions: int = 0
    indexed_regions: int = 0
    operation_ids: int = 0
    eligible_families: int = 0
    nominated_families: int = 0
    nominated_owners: int = 0
    nominated_sites: int = 0
    output_source_bytes: int = 0
    skipped: dict[str, int] = Field(default_factory=dict)


class FamilyBatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)
    schema_version: Literal[1] = Field(default=1, alias="schema")
    generator: Literal["python-operation-families:1"] = GENERATOR
    run: Run = Field(default_factory=Run)
    limits: FamilyLimits
    nominations: list[FamilyNomination]
    stats: FamilyStats


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _canonical(statements: list[ast.stmt], locals_: set[str]) -> tuple[str, dict[str, str]]:
    """Names are alpha slots only when the Python symbol table proves them local.

    Imported/global/nonlocal names, attributes, keyword names, literals (including
    their types), and all control/operator nodes remain exact. Scoped expressions
    are excluded by the caller: an outer local must never alias a comprehension's
    shadowing binding. Full function context still decides extraction suitability.
    """
    slots: dict[str, str] = {}

    def name(value: str) -> str | dict[str, str]:
        if value not in locals_:
            return value
        return {"local": slots.setdefault(value, f"v{len(slots)}")}

    def encode(value):
        if isinstance(value, ast.AST):
            fields = []
            for key, child in ast.iter_fields(value):
                if (
                    (isinstance(value, ast.Name) and key == "id")
                    or (isinstance(value, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and key == "name")
                    or (isinstance(value, ast.MatchMapping) and key == "rest")
                ):
                    encoded = name(child) if child is not None else None
                else:
                    encoded = encode(child)
                fields.append([key, encoded])
            return [type(value).__name__, fields]
        if isinstance(value, list):
            return [encode(item) for item in value]
        # repr is unambiguous for Python AST constants, including bytes/complex,
        # and keeps 1, 1.0 and True distinct (JSON equality alone would not).
        return [type(value).__name__, repr(value)]

    return json.dumps(encode(statements), separators=(",", ":")), {slot: original for original, slot in slots.items()}


def _span(first: ast.AST, last: ast.AST, function: Function, indent: int) -> SourceSpan:
    return SourceSpan(
        line=function.line + first.lineno - 1,
        end_line=function.line + last.end_lineno - 1,
        column=first.col_offset + indent,
        end_column=last.end_col_offset + indent,
    )


def _slice(lines: list[bytes], span: SourceSpan, line: int) -> str:
    start, end = span.line - line, span.end_line - line
    if start == end:
        return lines[start][span.column : span.end_column].decode()
    return b"".join([lines[start][span.column :], *lines[start + 1 : end], lines[end][: span.end_column]]).decode()


def _overlaps(a: SourceSpan, b: SourceSpan) -> bool:
    return (a.line, a.column) < (b.end_line, b.end_column) and (b.line, b.column) < (a.end_line, a.end_column)


def _source_file(function: Function) -> tuple[str, str, str]:
    # One physical file at one revision, so two aliases of a site never count as two owners. Unlike a validated
    # SourceReference, it names no function and accepts unpinned (empty) origins.
    # dry-lint: distinct-from src/dry_lint/evidence.py::SourceReference.of
    origin = function.origin or Run()
    return origin.repository, origin.head, function.path


def _benefit(owners: list[OperationOwner]) -> FamilyBenefit:
    regions = [region for owner in owners for region in owner.regions]
    repeated = sum(region.statements for region in regions)
    shared = regions[0].statements
    return FamilyBenefit(
        repeated_statements=repeated,
        replacement_statements=len(regions),
        shared_statements=shared,
        shared_owner_overhead=1,
        removable_statements=repeated - len(regions) - shared - 1,
    )


@dataclass
class _Group:
    canonical: str
    owners: dict[str, list[OperationRegion]]


class PythonOperationFamilies:
    """Stateless exact-region generator, callable on the complete native inventory.

    Bounds drop complete evidence, never trim it into an apparent match. Sorted
    source identity establishes deterministic admission, independent of input order.
    Returned models are snapshots; callers can judge/report one family per request.
    """

    def __init__(self, limits: FamilyLimits | None = None) -> None:
        self.limits = limits or FamilyLimits()

    def nominate(
        self, functions: list[Function], *, run: Run | None = None, changed: set[str] | None = None
    ) -> FamilyBatch:
        limits = self.limits
        run = run or Run()
        # Bind root-native source to the caller's immutable run. Every repository
        # has one revision in a batch, including owners outside the changed set.
        # Reject mixed pins before any resource limit can hide the conflict.
        pins = {run.repository: run.head} if run.repository or run.head else {}
        native = []
        changed_ids: set[str] | None = set() if changed is not None else None
        for function in functions:
            original_id = function.qualname
            origin = function.origin or run
            repository = origin.repository or run.repository
            head = origin.head or (run.head if repository == run.repository else "")
            if repository in pins and pins[repository] != head:
                raise ValueError(f"mixed source revisions for repository {repository!r}")
            pins[repository] = head
            if repository or head:
                origin = origin.model_copy(update={"repository": repository, "head": head})
                if function.origin != origin:
                    function = function.model_copy(update={"origin": origin})
            native.append(function)
            if changed_ids is not None and (original_id in changed or function.qualname in changed):
                changed_ids.add(function.qualname)
        stats = FamilyStats(input_functions=len(functions))
        skipped: Counter[str] = Counter()
        # Duplicate inventory entries cannot manufacture independent owners. Conflicting
        # definitions of one identity are ambiguous and are all omitted, regardless of order.
        inventory: dict[str, Function] = {}
        ambiguous: set[str] = set()
        for function in native:
            key = function.qualname
            if key in inventory:
                if function != inventory[key]:
                    ambiguous.add(key)
                skipped["duplicate_owner"] += 1
            else:
                inventory[key] = function
        for key in ambiguous:
            del inventory[key]
        skipped["ambiguous_owner"] = len(ambiguous)
        keys = sorted(inventory)
        skipped["function_limit"] = max(0, len(keys) - limits.max_functions)
        selected = {key: inventory[key] for key in keys[: limits.max_functions]}
        groups: dict[str, _Group] = {}
        overflow: set[str] = set()
        for key, function in selected.items():
            size = len(function.code.encode()) + len(function.context.encode())
            if size > limits.max_function_bytes:
                skipped["function_bytes"] += 1
                continue
            if stats.source_bytes + size > limits.max_source_bytes:
                skipped["source_bytes"] += 1
                continue
            if stats.examined_regions >= limits.max_regions:
                skipped["region_limit_functions"] += 1
                continue
            stats.source_bytes += size
            regions = self._function_regions(function, stats, skipped)
            for canonical, region in regions:
                operation_id = _digest(GENERATOR + "\n" + canonical)
                if operation_id in overflow:
                    skipped["overfull_family_sites"] += 1
                    continue
                group = groups.get(operation_id)
                if group is None:
                    if len(groups) + len(overflow) >= limits.max_operation_ids:
                        skipped["operation_id_limit"] += 1
                        continue
                    group = groups[operation_id] = _Group(canonical, {})
                if key not in group.owners and len(group.owners) >= limits.max_owners:
                    # Dropping an overfull family as a whole avoids claiming an arbitrary
                    # subset of a repository-wide idiom is its complete ownership family.
                    del groups[operation_id]
                    overflow.add(operation_id)
                    skipped["overfull_families"] += 1
                    continue
                sites = group.owners.setdefault(key, [])
                if len(sites) >= limits.max_sites_per_owner:
                    skipped["sites_per_owner"] += 1
                    continue
                sites.append(region)
                stats.indexed_regions += 1
        stats.operation_ids = len(groups) + len(overflow)
        callers: dict[str, list[str]] = defaultdict(list)
        for key, function in selected.items():
            prefix = f"{function.origin.repository}/" if function.origin and function.origin.repository else ""
            for target in function.analysis.local_calls if function.analysis else ():
                targets = callers[prefix + target]
                if len(targets) < limits.max_callers:
                    targets.append(key)
                else:
                    skipped["callers"] += 1
        snapshots: dict[str, tuple[Function, str]] = {}

        def owner(key: str, regions: list[OperationRegion]) -> OperationOwner:
            if key not in snapshots:
                function = selected[key].model_copy(deep=True)
                snapshots[key] = function, _digest(function.model_dump_json())
            function, source_id = snapshots[key]
            return OperationOwner(
                owner_id=key, source_id=source_id, function=function, regions=regions, local_callers=callers[key]
            )

        eligible = []
        for operation_id, group in groups.items():
            if len(group.owners) < 3:
                continue
            if changed_ids is not None and not changed_ids.intersection(group.owners):
                skipped["unchanged_families"] += 1
                continue
            owners = []
            family_sites: dict[tuple[str, str, str], list[SourceSpan]] = defaultdict(list)
            for key, regions in sorted(group.owners.items()):
                disjoint: list[OperationRegion] = []
                source_sites = family_sites[_source_file(selected[key])]
                for region in sorted(regions, key=lambda r: (r.span.line, r.span.column, -r.statements)):
                    if not any(_overlaps(region.span, old) for old in source_sites):
                        disjoint.append(region)
                        source_sites.append(region.span)
                    else:
                        skipped["duplicate_source_site"] += 1
                if disjoint:
                    owners.append(owner(key, disjoint))
            if len(owners) < 3:
                continue
            if changed_ids is not None and not any(member.owner_id in changed_ids for member in owners):
                skipped["unchanged_after_source_dedup"] += 1
                continue
            benefit = _benefit(owners)
            if benefit.removable_statements > 0:
                eligible.append((operation_id, group.canonical, owners, benefit))
            else:
                skipped["nonpositive_benefit"] += 1
        stats.eligible_families = len(eligible)
        eligible.sort(key=lambda item: (-item[3].removable_statements, -len(item[2]), item[0]))
        occupied: dict[tuple[str, str, str], list[SourceSpan]] = defaultdict(list)
        nominations = []
        for operation_id, canonical, owners, _ in eligible:
            if len(nominations) >= limits.max_candidates:
                skipped["candidate_limit"] += 1
                continue
            remaining = []
            for member in owners:
                sites = [
                    region
                    for region in member.regions
                    if not any(_overlaps(region.span, span) for span in occupied[_source_file(member.function)])
                ]
                skipped["overlapping_sites"] += len(member.regions) - len(sites)
                if sites:
                    remaining.append(member.model_copy(update={"regions": sites}))
            if len(remaining) < 3:
                skipped["overlap_owner_floor"] += 1
                continue
            if changed_ids is not None and not any(member.owner_id in changed_ids for member in remaining):
                skipped["unchanged_after_overlap"] += 1
                continue
            benefit = _benefit(remaining)
            if benefit.removable_statements <= 0:
                skipped["overlap_benefit_floor"] += 1
                continue
            size = sum(len(member.function.model_dump_json().encode()) for member in remaining)
            if stats.output_source_bytes + size > limits.max_output_source_bytes:
                skipped["output_source_bytes"] += 1
                continue
            evidence = json.dumps(
                [[member.source_id, [region.model_dump() for region in member.regions]] for member in remaining],
                sort_keys=True,
                separators=(",", ":"),
            )
            nominations.append(
                FamilyNomination(
                    operation_id=operation_id,
                    nomination_id=_digest(operation_id + evidence),
                    canonical_operation=canonical,
                    owners=remaining,
                    benefit=benefit,
                )
            )
            stats.output_source_bytes += size
            for member in remaining:
                occupied[_source_file(member.function)].extend(region.span for region in member.regions)
        stats.nominated_families = len(nominations)
        stats.nominated_owners = sum(len(family.owners) for family in nominations)
        stats.nominated_sites = sum(len(member.regions) for family in nominations for member in family.owners)
        stats.skipped = dict(sorted((key, count) for key, count in skipped.items() if count))
        return FamilyBatch(run=run or Run(), limits=limits, nominations=nominations, stats=stats)

    def _function_regions(
        self, function: Function, stats: FamilyStats, skipped: Counter[str]
    ) -> list[tuple[str, OperationRegion]]:
        limits = self.limits
        if function.declaration is not None or (
            function.analysis.language != "python" if function.analysis else not function.path.endswith(".py")
        ):
            skipped["unsupported_language_or_declaration"] += 1
            return []
        lines = function.code.splitlines(keepends=True)
        if function.line < 1 or function.end_line != function.line + len(lines) - 1:
            skipped["invalid_span"] += 1
            return []
        try:
            tree = _parse(function.code)
            if (
                tree is None
                or len(tree.body) != 1
                or not isinstance(tree.body[0], (ast.FunctionDef, ast.AsyncFunctionDef))
            ):
                skipped["parse_unavailable"] += 1
                return []
            node = tree.body[0]
            if node.name != function.name:
                skipped["invalid_span"] += 1
                return []
            for index, _ in enumerate(ast.walk(node)):
                if index >= limits.max_function_nodes:
                    skipped["function_nodes"] += 1
                    return []
            indent = min((len(line) - len(line.lstrip()) for line in lines if line.strip()), default=0)
            normalized = "\n".join(line[indent:] for line in function.code.splitlines())
            table = symtable.symtable(normalized, function.path, "exec")
            scope = next(child for child in table.get_children() if child.get_name() == node.name)
            locals_ = {
                symbol.get_name() for symbol in scope.get_symbols() if symbol.is_local() and not symbol.is_imported()
            }
            stats.scanned_functions += 1
            result = []
            source_lines = [line.encode() for line in lines]
            raw = sorted(
                # The operation-block vocabulary across every suite: no depth cap, and an oversized
                # compound still yields its eligible complete children.
                statement_regions(node.body),
                key=lambda item: (item[1][0].lineno, item[1][0].col_offset, -item[1][-1].end_lineno),
            )
            for kind, statements, enclosing in raw:
                if len(result) >= limits.max_regions_per_function:
                    skipped["regions_per_function"] += 1
                    continue
                if stats.examined_regions >= limits.max_regions:
                    skipped["region_limit"] += 1
                    break
                stats.examined_regions += 1
                span = _span(statements[0], statements[-1], function, indent)
                code = _slice(source_lines, span, function.line)
                if len(code.encode()) > limits.max_region_bytes:
                    skipped["region_bytes"] += 1
                    continue
                nodes = []
                for statement in statements:
                    for child in ast.walk(statement):
                        nodes.append(child)
                        if len(nodes) > limits.max_region_nodes:
                            break
                    if len(nodes) > limits.max_region_nodes:
                        break
                if len(nodes) > limits.max_region_nodes:
                    skipped["region_nodes"] += 1
                    continue
                if any(isinstance(child, _SCOPES) for child in nodes):
                    skipped["nested_binding_scope"] += 1
                    continue
                count = sum(isinstance(child, ast.stmt) and not docstring_statement(child) for child in nodes)
                if count < 2:
                    skipped["single_statement"] += 1
                    continue
                # A straight run that only assigns a helper result and returns it is
                # already delegated, just like a one-statement return helper(...).
                if self._delegate(statements):
                    skipped["single_call_delegate"] += 1
                    continue
                canonical, bindings = _canonical(statements, locals_)
                result.append(
                    (
                        canonical,
                        OperationRegion(
                            span=span,
                            code=code,
                            kind=kind,
                            statements=count,
                            bindings=bindings,
                            enclosing=[_span(parent, parent, function, indent) for parent in enclosing],
                        ),
                    )
                )
            return result
        except (SyntaxError, ValueError, RecursionError, StopIteration):
            skipped["parse_unavailable"] += 1
            return []

    @staticmethod
    def _delegate(statements: list[ast.stmt]) -> bool:
        if (
            len(statements) != 2
            or not isinstance(statements[0], ast.Assign)
            or not isinstance(statements[1], ast.Return)
        ):
            return False
        assignment, returned = statements
        value = assignment.value.value if isinstance(assignment.value, ast.Await) else assignment.value
        return (
            len(assignment.targets) == 1
            and isinstance(assignment.targets[0], ast.Name)
            and isinstance(returned.value, ast.Name)
            and returned.value.id == assignment.targets[0].id
            and isinstance(value, ast.Call)
            and sum(isinstance(child, ast.Call) for child in ast.walk(value)) == 1
        )
