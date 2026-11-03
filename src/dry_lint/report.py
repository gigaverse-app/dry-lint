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
from dry_lint.models import Candidate, Function, Run, Verdict, Versioned
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


def escaped(text: str) -> str:
    """Plain text that markdown shows as typed: no links, emphasis, HTML or table breaks."""
    return re.sub(r"([\\`*_{}\[\]()<>#!|~])", r"\\\1", plain(text))


class Finding(BaseModel):
    """A proposed pair and, when it was judged, the verdict and whether it came from the store."""

    candidate: Candidate
    verdict: Verdict | None = None
    cached: bool = False
    family: int = Field(default=1, description="How many look-alikes were proposed for the same changed function.")
    reported: bool = Field(default=False, description="Judged a duplicate at or above report_at.")
    blocking: bool = Field(default=False, description="Reported, and at or above fail_at: fails the check.")

    def headline(self) -> str:
        new, existing = self.candidate.new, self.candidate.existing
        kind = self.verdict.label if self.verdict else "candidate"
        return f"{new.qualname.split('::')[1]} looks like {existing.qualname} ({kind})"

    def advice(self) -> str:
        parts = []
        if self.verdict:
            parts.append(f"judge {self.verdict.score:.2f}" + (" (cached)" if self.cached else ""))
            if self.verdict.label == "drifted":
                parts.append("the two already behave differently")
            if self.verdict.owner in OWNERS:
                parts.append(OWNERS[self.verdict.owner])
            if self.verdict.why:
                parts.append(plain(self.verdict.why))
        parts.append(f"similarity {self.candidate.similarity:.2f}")
        if self.family > 1:
            parts.append(f"{self.family} look-alikes")
        parts.append(f"if they are different concepts, add `{self.suppression()}`")
        return "; ".join(parts)

    def suppression(self) -> str:
        prefix = "//" if self.candidate.new.path.endswith((".ts", ".tsx", ".mts", ".cts")) else "#"
        return f"{prefix} dry-lint: distinct-from {self.candidate.existing.qualname}"


class Report(Versioned):
    """`report.json`."""

    run: Run = Field(default_factory=Run)
    changed: int = 0
    functions: int = Field(default=0, description="How many functions the repository has: what changed ones meet.")
    scope: Literal["change", "repository"] = Field(default="change", description="`check` or `scan`.")
    judge: str | None = Field(default=None, description="The judge (and escalation judge), or None when unjudged.")
    findings: list[Finding] = Field(default_factory=list)
    filtered: list[Candidate] = Field(default_factory=list, description="Pairs a rule settled, with the rule.")

    @classmethod
    def build(cls, findings: list[Finding], settings: Settings, filtered: list[Candidate] = (), run: Run | None = None,
              changed: int = 0, judge: str | None = None, functions: int = 0,
              scope: Literal["change", "repository"] = "change") -> "Report":
        family: dict[str, int] = {}
        for f in findings:
            family[f.candidate.new.qualname] = family.get(f.candidate.new.qualname, 0) + 1
        def duplicate_at(f: Finding, threshold: float) -> bool:
            return f.verdict is not None and f.verdict.label != "separate" and f.verdict.score >= threshold

        marked = [
            f.model_copy(update={"family": family[f.candidate.new.qualname], "reported": duplicate_at(f, settings.report_at),
                                 "blocking": duplicate_at(f, max(settings.report_at, settings.fail_at))})
            for f in findings
        ]  # fmt: skip
        order = sorted(marked, key=lambda f: (not f.blocking, not f.reported,
                                              f.verdict is None or f.verdict.label != "drifted",
                                              -(f.verdict.score if f.verdict else f.candidate.similarity)))
        return cls(run=run or Run(), changed=changed, functions=functions, scope=scope, judge=judge, findings=order,
                   filtered=list(filtered))

    @property
    def visible(self) -> list[Finding]:
        """Unjudged candidates, and judged pairs at or above the report threshold."""
        return [f for f in self.findings if f.verdict is None or f.reported]

    def as_warnings(self) -> "Report":
        return self.model_copy(update={"findings": [f.model_copy(update={"blocking": False}) for f in self.findings]})

    @property
    def repository_wide(self) -> bool:
        """A `scan` of the whole repository rather than a `check` of a change."""
        return self.scope == "repository"

    @property
    def stats(self) -> dict[str, int]:
        judged = [f for f in self.findings if f.verdict is not None]
        return {"changed": self.changed, "candidates": len(self.findings) + len(self.filtered),
                "filtered": len(self.filtered), "cached": sum(f.cached for f in judged),
                "judged": sum(not f.cached for f in judged), "reported": sum(f.reported for f in self.findings)}


