"""
The report: what a run found, as `report.json`, and every way dry-lint shows it.

Every view renders the same `Report`, so the terminal, the annotations, the pull request comment, SARIF and the
check run always list the same findings in the same order: drifted first, then by score. A judge's reason is
untrusted text (an LLM judge read code from the pull request), so it is flattened, capped and escaped wherever
it is shown, and never rendered as markdown or links.
"""

import json
import re
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
        prefix = "//" if self.candidate.new.path.endswith((".ts", ".tsx", ".mts", ".cts")) else "#"
        parts.append(f"if they are different concepts, add `{prefix} dry-lint: distinct-from {self.candidate.existing.qualname}`")
        return "; ".join(parts)


class Report(Versioned):
    """`report.json`."""

    run: Run = Field(default_factory=Run)
    changed: int = 0
    judge: str | None = Field(default=None, description="The judge (and escalation judge), or None when unjudged.")
    findings: list[Finding] = Field(default_factory=list)
    filtered: list[Candidate] = Field(default_factory=list, description="Pairs a rule settled, with the rule.")

    @classmethod
    def build(cls, findings: list[Finding], settings: Settings, filtered: list[Candidate] = (), run: Run | None = None,
              changed: int = 0, judge: str | None = None) -> "Report":
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
        return cls(run=run or Run(), changed=changed, judge=judge, findings=order, filtered=list(filtered))

    @property
    def visible(self) -> list[Finding]:
        """Unjudged candidates, and judged pairs at or above the report threshold."""
        return [f for f in self.findings if f.verdict is None or f.reported]

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


OVERRIDES = (
    "False positive? Add `# dry-lint: distinct-from <qualified name>` to the new function (this pair), "
    "`# dry-lint: ignore` to a function (that function), a `patterns` entry under `[tool.dry-lint]` (a family), "
    "or the `dry-lint: override` label to the pull request (this pull request only). "
    "For TypeScript/TSX, use `//` instead of `#`; configuration can also live in `.dry-lint.toml`."
)


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
    label = f"`{function.qualname.replace('`', '')}`"
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", run.repository) or not re.fullmatch(r"[a-fA-F0-9]{40}", run.head):
        return label
    path = quote(function.path, safe="/")
    return f"[{label}](https://github.com/{run.repository}/blob/{run.head}/{path}#L{function.line}-L{function.end_line})"


def as_markdown(report: Report, max_findings: int = 10) -> str:
    if report.judge is None:
        return (f"{MARKER}\n### dry-lint\n\nNo judge is configured, so the {len(report.findings)} look-alike pair(s) "
                "found are shown only as annotations. Set `TYPESAFE_AI_API_KEY`, or configure a judge, to have them "
                "judged and reported here.")
    shown = report.visible
    if not shown:
        return f"{MARKER}\n### dry-lint\n\nNo duplicated concepts found in the changed functions."
    rows = ["| Changed function | Looks like | Verdict | Suggestion |", "| --- | --- | --- | --- |"]
    for f in shown[:max_findings]:
        if f.verdict:
            verdict = f"**{'blocking ' if f.blocking else ''}{f.verdict.label}** {f.verdict.score:.2f}"
            suggestion = "; ".join(part for part in (OWNERS.get(f.verdict.owner, ""), escaped(f.verdict.why)) if part)
        else:
            verdict, suggestion = f"similarity {f.candidate.similarity:.2f}", "not judged"
        if f.family > 1:
            suggestion += f" ({f.family} look-alikes)"
        rows.append(f"| {function_link(f.candidate.new, report.run)} | "
                    f"{function_link(f.candidate.existing, report.run)} | {verdict} | {suggestion} |")
    more = ["", f"And {len(shown) - max_findings} more; run `dry-lint check` to see them all."] \
        if len(shown) > max_findings else []
    skipped = [f"<details><summary>Not reported ({len(report.filtered)} settled by a rule)</summary>", "",
               *(f"- `{c.new.qualname}` ~ `{c.existing.qualname}`: {escaped(c.filtered or '')}" for c in report.filtered),
               "", "</details>"] if report.filtered else []
    blocking = sum(f.blocking for f in shown)
    verdict_line = [f"{blocking} of them are blocking: judged duplicates at or above `fail_at`, which fail the check.", ""] \
        if blocking else []
    return "\n".join([
        MARKER, "### dry-lint", "",
        f"{len(shown)} changed function(s) look like code that already exists. One concept should have one "
        "implementation: reuse it, or parameterize the difference.", "", *verdict_line, *rows, *more, "",
        OVERRIDES,
        *([""] + skipped if skipped else []),
    ])


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


def as_check_run(report: Report, max_findings: int = 10, warn_only: bool = False) -> str:
    """
    The body for `POST /repos/{owner}/{repo}/check-runs`: a failure only for a blocking finding (and not
    `warn_only`), neutral for findings that only warn, success otherwise.
    """
    reported = [f for f in report.findings if f.reported]
    failed = any(f.blocking for f in reported) and not warn_only
    title = f"{len(reported)} duplicated concept(s)" if reported else "No duplicated concepts"
    annotations = [{
        "path": f.candidate.new.path, "start_line": f.candidate.new.line, "end_line": f.candidate.new.end_line,
        "annotation_level": "failure" if level(f) == "error" else "warning", "title": f.headline(), "message": f.advice(),
    } for f in reported[:50]]  # fmt: skip
    body = {"name": "dry-lint", "head_sha": report.run.head, "status": "completed",
            "conclusion": "failure" if failed else "neutral" if reported else "success",
            "output": {"title": title, "summary": as_markdown(report, max_findings), "annotations": annotations}}
    return json.dumps(body, indent=2)


FORMATS = ("text", "github", "markdown", "json", "sarif", "check-run")


def render(report: Report, form: str, settings: Settings, warn_only: bool = False) -> str:
    if form == "markdown":
        return as_markdown(report, settings.max_findings)
    if form == "check-run":
        return as_check_run(report, settings.max_findings, warn_only)
    return {"text": as_text, "github": as_github, "json": as_json, "sarif": as_sarif}[form](report)
