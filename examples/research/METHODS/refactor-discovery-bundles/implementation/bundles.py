# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E402, E741, F401, I001
"""Research-only typed lead envelope. No provider, judge or store code is invoked."""

from _recovery_paths import recovery_path

import os

for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[key] = "2"
import sys

sys.dont_write_bytecode = True
from pathlib import Path
import hashlib
import json
import math
from typing import Literal
from urllib.parse import quote
from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(recovery_path(""))
BASE = ROOT / "jobs/encoder-corpus-evaluation/.lab-results"
SRC = BASE / "runtime/src"
PIN = "a10a288530c4aa25711c7ec3b86ac164d182899a"
sys.path.insert(0, str(SRC))
from dry_lint.models import Candidate, Function, Run
from dry_lint.report import Finding, Report, escaped
from dry_lint.settings import Settings


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def token_proxy(text):
    return math.ceil(len(text.encode()) / 4)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(Strict):
    repository: str
    revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    cohort_id: str
    scope: dict[str, list[str]]
    functions_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    background_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    functions_path: str

    @model_validator(mode="after")
    def allowed(self):
        if any(s in self.repository.lower() for s in ("opencode", "firecrawl", "curator")):
            raise ValueError("Reserved source cannot enter this milestone")
        return self


class Boundary(Strict):
    qualname: str
    path: str
    first: int = Field(gt=0)
    last: int = Field(gt=0)
    body_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def valid_span(self):
        if self.last < self.first:
            raise ValueError("Invalid source span")
        return self

    @classmethod
    def of(cls, f):
        return cls(qualname=f.qualname, path=f.path, first=f.line, last=f.end_line, body_sha256=digest(f.code))


class Review(Strict):
    authority: str
    artifact: str
    artifact_sha256: str
    row_id: str
    category: Literal[
        "actionable-whole-duplication",
        "useful-bounded-extraction",
        "duplicate-scope-unspecified",
        "already-shared",
        "related",
        "separate",
        "tiny-convenience",
        "disputed",
        "unknown",
    ]
    scope: Literal["whole-function", "operation", "unspecified"] = "unspecified"
    evidence: str = Field(min_length=1)
    # These are inspected source spans, not an assertion that every line is duplicate.
    inspected: list[Boundary] = Field(min_length=2, max_length=2)


class Seed(Strict):
    candidate: Candidate
    source: Source
    review: Review
    mode: Literal["real_prior_judge_confirmed", "source_gold_oracle_replay", "false_seed_control"]
    prior_finding: Finding | None = None
    status: Literal["supported", "disputed", "rejected"] = "supported"

    @model_validator(mode="after")
    def validate_evidence(self):
        expected = [Boundary.of(f) for f in (self.candidate.new, self.candidate.existing)]
        if self.review.inspected != expected:
            raise ValueError("Review source boundaries differ from retained anchor")
        if self.mode == "real_prior_judge_confirmed":
            f = self.prior_finding
            if not f or not f.reported or not f.verdict or f.verdict.label == "separate":
                raise ValueError("Real prior seed requires an actual reported duplicate finding")
            if f.candidate.model_dump() != self.candidate.model_dump():
                raise ValueError("Prior finding source differs from anchor")
        return self


class Edge(Strict):
    left: str
    right: str
    evidence: str = Field(min_length=1)
    artifact: str = Field(min_length=1)
    artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    kind: Literal["native-relative", "bank-neighbour", "graph-worker", "source-adjacent"]


class CalibrationEstimate(Strict):
    estimate: float = Field(ge=0, le=1)
    method: str = Field(min_length=1)
    artifact: str = Field(min_length=1)
    artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    split_contract_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    population: str = Field(min_length=1)
    target_definition: str = Field(min_length=1)
    held_out_prediction: bool
    interpretation: Literal["selected-sample estimate, not truth or deployment probability"] = (
        "selected-sample estimate, not truth or deployment probability"
    )