def as_text(report: Report) -> str:
    lines = [f"{f.candidate.new.path}:{f.candidate.new.line}: {f.headline()}\n    {f.advice()}" for f in report.visible]
    stats = report.stats
    judge = f"judge {report.judge}" if report.judge else "no judge"
    lines.append(f"dry-lint: {stats['candidates']} candidate pair(s), {stats['filtered']} skipped by rule, "
                 f"{stats['cached']} from the store, {stats['judged']} judged ({judge}), {stats['reported']} reported")
    return "\n".join(lines)


def level(finding: Finding) -> str:
    return "error" if finding.blocking else "warning"


def as_github(report: Report) -> str:
    """Workflow-command annotations, for the job that runs dry-lint."""

    def escape(text: str) -> str:
        return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")

    lines = []
    for f in report.visible:
        new = f.candidate.new
        lines.append(f"::{level(f)} file={new.path},line={new.line},endLine={new.end_line},title=dry-lint::"
                     f"{escape(f.headline() + ': ' + f.advice())}")
    return "\n".join(lines)


def function_link(function: Function, run: Run) -> str:
    """Link to the measured revision, not a moving branch; local reports keep the full location."""
    url = source_url(function, run)
    label = function.qualname.split('::', 1)[1]
    if function.origin:
        label = f"{function.origin.repository}: {label}"
    return f"[{escaped(label)}]({url})" if url else escaped(function.qualname)


