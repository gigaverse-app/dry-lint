"""
The report: what a run found, as `report.json`, and every way dry-lint shows it.

Every view renders the same `Report`, so the terminal, the annotations, the pull request comment, SARIF and the
check run always list the same findings in the same order: drifted first, then by score. A judge's reason is
untrusted text (an LLM judge read code from the pull request), so it is flattened, capped and escaped wherever
it is shown, and never rendered as markdown or links.
"""

import json
import os
import re
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, Field

from dry_lint import __version__
from dry_lint.costs import Spend
from dry_lint.family_judging import FamilyFinding
from dry_lint.models import Candidate, Function, Run, Verdict, Versioned, qualified
from dry_lint.settings import Settings

MARKER = "<!-- dry-lint -->"
REASON_LIMIT = 300
OWNERS = {
    "existing": "call the existing function",
    "new": "move callers of the existing function to the new one",
    "shared": "extract a shared helper both can call",
}


def plain(text: str, limit: int = REASON_LIMIT) -> str:
    """One line of at most `limit` characters."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def escaped(text: str, limit: int = REASON_LIMIT) -> str:
    """Plain text that markdown shows as typed: no links, emphasis, HTML or table breaks."""
    return re.sub(r"([\\`*_{}\[\]()<>#!|~])", r"\\\1", plain(text, limit))


class Finding(BaseModel):
    """A proposed pair and, when it was judged, the verdict and whether it came from the store."""

    candidate: Candidate
    verdict: Verdict | None = None
    cached: bool = False
    deferred: bool = False
    budget_deferred: bool = Field(default=False, description="No final verdict because the spending allowance ran out.")
    source_review: bool = False
    family: int = Field(default=1, description="How many look-alikes were proposed for the same changed function.")
    reported: bool = Field(default=False, description="Judged a duplicate at or above report_at.")
    blocking: bool = Field(
        default=False, description="A confirmed duplicate at fail_at, or an unresolved pair requiring agent review."
    )
    related: bool = Field(
        default=False,
        description="A relative judged a duplicate at or above report_at: shown "
        "with its parent pair, never on its own, never blocking.",
    )

    @property
    def kind(self) -> Literal["function", "model"]:
        return "model" if self.candidate.new.declaration or self.candidate.existing.declaration else "function"

    @property
    def tracked(self) -> bool:
        """Model ownership tasks belong in history, but never in confirmed-duplicate counters."""
        return self.reported or self.kind == "model" and self.review_required

    @property
    def review_required(self) -> bool:
        """An unresolved primary pair is work for the coding agent, never a confirmed duplicate."""
        return self.candidate.lane != "relative" and (
            self.source_review
            or self.deferred
            or self.verdict is not None
            and self.verdict.model_assessment is not None
        )

    def headline(self) -> str:
        new, existing = self.candidate.new, self.candidate.existing
        kind = "review required" if self.review_required else self.verdict.label if self.verdict else "candidate"
        return f"{new.qualname.split('::')[1]} looks like {existing.qualname} ({kind})"

    def advice(self, relatives: list["Finding"] = ()) -> str:
        parts = []
        if self.review_required:
            parts.append(
                "coding agent: inspect both implementations and callers; refactor duplication or record a reasoned pair-specific dismissal; no extra judge budget is needed"
            )
            if self.candidate.new.declaration or self.candidate.existing.declaration:
                parts.append(
                    "resolve nested types and producer/consumer roles; apply repository ownership policies; "
                    "preserve independently evolving contracts and verify any proposed shared component"
                )
        if self.verdict:
            parts.append(f"judge {self.verdict.score:.2f}" + (" (cached)" if self.cached else ""))
            if self.verdict.label == "drifted":
                parts.append("the two already behave differently")
            if self.kind == "function" and self.verdict.owner in OWNERS and not self.candidate.consolidation:
                parts.append(OWNERS[self.verdict.owner])
            if self.verdict.why:
                parts.append(plain(self.verdict.why))
            if self.verdict.label != "separate" and self.candidate.consolidation:
                parts.append(
                    "preferred consolidation home: "
                    + "; ".join(target.destination for target in self.candidate.consolidation)
                )
        parts.append(f"similarity {self.candidate.similarity:.2f}")
        if self.candidate.policies:
            parts.append(
                "adopter policies: " + "; ".join(plain(f"{p.name}: {p.reason}") for p in self.candidate.policies)
            )
        parts.append(f"pair {self.candidate.key}")
        if self.family > 1:
            parts.append(f"{self.family} look-alikes")
        if relatives:
            parts.append(self.kin(relatives))
        parts.append(f"if they are different concepts, add `{self.suppression()}`")
        return "; ".join(parts)

    def kin(self, relatives: list["Finding"]) -> str:
        """What else the fix touches: the existing function's other copies, to consolidate in the same change."""
        assert all(r.verdict is not None for r in relatives), "a relative is shown only once judged"
        copies = ", ".join(f"{r.candidate.existing.qualname} (judge {r.verdict.score:.2f})" for r in relatives)
        existing = self.candidate.existing
        return (
            f"fixing this touches {qualified(existing.owner, existing.name)}, which also looks like {copies}: "
            "consolidate them in the same change"
        )

    def suppression(self) -> str:
        prefix = "//" if self.candidate.new.path.endswith((".ts", ".tsx", ".mts", ".cts")) else "#"
        return f"{prefix} dry-lint: distinct-from {self.candidate.existing.qualname}"