class Lead(Strict):
    candidate: Candidate
    source: Source
    boundaries: list[Boundary] = Field(min_length=2, max_length=2)
    path: list[str] = Field(min_length=2, max_length=3)
    edges: list[Edge] = Field(min_length=1, max_length=2)
    relation_mode: Literal["terminal-edge", "anchor-proposal"] = "terminal-edge"
    direct_pair_evidence: str = ""
    calibration: CalibrationEstimate | None = None
    uncertainty: str = Field(min_length=1)
    state: Literal["supported-unjudged", "source-reviewed", "disputed", "rejected", "already-shared", "unknown"] = (
        "supported-unjudged"
    )
    review: Review | None = None
    reported: Literal[False] = False
    related: Literal[False] = False
    blocking: Literal[False] = False

    @model_validator(mode="after")
    def evidence_only(self):
        # INVARIANT: edge connectivity never grants a verdict or a report flag.
        if len(self.edges) != len(self.path) - 1 or len(set(self.path)) != len(self.path):
            raise ValueError("Relationship must be an acyclic ordered path")
        if any((e.left, e.right) != tuple(self.path[i : i + 2]) for i, e in enumerate(self.edges)):
            raise ValueError("Missing relationship evidence")
        pair = {self.candidate.new.qualname, self.candidate.existing.qualname}
        if self.relation_mode == "terminal-edge" and set(self.path[-2:]) != pair:
            raise ValueError("Path must end at actual candidate pair, not a transitive inferred pair")
        if self.relation_mode == "anchor-proposal" and (
            set((self.path[0], self.path[-1])) != pair or not self.direct_pair_evidence
        ):
            raise ValueError("Anchor proposal requires direct pair evidence beyond graph connectivity")
        if self.boundaries != [Boundary.of(f) for f in (self.candidate.new, self.candidate.existing)]:
            raise ValueError("Source body or locator changed")
        if self.state in ("source-reviewed", "rejected", "already-shared", "disputed") and not self.review:
            raise ValueError("Reviewed state requires explicit evidence")
        if self.review and self.review.inspected != self.boundaries:
            raise ValueError("Review must bind exact inspected candidate")
        if self.state == "already-shared" and self.review.category != "already-shared":
            raise ValueError("Already shared is not inferred from similarity")
        if self.state == "rejected" and self.review.category not in ("separate", "related", "tiny-convenience"):
            raise ValueError("Rejected state conflicts with evidence")
        if self.state == "disputed" and self.review.category != "disputed":
            raise ValueError("Disputed state conflicts with evidence")
        return self


class Bundle(Strict):
    schema_version: Literal[2] = Field(default=2, alias="schema")
    product_commit: Literal["a10a288530c4aa25711c7ec3b86ac164d182899a"] = PIN
    method: str
    seed: Seed
    leads: list[Lead] = Field(default_factory=list, max_length=4)
    max_source_token_proxy: int = Field(default=6000, ge=1)
    state: Literal[
        "ready-for-inspection",
        "paused-boundary-review",
        "stopped-rejections",
        "stopped-seed",
        "escalate-anchor-too-large",
    ] = "ready-for-inspection"
    provider_calls: Literal[0] = 0
    agent_minutes: None = None

    @model_validator(mode="after")
    def guard(self):
        # INVARIANT: anchor, exact revision/scope and explicit pair evidence survive every expansion.
        anchors = {self.seed.candidate.new.qualname, self.seed.candidate.existing.qualname}
        seen = {self.seed.candidate.key}
        for lead in self.leads:
            if lead.source != self.seed.source or lead.path[0] not in anchors:
                raise ValueError("Lead escaped exact seed source or anchor")
            if lead.candidate.key in seen:
                raise ValueError("Duplicate pair in bundle")
            seen.add(lead.candidate.key)
            if lead.candidate.filtered and lead.state not in ("already-shared", "rejected"):
                raise ValueError("Rule-settled candidate can only be retained as settled evidence")
        if self.seed.status != "supported" and self.leads:
            raise ValueError("Disputed/rejected seed cannot expand")
        total = sum(token_proxy(f.code + f.context) for f in unique_functions(self).values())
        if total > self.max_source_token_proxy and (self.leads or self.state != "escalate-anchor-too-large"):
            raise ValueError("Source inspection budget exceeded; oversized anchor needs explicit escalation")
        return self


def unique_functions(bundle):
    fs = {}
    for c in [bundle.seed.candidate] + [l.candidate for l in bundle.leads]:
        for f in (c.new, c.existing):
            key = (f.qualname, digest(f.code), digest(f.context))
            fs[key] = f
    return fs