def source_url(function: Function, run: Run) -> str:
    run = function.origin or run
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", run.repository) or not re.fullmatch(r"[a-fA-F0-9]{40}", run.head):
        return ""
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    return (f"{server}/{quote(run.repository, safe='/')}/blob/{quote(run.head, safe='')}/"
            f"{quote(function.path, safe='/')}#L{function.line}-L{function.end_line}")


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

    return (f"![{escaped(f'{label}: {message}')}]({BADGES}/{part(label)}-{part(str(message))}-{color}"
            "?style=flat-square&labelColor=24292F)")


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
    """
    The pull request comment, the job summary and the check run summary. A headline and badges say how bad it is
    at a glance; one row per pair says where and what to do; the folds hold the reasons and the ways out.
    """
    audit, stats, shown = report.repository_wide, report.stats, report.visible
    below = sum(f.verdict is not None and not f.reported for f in report.findings)
    coverage = " · ".join(part for part in (
        "" if audit else plural(stats["changed"], "changed function"),
        f"{plural(stats['candidates'], 'pair')} compared",
        f"{below} below the report threshold" if below else "",
        f"{stats['filtered']} settled by a rule" if stats["filtered"] else "",
        f"{stats['cached']} from the verdict store" if stats["cached"] else "",
        f"judge {code(report.judge)}" if report.judge else "no judge",
    ) if part)  # fmt: skip
    footer = ["", f"<sub>{coverage}</sub>"]
    scope = [] if audit else [badge("changed functions", stats["changed"], GRAY)]
    if report.judge is None:
        return "\n".join([
            MARKER, f"### dry-lint · {plural(len(report.findings), 'look-alike pair')}, not judged", "",
            " ".join([badge("look-alikes", len(report.findings), GRAY), *scope, badge("judge", "none", GRAY)]), "",
            NOTE_SLOT, "",
            "No judge is configured, so these pairs have not been assessed for duplication and nothing is listed. "
            "Set `TYPESAFE_AI_API_KEY`, or configure a judge, to have them judged and reported here.", *footer,
        ])  # fmt: skip
    judge = badge("judge", report.judge, GRAY)
    if not shown:
        return clean(report, audit, scope, judge, report_at)
    blocking = sum(f.blocking for f in shown)
    drifted = sum(f.verdict is not None and f.verdict.label == "drifted" for f in shown)
    headline = (f"### dry-lint audit · {plural(len(shown), 'duplicated concept')} in existing code" if audit else
                f"### dry-lint · {plural(len(shown), 'duplicated concept')}")
    badges = [badge("duplicated concepts", len(shown), RED if blocking else AMBER),
              *([badge("blocking", blocking, RED)] if blocking else []),
              *([badge("drifted", drifted, ORANGE)] if drifted else []),
              *(scope or [badge("pairs judged", stats["cached"] + stats["judged"], GRAY)]), judge]
    lead = ("A repository-wide audit of code that already exists: each row is one concept implemented twice. "
            "Not introduced by this pull request, and never blocking." if audit else
            "Each row is one concept implemented twice: a function this pull request changed, and code the "
            "repository already has. Reuse it, or parameterize the difference.")
    actions = AUDIT_ACTIONS if audit else ACTIONS
    listed = shown[:max_findings]
    advised = {actions.get(f.verdict.owner, "") if f.verdict else "" for f in listed}
    common = advised.pop() if len(advised) == 1 else ""
    if common:
        lead += f" The judge's fix for every pair listed: **{common}**."
    rows = ["| | Concept | Copies | Verdict |", "| :-: | :-- | :-- | :-- |"]
    details = ["<details><summary><strong>Reasons, and a one-line dismissal for each</strong></summary>", ""]
    for f in listed:
        new, existing = f.candidate.new, f.candidate.existing
        names = [side.qualname.split("::", 1)[1] for side in (new, existing)]
        concept = code(names[0]) if names[0] == names[1] else f"{code(names[0])} ≈ {code(names[1])}"
        if f.family > 1:
            concept += f" <sub>· {f.family} look-alikes</sub>"
        copies = []
        for side, short in zip((new, existing), short_paths(new.path, existing.path), strict=True):
            url = source_url(side, report.run)
            title = side.path.replace('"', "'")
            if side.origin:
                short = f"{side.origin.repository}/{short}"
            copies.append(f'[{escaped(f"{short}:{side.line}")}]({url} "{escaped(title)}")' if url
                          else escaped(f"{side.path}:{side.line}"))
        if not audit:
            copies[0] += " <sub>changed</sub>"
        if f.verdict:
            hint = [part for part in ("blocks" if f.blocking else "", "" if common else actions.get(f.verdict.owner, ""))
                    if part]
            verdict = f"**{f.verdict.label}**&nbsp;{f.verdict.score:.2f}" + (f"<br><sub>{' · '.join(hint)}</sub>" if hint else "")
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
            f"Different concepts? Add to {escaped(short_paths(new.path, existing.path)[0])}:", "",
            *([f"```{'ts' if suppression.startswith('//') else 'python'}", suppression, "```"]
              if not re.search(r"[`\n]", suppression) else [escaped(suppression)]), "",
        ])  # fmt: skip
    details.append("</details>")
    legend = " · ".join(f"{icon} {text}" for icon, text in LEGEND.items() if any(dot(f) == icon for f in listed))
    more = [f"<sub>+ {plural(len(shown) - max_findings, 'more pair')} not listed here; the run log lists every one.</sub>",
            ""] if len(shown) > max_findings else []
    skipped = ["", f"<details><summary><strong>Settled by a rule ({len(report.filtered)})</strong></summary>", "",
               *(f"- {code(c.new.qualname)} ~ {code(c.existing.qualname)}: {escaped(c.filtered or '')}"
                 for c in report.filtered), "", "</details>"] if report.filtered else []
    return "\n".join([
        MARKER, headline, "", " ".join(badges), "", NOTE_SLOT, "", lead, "", *rows, "", *more, f"<sub>{legend}</sub>",
        "", *details, "", "<details><summary><strong>False positive? Choose the scope of your decision</strong></summary>",
        "", *overrides(shown, audit), "", "</details>", *skipped, *footer,
    ])  # fmt: skip