class JudgingSummary(BaseModel):
    """Which judges ran, on which thresholds, within which budget, and what they cost: explicit on every report."""

    preset: str = ""
    judge: str | None = None
    escalation: str | None = None
    band: tuple[float, float] | None = None
    report_at: float = 0.8
    fail_at: float = 0.8
    budget_usd: float = 0.0
    subscription_calls: int = 0
    spend: list[Spend] = Field(default_factory=list)
    spent_before: float = Field(default=0.0, description="What earlier runs on the same pull request spent.")
    pull_request: bool = Field(default=False, description="The budget covered a pull request, not just this run.")
    campaign: str = ""
    exploration_credit: float = 0.0

    @property
    def usd(self) -> float | None:
        """This run's estimated cost at list price, subscriptions included; None when any judge's price is unknown."""
        costs = [s.usd for s in self.spend]
        return None if any(c is None for c in costs) else sum(costs)

    @property
    def skipped(self) -> int:
        return sum(s.skipped for s in self.spend)

    def line(self, *, ranking: bool = False) -> str:
        """One line: judges, thresholds, and the bill."""
        judges = self.judge or "no judge"
        if self.escalation and self.band:
            judges += f" > {self.escalation} on [{self.band[0]:g}, {self.band[1]:g})"
        if self.campaign:
            recovery = [s.judge for s in self.spend if s.judge not in {self.judge, self.escalation}]
            if recovery:
                judges += "; recovery " + ", ".join(recovery)
        thresholds = (
            f"reports at {self.report_at:g}, fails at {self.fail_at:g}"
            if self.fail_at > self.report_at
            else f"reports and fails at {self.report_at:g}"
        )
        if ranking:
            thresholds = "ranking only; coding agent owns consolidation and dismissal"
        usd = self.usd
        scope = "for this pull request" if self.pull_request else "for this campaign" if self.campaign else "budget"
        bill = (
            "cost unknown"
            if usd is None
            else f"est. ${usd:.3f}"
            + (f" (${usd + self.spent_before:.3f} so far)" if self.spent_before else "")
            + f" of ${self.budget_usd:g} {scope}"
        )
        if self.campaign:
            bill = bill.replace("est.", "accounted") + f"; exploration credit ${self.exploration_credit:.4f}"
        calls = sum(s.calls for s in self.spend if s.subscription)
        parts = [
            f"preset {self.preset}" if self.preset else "",
            judges,
            thresholds,
            bill,
            f"{calls} subscription calls" if calls else "",
            f"{self.skipped} pairs not judged (budget)" if self.skipped else "",
            *(
                f"{s.judge} failed ({s.error}): {s.failed} pairs "
                + (
                    "deferred; accounted attempts can retry on a later tree"
                    if self.campaign
                    else "kept the first judge's answer, asked again next run"
                )
                for s in self.spend
                if s.error
            ),
        ]
        return " · ".join(p for p in parts if p)


class BacklogCleanup(BaseModel):
    """An accepted baseline pair the change cleaned up, and the evidence: a side it removed, or a `separate` verdict."""

    new: str = Field(description="Qualified names, as the baseline records them.")
    kind: Literal["function", "model"] = "function"
    existing: str
    how: Literal["removed", "separate"]