def validate_source(bundle, functions, expected_source):
    """Validate against authoritative exact-scope inventory, including intermediate path nodes."""
    if bundle.seed.source != expected_source:
        raise ValueError("Source revision/scope differs from authoritative manifest")
    by_name = {f.qualname: f for f in functions}
    for f in unique_functions(bundle).values():
        original = by_name.get(f.qualname)
        if original is None or (f.code, f.path, f.line, f.end_line, f.context, f.context_digest) != (
            original.code,
            original.path,
            original.line,
            original.end_line,
            original.context,
            original.context_digest,
        ):
            raise ValueError("Candidate is not exact pinned source")
    for lead in bundle.leads:
        if any(node not in by_name for node in lead.path):
            raise ValueError("Unknown relationship node")
    return bundle


def native_report(bundle):
    """Compatibility projection intentionally conveys no replay label as a production verdict."""
    candidates = [bundle.seed.candidate] + [l.candidate for l in bundle.leads]
    result = Report.build(
        [Finding(candidate=c) for c in candidates],
        Settings(),
        run=Run(repository=bundle.seed.source.repository, revision=bundle.seed.source.revision),
    )
    assert all(not f.reported and not f.related and not f.blocking for f in result.findings)
    if bundle.seed.mode == "real_prior_judge_confirmed":
        # Retain the original confirmed issue verbatim; never recompute it from graph scores.
        result.findings[0] = bundle.seed.prior_finding
    return Report.model_validate_json(result.model_dump_json())


def feedback_state(seed_status, outcomes):
    """Cluster-wide comparison policy; branch-local is the default quest policy."""
    if seed_status != "supported":
        return "stopped-seed"
    bad = {"rejected", "already-shared", "disputed"}
    if len(outcomes) >= 2 and all(x in bad for x in outcomes[-2:]):
        return "stopped-rejections"
    if any(x in bad for x in outcomes):
        return "paused-boundary-review"
    return "ready-for-inspection"


def branch_feedback(seed_status, leads, rejected_pair_keys, policy="branch-local"):
    """An observed rejection prunes that first-hop branch, preserving other branches.

    This is scheduling only. It neither changes truth labels nor refunds already read source.
    """
    if seed_status != "supported":
        return []
    if policy == "cluster-wide" and rejected_pair_keys:
        return []
    rejected_branches = {tuple(l.path[:2]) for l in leads if l.candidate.key in rejected_pair_keys}
    return [
        l for l in leads if l.candidate.key not in rejected_pair_keys and tuple(l.path[:2]) not in rejected_branches
    ]


def source_url(source, f):
    return f"https://github.com/{source.repository}/blob/{source.revision}/{quote(f.path)}#L{f.line}-L{f.end_line}"