def clean(report: Report, audit: bool, scope: list[str], judge: str, report_at: float | None) -> str:
    """No findings: say so plainly, and show how much was checked to earn it."""
    stats = report.stats
    judged = [f for f in report.findings if f.verdict is not None]
    closest = max(judged, key=lambda f: f.verdict.score, default=None)
    if audit:
        lead = ("**No concept is implemented twice.** The judge or a rule cleared every look-alike pair in this audit."
                if report.findings or report.filtered else "**No two functions in the repository look alike.**")
    elif not report.changed:
        lead = "**Nothing to compare.** This pull request changes no functions."
    elif report.findings or report.filtered:
        lead = (f"**Every changed function is the only implementation of its concept.** "
                f"{plural(stats['candidates'], 'look-alike pair')} came up; the judge or a rule cleared every one.")
    else:
        against = f" any of the {report.functions:,} functions in the repository" if report.functions else " anything"
        lead = (f"**Every changed function is the only implementation of its concept.** None of the "
                f"{plural(report.changed, 'changed function')} looks like{against}.")
    rows = ["| Check | Result |", "| :-- | --: |",
            *([] if audit else [f"| Changed functions | {report.changed:,} |"]),
            *([f"| {'Functions in the repository' if audit else 'Compared with'} | {plural(report.functions, 'function')} |"]
              if report.functions else []),
            f"| Look-alike pairs | {stats['candidates']:,} |",
            *([f"| Settled by a rule | {stats['filtered']:,} |"] if stats["filtered"] else []),
            *([f"| Cleared by the judge | {len(judged):,}"
               + (f" ({stats['cached']:,} from the verdict store)" if stats["cached"] else "") + " |"] if judged else [])]
    if closest:
        names = [side.qualname.split("::", 1)[1] for side in (closest.candidate.new, closest.candidate.existing)]
        pair = code(names[0]) if names[0] == names[1] else f"{code(names[0])} ≈ {code(names[1])}"
        bar = f" · under the {report_at:.2f} bar" if report_at is not None else ""
        rows.append(f"| Closest call | {pair} · {closest.verdict.label} {closest.verdict.score:.2f}{bar} |")
    badges = [badge("duplicated concepts", "none ✓", GREEN), *scope,
              *([badge("compared with" if not audit else "functions", f"{report.functions:,}", BLUE)]
                if report.functions else []), judge]
    title = "### dry-lint audit · ✨ No duplicated concepts in existing code" if audit else \
        "### dry-lint · ✨ No duplicated concepts"
    return "\n".join([MARKER, CLEAN, title, "", " ".join(badges), "", NOTE_SLOT, "", lead, "", *rows])


def overrides(shown: list[Finding], audit: bool) -> list[str]:
    typescript = [f.suppression().startswith("//") for f in shown]
    prefix = "//" if all(typescript) else "#"
    where = "either function" if audit else "the changed function"
    return [
        "| Scope | Decision |", "| :-- | :-- |",
        f"| this pair | `{prefix} dry-lint: distinct-from <qualified name>` in {where} |",
        f"| one function | `{prefix} dry-lint: ignore` in that function |",
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
            "message": {"text": f"{f.headline()}: {f.advice()}"},
            "locations": [location(new.path, new.line, new.end_line)],
            "relatedLocations": [{"id": 1, **location(existing.path, existing.line, existing.end_line),
                                  "message": {"text": existing.qualname}}],
            "partialFingerprints": {"dryLintPair/v1": f.candidate.key},
        })  # fmt: skip
    driver = {"name": "dry-lint", "version": __version__, "informationUri": "https://github.com/gigaverse-app/dry-lint",
              "rules": rules}
    sarif = {"$schema": "https://json.schemastore.org/sarif-2.1.0.json", "version": "2.1.0",
             "runs": [{"tool": {"driver": driver}, "results": results}]}
    return json.dumps(sarif, indent=2)


def as_check_run(report: Report, max_findings: int = 10, warn_only: bool = False, report_at: float | None = None) -> str:
    """
    The body for `POST /repos/{owner}/{repo}/check-runs`: a failure only for a blocking finding (and not
    `warn_only`), neutral for findings that only warn, success otherwise.
    """
    if warn_only:
        report = report.as_warnings()
    reported = [f for f in report.findings if f.reported]
    failed = any(f.blocking for f in reported) and not warn_only
    title = f"{len(reported)} duplicated concept(s)" if reported else "No duplicated concepts"
    annotations = [{
        "path": f.candidate.new.path, "start_line": f.candidate.new.line, "end_line": f.candidate.new.end_line,
        "annotation_level": "failure" if level(f) == "error" else "warning", "title": f.headline(), "message": f.advice(),
    } for f in reported[:50]]  # fmt: skip
    body = {"name": "dry-lint", "head_sha": report.run.head, "status": "completed",
            "conclusion": "failure" if failed else "neutral" if reported else "success",
            "output": {"title": title, "summary": as_markdown(report, max_findings, report_at), "annotations": annotations}}
    return json.dumps(body, indent=2)


FORMATS = ("text", "github", "markdown", "json", "sarif", "check-run")


def render(report: Report, form: str, settings: Settings, warn_only: bool = False) -> str:
    if form not in ("text", "json", "markdown") and any(
        side.origin for finding in report.findings for side in (finding.candidate.new, finding.candidate.existing)
    ):
        raise ValueError("A workspace report supports text, json and markdown; annotations belong to one repository")
    if form == "check-run":
        return as_check_run(report, settings.max_findings, warn_only, settings.report_at)
    if warn_only and form != "json":
        report = report.as_warnings()
    if form == "markdown":
        return as_markdown(report, settings.max_findings, settings.report_at)
    return {"text": as_text, "github": as_github, "json": as_json, "sarif": as_sarif}[form](report)