class Report(Versioned):
    """`report.json`."""

    run: Run = Field(default_factory=Run)
    changed: int = 0
    functions: int = Field(default=0, description="How many functions the repository has: what changed ones meet.")
    models: int = 0
    changed_models: int = 0
    model_judging: JudgingSummary | None = None
    model_debt: dict[str, int] | None = None
    scope: Literal["change", "repository"] = Field(default="change", description="`check` or `scan`.")
    judge: str | None = Field(default=None, description="The judge (and escalation judge), or None when unjudged.")
    judging: JudgingSummary | None = Field(default=None, description="Judges, thresholds, budget and cost.")
    findings: list[Finding] = Field(default_factory=list)
    families: list[FamilyFinding] = Field(default_factory=list)
    family_exclusions: list[dict[str, str]] = Field(default_factory=list)
    filtered: list[Candidate] = Field(default_factory=list, description="Pairs a rule settled, with the rule.")
    backlog: list[BacklogCleanup] | None = Field(
        default=None, description="Accepted baseline pairs this change cleaned up; None when no baseline was checked."
    )
    model_backlog: list[BacklogCleanup] | None = None

    @classmethod
    def build(
        cls,
        findings: list[Finding],
        settings: Settings,
        filtered: list[Candidate] = (),
        run: Run | None = None,
        changed: int = 0,
        judge: str | None = None,
        functions: int = 0,
        scope: Literal["change", "repository"] = "change",
        judging: JudgingSummary | None = None,
    ) -> "Report":
        family: dict[str, int] = {}
        for f in findings:
            if f.candidate.lane != "relative":
                family[f.candidate.new.qualname] = family.get(f.candidate.new.qualname, 0) + 1

        def duplicate_at(f: Finding, threshold: float) -> bool:
            return (
                not f.review_required
                and not f.deferred
                and f.verdict is not None
                and f.verdict.model_assessment is None
                and settings.duplicate_at(f.verdict, threshold)
            )

        marked = [
            f.model_copy(update={"related": duplicate_at(f, settings.report_at)}) if f.candidate.lane == "relative" else
            f.model_copy(update={"family": family[f.candidate.new.qualname], "reported": duplicate_at(f, settings.report_at),
                                 "blocking": (f.review_required and not f.budget_deferred) or duplicate_at(f, max(settings.report_at, settings.fail_at))})
            for f in findings
        ]  # fmt: skip
        order = sorted(
            marked,
            key=lambda f: (
                not f.blocking,
                not f.reported,
                -f.candidate.priority,
                f.verdict is None or f.verdict.label != "drifted",
                -(f.verdict.score if f.verdict else f.candidate.similarity),
            ),
        )
        return cls(
            run=run or Run(),
            changed=changed,
            functions=functions,
            scope=scope,
            judge=judge,
            findings=order,
            filtered=list(filtered),
            judging=judging,
        )

    @property
    def visible(self) -> list[Finding]:
        """Review tasks, unjudged candidates and reported duplicates; relatives show with their parent."""
        return [
            f
            for f in self.findings
            if f.review_required
            or (not f.deferred and f.candidate.lane != "relative" and (f.verdict is None or f.reported))
        ]

    @property
    def review_required(self) -> list[Finding]:
        return [f for f in self.findings if f.review_required]

    def relatives(self, finding: Finding) -> list[Finding]:
        """The reported relatives of `finding`: copies its fix touches, closest first."""
        return [f for f in self.findings if f.related and f.candidate.parent == finding.candidate.key]

    @property
    def deferred(self) -> int:
        return sum(f.deferred for f in self.findings)

    def as_warnings(self) -> "Report":
        return self.model_copy(update={"findings": [f.model_copy(update={"blocking": False}) for f in self.findings]})

    @property
    def repository_wide(self) -> bool:
        """A `scan` of the whole repository rather than a `check` of a change."""
        return self.scope == "repository"

    @property
    def stats(self) -> dict[str, int]:
        judged = [f for f in self.findings if f.verdict is not None]
        return {
            "changed": self.changed,
            "candidates": len(self.findings) + len(self.filtered),
            "filtered": len(self.filtered),
            "cached": sum(f.cached for f in judged),
            "judged": sum(not f.cached for f in judged),
            "reported": sum(f.reported for f in self.findings),
        }

    def lane(self, kind: Literal["function", "model"]) -> "Report":
        """A rendering view of one pass; counts and judging retain that pass's meaning."""
        model = kind == "model"
        return self.model_copy(
            update={
                "findings": [f for f in self.findings if f.kind == kind],
                "filtered": [c for c in self.filtered if bool(c.new.declaration or c.existing.declaration) == model],
                "changed": self.changed_models if model else self.changed,
                "functions": self.models if model else self.functions,
                "judging": self.model_judging if model else self.judging,
                "judge": (
                    self.model_judging.judge
                    or ("source-review" if any(f.review_required for f in self.findings if f.kind == "model") else None)
                )
                if model and self.model_judging
                else self.judge,
                "model_judging": None,
                "model_debt": None,
            }
        )


def family_summary(report: Report, *, markdown: bool = False) -> str:
    if not report.families and not report.family_exclusions:
        return ""
    from dry_lint.family_report import FamilyReport

    families = FamilyReport(findings=report.families)
    output = families.markdown() if markdown else families.text()
    if report.family_exclusions:
        clean = escaped if markdown else plain
        output += (
            "\nExcluded family nominations:\n"
            + "\n".join(
                f"- {clean(item.get('nomination_id', 'unknown'))}: {clean(item.get('reason', 'unspecified'))}"
                for item in report.family_exclusions
            )
            + "\n"
        )
    return "\n\n" + output