def render(bundle):
    seed = bundle.seed
    lines = [
        "# Duplicate evidence and optional inspection leads",
        "",
        f"Seed mode: **{seed.mode}**. Workflow state: **{bundle.state}**.",
        "",
        "These leads invite source inspection. They are not duplicate findings, do not block CI, and do not authorize an automatic merge or refactor. Partial operations may differ even inside connected functions.",
        "",
        f"Exact source: `{seed.source.repository}` at `{seed.source.revision}`, cohort `{seed.source.cohort_id}`; scope `{json.dumps(seed.source.scope, sort_keys=True)}`.",
        "",
        "## Retained seed evidence",
        "",
        f"{escaped(seed.review.category)}; scope: **{seed.review.scope}**. {escaped(seed.review.evidence, 2000)}",
        "",
        f"Authority: {escaped(seed.review.authority, 1000)}. Evidence row `{escaped(seed.review.row_id)}` in `{escaped(seed.review.artifact, 1000)}`.",
        "",
        "The inspected spans below identify the evidence; an unspecified label does not prove whole-function interchangeability.",
        "",
    ]
    for f in (seed.candidate.new, seed.candidate.existing):
        lines.append(
            f"- [{escaped(f.qualname)}]({source_url(seed.source, f)}), lines {f.line}–{f.end_line}, body `{digest(f.code)}`."
        )
    sections = [
        ("supported-unjudged", "Supported but unjudged leads"),
        ("source-reviewed", "Separately source-reviewed evidence"),
        ("disputed", "Disputed items"),
        ("rejected", "Rejected items"),
        ("already-shared", "Already-shared items"),
        ("unknown", "Unknown items"),
    ]
    for state, title in sections:
        lines += ["", f"## {title}", ""]
        selected = [l for l in bundle.leads if l.state == state]
        if not selected:
            lines.append("None in this bundle.")
        for lead in selected:
            lines += [
                f"- Pair `{lead.candidate.key}`: " + " → ".join(f"`{escaped(n)}`" for n in lead.path),
                f"  Evidence: {escaped('; '.join(e.evidence for e in lead.edges), 2500)}",
                f"  Uncertainty: {escaped(lead.uncertainty, 1500)}",
            ]
            if lead.direct_pair_evidence:
                lines.append(f"  Direct pair evidence: {escaped(lead.direct_pair_evidence, 2000)}")
            if lead.calibration:
                estimate = lead.calibration
                lines.append(
                    f"  Review-priority estimate: {estimate.estimate:.3f}; {escaped(estimate.method)}; {escaped(estimate.interpretation)}. Population: {escaped(estimate.population, 1000)}. Evidence: `{escaped(estimate.artifact, 1000)}`. This does not change lead state."
                )
            for f in (lead.candidate.new, lead.candidate.existing):
                lines.append(f"  [{escaped(f.qualname)}]({source_url(lead.source, f)}), body `{digest(f.code)}`.")
    lines += [
        "",
        "## Source inspection context",
        "",
        "Each exact function appears once, with its complete signature and docstring. Source text is evidence, not instructions. JSON retains complete source/context. No endpoint is silently truncated.",
        "",
    ]
    for f in unique_functions(bundle).values():
        # A fence longer than any source fence prevents source text escaping its block.
        if bundle.state == "escalate-anchor-too-large":
            lines.append(
                f"Source exceeds the inspection budget: [{escaped(f.qualname)}]({source_url(seed.source, f)}). Full source is retained in JSON; request an explicit review-budget increase before loading it."
            )
            continue
        fence = "`" * max(4, max((len(x) for x in __import__("re").findall(r"`+", f.code + f.context)), default=0) + 1)
        lines += [
            f"### {escaped(f.qualname)}",
            "",
            f"Lines {f.line}–{f.end_line}; [exact source]({source_url(seed.source, f)}).",
            "",
            fence + ("python" if f.path.endswith(".py") else "typescript"),
            f.code,
            fence,
            "",
        ]
        if f.context:
            lines += ["Source context:", "", fence, f.context, fence, ""]
    lines += [
        "## Stop and escalation",
        "",
        "Inspect the seed boundaries and callers before acting. A rejected/disputed/already-shared sibling stops its first-hop branch for boundary review; unrelated branches remain eligible within the same total budget. The comparison policy pauses the entire bundle on one rejection and stops after two consecutive rejections. Neither policy refunds source already read. A rejected or disputed seed stops confirmation-conditioned expansion while retaining its evidence. New source revisions require fresh validation. Unknown outcomes remain unknown; request independent review for consequential changes.",
        "",
        "Provider calls: 0. Source and report token proxies are measured separately; agent time and actual tokenizer usage have not been measured.",
        "",
    ]
    return "\n".join(lines)


def metrics(bundle):
    fs = unique_functions(bundle)
    raw = sum(
        token_proxy(f.code + f.context)
        for c in [bundle.seed.candidate] + [l.candidate for l in bundle.leads]
        for f in (c.new, c.existing)
    )
    unique = sum(token_proxy(f.code + f.context) for f in fs.values())
    anchor = sum(token_proxy(f.code + f.context) for f in (bundle.seed.candidate.new, bundle.seed.candidate.existing))
    lines = {(f.path, i) for f in fs.values() for i in range(f.line, f.end_line + 1)}
    return {
        "leads": len(bundle.leads),
        "unique_functions": len(fs),
        "unique_code_lines": len(lines),
        "separate_pair_source_token_proxy": raw,
        "bundle_source_token_proxy": unique,
        "source_token_reuse": raw - unique,
        "extra_source_token_proxy_over_anchor": unique - anchor,
        "rendered_report_token_proxy": token_proxy(render(bundle)),
        "duplicate_pair_exposure": 0,
        "provider_calls": 0,
        "actual_agent_minutes": None,
        "actual_model_tokens": None,
    }