def as_text(report: Report) -> str:
    if report.model_judging is not None:
        return "\n\n".join(
            [
                "Functions\n" + text_lane(report.lane("function")),
                "Models\n" + text_lane(report.lane("model"), kind="model"),
                *[f"<sub>{escaped(line)}</sub>" for line in model_summary(report)],
            ]
        ) + family_summary(report)
    return text_lane(report) + "\nModels: not checked in this run." + family_summary(report)


def text_lane(report: Report, *, kind: str = "function") -> str:
    lines = [
        f"{f.candidate.new.path}:{f.candidate.new.line}: {f.headline()}\n    {f.advice(report.relatives(f))}"
        for f in report.visible
    ]
    stats = report.stats
    judge = f"judge {report.judge}" if report.judge else "no judge"
    lines.append(
        f"dry-lint: {stats['candidates']} candidate pair(s), {stats['filtered']} skipped by rule, "
        f"{stats['cached']} from the store, {stats['judged']} judged ({judge}), {stats['reported']} reported"
        + (f", {len(report.review_required)} review required" if report.review_required else "")
    )
    if report.deferred:
        lines.append(f"dry-lint: {report.deferred} deferred by the judge budget; these pairs are not cleared")
    if report.judging:
        lines.append(f"judging: {report.judging.line(ranking=kind == 'model')}")
    lines.extend(model_summary(report))
    return "\n".join(lines)


def model_summary(report: Report) -> list[str]:
    if report.model_judging is None:
        return []
    lines = [
        f"models: {report.changed_models} changed, {report.models} in scope; {report.model_judging.line(ranking=True)}"
    ]
    if report.model_debt is not None:
        lines.append(
            "reviewed model debt: " + ", ".join(f"{count} {state}" for state, count in report.model_debt.items())
        )
    return lines


def level(finding: Finding) -> str:
    return "error" if finding.blocking else "warning"


def as_github(report: Report) -> str:
    """Workflow-command annotations, for the job that runs dry-lint."""

    def escape(text: str) -> str:
        return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")

    lines = [
        f"::warning title=dry-lint::{escape('Judging degraded: ' + summary.line())}"
        for summary in (report.judging, report.model_judging)
        if summary and any(spend.failed or spend.error for spend in summary.spend)
    ]
    for f in report.visible:
        new = f.candidate.new
        lines.append(
            f"::{level(f)} file={new.path},line={new.line},endLine={new.end_line},title=dry-lint::"
            f"{escape(f.headline() + ': ' + f.advice(report.relatives(f)))}"
        )
    return "\n".join(lines)


def function_link(function: Function, run: Run) -> str:
    """Link to the measured revision, not a moving branch; local reports keep the full location."""
    url = source_url(function, run)
    label = function.qualname.split("::", 1)[1]
    if function.origin:
        label = f"{function.origin.repository}: {label}"
    return f"[{escaped(label)}]({url})" if url else escaped(function.qualname)


def source_url(function: Function, run: Run) -> str:
    run = function.origin or run
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", run.repository) or not re.fullmatch(r"[a-fA-F0-9]{40}", run.head):
        return ""
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    return (
        f"{server}/{quote(run.repository, safe='/')}/blob/{quote(run.head, safe='')}/"
        f"{quote(function.path, safe='/')}#L{function.line}-L{function.end_line}"
    )


NOTE_SLOT = "<!-- dry-lint note -->"
CLEAN = "<!-- dry-lint clean -->"
BADGES = "https://img.shields.io/badge"
RED, ORANGE, AMBER, GREEN, BLUE, GRAY = "CF222E", "EA580C", "BF8700", "2EA043", "2563EB", "6E7781"
ACTIONS = {
    "existing": "call the existing one",
    "new": "keep the new one; move callers",
    "shared": "extract a shared helper",
}
AUDIT_ACTIONS = {"existing": "keep the second copy", "new": "keep the first copy", "shared": "extract a shared helper"}
LEGEND = {
    "🔴": "fails the check",
    "🟠": "drifted: the copies already behave differently, so check callers before merging them",
    "🟡": "duplicate",
    "⚪": "not judged",
}


def badge(label: str, message: object, color: str) -> str:
    """A static shields.io badge: it renders in any repository, private ones included."""

    def part(text: str) -> str:
        return quote(text.replace("-", "--").replace("_", "__").replace(" ", "_"), safe="")

    return (
        f"![{escaped(f'{label}: {message}')}]({BADGES}/{part(label)}-{part(str(message))}-{color}"
        "?style=flat-square&labelColor=24292F)"
    )


def code(text: str) -> str:
    """A code span, unless the text could close it or break a table cell."""
    return escaped(text) if re.search(r"[`|\n]", text) else f"`{text}`"


def short_paths(first: str, second: str) -> tuple[str, str]:
    """The fewest trailing path segments that tell two files apart: the file names, unless they are the same."""
    a, b = first.split("/"), second.split("/")
    n = 1
    while first != second and n < max(len(a), len(b)) and a[-n:] == b[-n:]:
        n += 1
    return "/".join(a[-n:]), "/".join(b[-n:])


def dot(finding: Finding) -> str:
    if finding.blocking:
        return "🔴"
    if finding.verdict is None:
        return "⚪"
    return "🟠" if finding.verdict.label == "drifted" else "🟡"


def plural(count: int, noun: str) -> str:
    return f"{count:,} {noun}{'' if count == 1 else 's'}"


def as_markdown(report: Report, max_findings: int = 10, report_at: float | None = None) -> str:
    if report.model_judging is None:
        return (
            markdown_lane(report, max_findings, report_at)
            + "\n\n<sub>Models: not checked in this run.</sub>"
            + family_summary(report, markdown=True)
        )
    parts = [MARKER, "### dry-lint · Functions & models", "", NOTE_SLOT, ""]
    if not report.visible:
        parts.append(CLEAN)
    for kind, title in (("function", "Functions"), ("model", "Models")):
        lane = report.lane(kind)
        body = markdown_lane(lane, max_findings, report_at, kind)
        # The sticky has one marker, one ledger insertion point and one overall clean status.
        body = "\n".join(line for line in body.splitlines() if line not in (MARKER, NOTE_SLOT, CLEAN))
        heading, _, content = body.partition("\n")
        status = heading.split(" · ", 1)[-1]
        parts += [f"#### {title} · {status}", content]
        if kind == "model":
            parts += [
                "Model similarity proposes ownership work. Inspect nested types, producers and consumers, and "
                "repository policies before consolidating. Independently evolving contracts may need to stay separate.",
                *model_summary(report),
            ]
    return "\n\n".join(parts) + family_summary(report, markdown=True)


def markdown_lane(
    report: Report, max_findings: int = 10, report_at: float | None = None, kind: str = "function"
) -> str:
    """
    The pull request comment, the job summary and the check run summary. A headline says how bad it is
    at a glance; one row per pair says where and what to do; the folds hold the reasons and the ways out.
    """
    audit, stats, shown = report.repository_wide, report.stats, report.visible
    below = sum(f.verdict is not None and not f.reported and not f.review_required for f in report.findings)
    coverage = " · ".join(part for part in (
        "" if audit else plural(stats["changed"], f"changed {kind}"),
        f"{plural(stats['candidates'], 'pair')} compared",
        f"{plural(stats['judged'] + stats['cached'], 'pair')} judged" if audit else "",
        f"{below} below the report threshold" if below else "",
        f"{stats['filtered']} settled by a rule" if stats["filtered"] else "",
        f"{stats['cached']} from the verdict store" if stats["cached"] else "",
        f"{report.deferred} deferred by the judge budget" if report.deferred else "",
        (f"judge {code(report.judge)}" if report.judge else "no judge") if not report.judging else "",
    ) if part)  # fmt: skip
    footer = [
        "",
        f"<sub>{coverage}</sub>",
        *([f"<sub>{escaped(report.judging.line(ranking=kind == 'model'))}</sub>"] if report.judging else []),
        *[f"<sub>{escaped(line)}</sub>" for line in model_summary(report)],
    ]
    if report.judge is None and kind == "function":
        return "\n".join([
            MARKER, f"### dry-lint · {plural(len(report.findings), 'look-alike pair')}, not judged", "",
            NOTE_SLOT, "",
            "No judge is configured, so these pairs have not been assessed for duplication and nothing is listed. "
            "Set `TYPESAFE_AI_API_KEY`, or configure a judge, to have them judged and reported here.", *footer,
        ])  # fmt: skip
    if not shown:
        return clean(report, audit, report_at, kind)
    blocking = sum(f.blocking for f in shown)
    headline = (
        f"### dry-lint audit · {plural(len(shown), 'duplicated concept')} in existing code"
        if audit
        else f"### dry-lint · {plural(len(shown), 'duplicated concept')}"
    )
    if report.review_required:
        headline = f"### dry-lint · {plural(len(report.review_required), 'pair')}: review required"
    elif kind == "model":
        headline = f"### dry-lint · {plural(len(shown), 'model candidate')} for ownership review"
    if blocking:
        headline += f" · 🔴 {blocking} blocking"
    lead = (
        "A repository-wide audit of code that already exists: each row is one concept implemented twice. "
        "Not introduced by this pull request, and never blocking."
        if audit
        else ""
    )
    if report.review_required:
        lead += " The coding agent must inspect these pairs, then refactor or record a justified pair-specific dismissal. Pairs deferred solely by the spending cap are advisory. No extra judge budget is needed."
    elif kind == "model":
        lead = "These are structural candidates, not confirmed duplicates. Inspect ownership and usage before deciding."
    actions = AUDIT_ACTIONS if audit else ACTIONS
    listed = shown[:max_findings]

    def action(f: Finding) -> str:
        if f.review_required:
            return "inspect callers, refactor or record a reasoned pair-specific dismissal"
        if f.candidate.consolidation:
            return "consider consolidation in " + "; ".join(t.destination for t in f.candidate.consolidation)
        return actions.get(f.verdict.owner, "") if f.verdict else ""

    advised = {action(f) for f in listed}
    common = advised.pop() if len(advised) == 1 else ""
    if common:
        lead += f" **Suggested fix:** {escaped(common)}."
    rows = ["| | Concept | Copies | Verdict |", "| :-: | :-- | :-- | :-- |"]
    details = ["<details><summary><strong>Why these match & how to dismiss</strong></summary>", ""]
    for f in listed:
        new, existing = f.candidate.new, f.candidate.existing
        names = [side.qualname.split("::", 1)[1] for side in (new, existing)]
        concept = code(names[0]) if names[0] == names[1] else f"{code(names[0])} ≈ {code(names[1])}"
        if f.family > 1:
            concept += f" <sub>· {f.family} look-alikes</sub>"
        if kin := report.relatives(f):
            concept += f" <sub>· {plural(len(kin), 'relative')} to fold in</sub>"
        copies = []
        for side, short in zip((new, existing), short_paths(new.path, existing.path), strict=True):
            url = source_url(side, report.run)
            title = side.path.replace('"', "'")
            if side.origin:
                short = f"{side.origin.repository}/{short}"
            copies.append(
                f'[{escaped(f"{short}:{side.line}")}]({url} "{escaped(title)}")'
                if url
                else escaped(f"{side.path}:{side.line}")
            )
        if not audit:
            copies[0] += " <sub>changed</sub>"
        if f.review_required:
            verdict = "**review required**<br><sub>coding agent owns the decision</sub>"
        elif f.verdict:
            hint = [part for part in ("blocks" if f.blocking else "", "" if common else escaped(action(f))) if part]
            verdict = f"**{f.verdict.label}**&nbsp;{f.verdict.score:.2f}" + (
                f"<br><sub>{' · '.join(hint)}</sub>" if hint else ""
            )
        else:
            verdict = f"similarity&nbsp;{f.candidate.similarity:.2f}<br><sub>not judged</sub>"
        rows.append(f"| {dot(f)} | {concept} | {'<br>'.join(copies)} | {verdict} |")
        source = "from the verdict store" if f.cached else "new verdict" if f.verdict else "not judged"
        scored = f"{f.verdict.label} {f.verdict.score:.2f} · " if f.verdict else ""
        drift = " · the copies already behave differently" if f.verdict and f.verdict.label == "drifted" else ""
        suppression = f.suppression()
        details.extend([
            f"{dot(f)} **{concept}** · {scored}similarity {f.candidate.similarity:.2f} · {source}{drift}", "",
            *([f"> {escaped(f.verdict.why)}", ""] if f.verdict and f.verdict.why else []),
            *(["Adopter policies: " + "; ".join(escaped(f"{p.name}: {p.reason}") for p in f.candidate.policies), ""]
              if f.candidate.policies else []),
            *([f"Preferred home: {escaped(action(f))}.", ""] if f.candidate.consolidation else []),
            *([f"Fixing it touches {code(qualified(existing.owner, existing.name))}, which also looks like "
               + ", ".join(f"{function_link(r.candidate.existing, report.run)} ({r.verdict.label} {r.verdict.score:.2f})"
                           for r in kin) + ": consolidate them in the same change.", ""]
              if (kin := report.relatives(f)) else []),
            f"Different concepts? Add to {escaped(short_paths(new.path, existing.path)[0])}:", "",
            *([f"```{'ts' if suppression.startswith('//') else 'python'}", suppression, "```"]
              if not re.search(r"[`\n]", suppression) else [escaped(suppression)]), "",
        ])  # fmt: skip
    legend = " · ".join(f"{icon} {text}" for icon, text in LEGEND.items() if any(dot(f) == icon for f in listed))
    details += [f"<sub>{legend}</sub>", "", "</details>"]
    more = (
        [
            f"<sub>+ {plural(len(shown) - max_findings, 'more pair')} not listed here; the run log lists every one.</sub>",
            "",
        ]
        if len(shown) > max_findings
        else []
    )
    skipped = (
        [
            "",
            f"<details><summary><strong>Settled by a rule ({len(report.filtered)})</strong></summary>",
            "",
            *(
                f"- {code(c.new.qualname)} ~ {code(c.existing.qualname)}: {escaped(c.filtered or '')}"
                for c in report.filtered
            ),
            "",
            "</details>",
        ]
        if report.filtered
        else []
    )
    return "\n".join([
        MARKER, headline, "", NOTE_SLOT, "", lead.strip(), "", *rows, "", *more,
        "", *details, "", "<details><summary><strong>False positive? Choose the scope of your decision</strong></summary>",
        "", *overrides(shown, audit, kind), "", "</details>", *skipped, *footer,
    ])  # fmt: skip


def clean(report: Report, audit: bool, report_at: float | None, kind: str = "function") -> str:
    """No findings: say so plainly, and show how much was checked to earn it."""
    stats = report.stats
    judged = [f for f in report.findings if f.verdict is not None]
    closest = max(judged, key=lambda f: f.verdict.score, default=None)
    counts = [
        *([] if audit else [(f"🔎 Changed {kind}s", f"{report.changed:,}")]),
        *(
            [(f"🗂 {kind.title()}s in the repository" if audit else "🗂 Compared with", plural(report.functions, kind))]
            if report.functions
            else []
        ),
        ("🧶 Look-alike pairs", f"{stats['candidates']:,}"),
    ]
    rows = [
        "| " + " | ".join(label for label, _ in counts) + " |",
        "| " + " | ".join("--:" for _ in counts) + " |",
        "| " + " | ".join(value for _, value in counts) + " |",
    ]
    extra = [
        *([f"| Settled by a rule | {stats['filtered']:,} |"] if stats["filtered"] else []),
        *(
            [
                f"| Cleared by the judge | {len(judged):,}"
                + (f" ({stats['cached']:,} from the verdict store)" if stats["cached"] else "")
                + " |"
            ]
            if judged
            else []
        ),
    ]
    if closest:
        names = [side.qualname.split("::", 1)[1] for side in (closest.candidate.new, closest.candidate.existing)]
        pair = code(names[0]) if names[0] == names[1] else f"{code(names[0])} ≈ {code(names[1])}"
        bar = f" · under the {report_at:.2f} bar" if report_at is not None else ""
        extra.append(f"| Closest call | {pair} · {closest.verdict.label} {closest.verdict.score:.2f}{bar} |")
    if extra:
        rows += ["", "| Review | Result |", "| :-- | --: |", *extra]
    title = (
        "### dry-lint audit · ✨ No duplicated concepts in existing code"
        if audit
        else "### dry-lint · ✨ No duplicated concepts"
    )
    if kind == "model":
        title = "### dry-lint · No unresolved model candidates"
    empty = (
        [f"**Nothing to compare.** This pull request changes no {kind}s.", ""]
        if not audit and not report.changed and not report.changed_models
        else []
    )
    judging = report.judging.line(ranking=kind == "model") if report.judging else f"judge {report.judge}"
    return "\n".join(
        [
            MARKER,
            CLEAN,
            title,
            "",
            NOTE_SLOT,
            "",
            *empty,
            *rows,
            "",
            f"<sub>{escaped(judging)}</sub>",
            *[f"<sub>{escaped(line)}</sub>" for line in model_summary(report)],
        ]
    )


def overrides(shown: list[Finding], audit: bool, kind: str = "function") -> list[str]:
    typescript = [f.suppression().startswith("//") for f in shown]
    prefix = "//" if all(typescript) else "#"
    noun = "model declaration" if kind == "model" else "function"
    where = f"either {noun}" if audit else f"the changed {noun}"
    return [
        "| Scope | Decision |", "| :-- | :-- |",
        f"| this pair | `{prefix} dry-lint: distinct-from <qualified name>` in {where} |",
        f"| one {noun} | `{prefix} dry-lint: ignore` in that {noun} |",
        "| a family of look-alikes | a `patterns` entry under `[tool.dry-lint]`, or in `.dry-lint.toml` |",
        *([] if audit else ["| this pull request only | the `dry-lint: override` label |"]),
        *(["", "In TypeScript and TSX, the comments start with `//`."] if any(typescript) and prefix == "#" else []),
    ]  # fmt: skip


def as_json(report: Report) -> str:
    return report.model_dump_json(indent=2)


def location(path: str, start: int, end: int) -> dict:
    return {"physicalLocation": {"artifactLocation": {"uri": path}, "region": {"startLine": start, "endLine": end}}}


def as_sarif(report: Report) -> str:
    """SARIF 2.1.0, for code scanning: each finding on the changed function, the existing one as related."""
    rules = [
        {"id": "dry-lint/duplicate", "shortDescription": {"text": "Re-implements a function the codebase already has"}},
        {"id": "dry-lint/drifted", "shortDescription": {"text": "Re-implements an existing function, and already behaves differently"}},
        {"id": "dry-lint/candidate", "shortDescription": {"text": "Looks like an existing function; not judged"}},
    ]  # fmt: skip
    results = []
    for f in report.visible:
        new, existing = f.candidate.new, f.candidate.existing
        kind = f.verdict.label if f.verdict else "candidate"
        results.append({
            "ruleId": f"dry-lint/{kind}", "level": level(f) if f.verdict else "note",
            "message": {"text": f"{f.headline()}: {f.advice(report.relatives(f))}"},
            "locations": [location(new.path, new.line, new.end_line)],
            "relatedLocations": [{"id": 1, **location(existing.path, existing.line, existing.end_line),
                                  "message": {"text": existing.qualname}}],
            "partialFingerprints": {"dryLintPair/v1": f.candidate.key},
        })  # fmt: skip
    driver = {
        "name": "dry-lint",
        "version": __version__,
        "informationUri": "https://github.com/gigaverse-app/dry-lint",
        "rules": rules,
    }
    sarif = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{"tool": {"driver": driver}, "results": results}],
    }
    return json.dumps(sarif, indent=2)


def as_check_run(
    report: Report, max_findings: int = 10, warn_only: bool = False, report_at: float | None = None
) -> str:
    """
    The body for `POST /repos/{owner}/{repo}/check-runs`: a failure only for a blocking finding (and not
    `warn_only`), neutral for findings that only warn, success otherwise.
    """
    if warn_only:
        report = report.as_warnings()
    reported = [f for f in report.findings if f.reported or f.review_required]
    failed = any(f.blocking for f in reported) and not warn_only
    title = f"{len(reported)} duplicated concept(s)" if reported else "No duplicated concepts"
    family_proposals = sum(finding.reported for finding in report.families)
    family_unresolved = sum(finding.unresolved for finding in report.families) + sum(
        item.get("kind") != "rule" for item in report.family_exclusions
    )
    if report.families or report.family_exclusions:
        title = f"{len(reported)} pair report(s); {family_proposals} family proposal(s); {family_unresolved} unresolved"
    if report.review_required:
        title = f"{len(report.review_required)} pair(s): review required"
    annotations = [{
        "path": f.candidate.new.path, "start_line": f.candidate.new.line, "end_line": f.candidate.new.end_line,
        "annotation_level": "failure" if level(f) == "error" else "warning", "title": f.headline(),
        "message": f.advice(report.relatives(f)),
    } for f in reported[:50]]  # fmt: skip
    body = {
        "name": "dry-lint",
        "head_sha": report.run.head,
        "status": "completed",
        "conclusion": "failure"
        if failed
        else "neutral"
        if reported or report.deferred or family_proposals or family_unresolved
        else "success",
        "output": {"title": title, "summary": as_markdown(report, max_findings, report_at), "annotations": annotations},
    }
    return json.dumps(body, indent=2)


FORMATS = ("text", "github", "markdown", "json", "sarif", "check-run")
# Formats that can show an operation family: one proposal with its unconfirmed siblings, not pair annotations.
FAMILY_FORMATS = ("text", "json", "markdown", "check-run")
FAMILY_FORMAT_ERROR = "Operation families support text, json, markdown and check-run reports"


def render(report: Report, form: str, settings: Settings, warn_only: bool = False) -> str:
    if (report.families or report.family_exclusions) and form not in FAMILY_FORMATS:
        raise ValueError(FAMILY_FORMAT_ERROR)
    if form not in ("text", "json", "markdown") and any(
        finding.candidate.new.origin
        and (report.repository_wide or finding.candidate.new.origin.repository != report.run.repository)
        for finding in report.findings
    ):
        raise ValueError("A workspace report supports text, json and markdown; annotations belong to one repository")
    if form == "check-run":
        return as_check_run(report, settings.max_findings, warn_only, settings.report_at)
    if warn_only and form != "json":
        report = report.as_warnings()
    if form == "markdown":
        return as_markdown(report, settings.max_findings, settings.report_at)
    return {"text": as_text, "github": as_github, "json": as_json, "sarif": as_sarif}[form](report)
