"""Findings, and the three ways dry-lint shows them: terminal text, GitHub annotations, a pull request comment."""

import json

from pydantic import BaseModel

from dry_lint.detector import Candidate
from dry_lint.settings import Settings
from dry_lint.store import Verdict

MARKER = "<!-- dry-lint -->"
OWNERS = {
    "existing": "call the existing function",
    "new": "move callers of the existing function to the new one",
    "shared": "extract a shared helper both can call",
}


class Finding(BaseModel):
    """A candidate pair and, when it was judged, the verdict and whether it came from the store."""

    candidate: Candidate
    verdict: Verdict | None = None
    cached: bool = False

    def reported(self, settings: Settings) -> bool:
        return self.verdict is not None and self.verdict.label != "separate" and self.verdict.score >= settings.report_at

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
                parts.append(self.verdict.why)
        parts.append(f"similarity {self.candidate.similarity:.2f}")
        parts.append(f"if they are different concepts, add `# dry-lint: distinct-from {self.candidate.existing.qualname}`")
        return "; ".join(parts)


def visible(findings: list[Finding], settings: Settings) -> list[Finding]:
    """Unjudged candidates, and judged pairs at or above the report threshold."""
    return [f for f in findings if f.verdict is None or f.reported(settings)]


def as_text(findings: list[Finding], settings: Settings, skipped: list[str]) -> str:
    shown = visible(findings, settings)
    lines = [f"{f.candidate.new.path}:{f.candidate.new.line}: {f.headline()}\n    {f.advice()}" for f in shown]
    judged = sum(f.verdict is not None for f in findings)
    lines.append(f"dry-lint: {len(findings)} candidate pair(s), {judged} judged, {len(shown)} shown, {len(skipped)} skipped by rule")
    return "\n".join(lines)


def as_github(findings: list[Finding], settings: Settings) -> str:
    def escape(text: str) -> str:
        return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")

    lines = []
    for f in visible(findings, settings):
        level = "warning" if f.verdict is None or f.verdict.label == "duplicate" else "error"
        new = f.candidate.new
        lines.append(f"::{level} file={new.path},line={new.line},endLine={new.end_line},title=dry-lint::"
                     f"{escape(f.headline() + ': ' + f.advice())}")
    return "\n".join(lines)


def as_markdown(findings: list[Finding], settings: Settings) -> str:
    shown = visible(findings, settings)
    if not shown:
        return f"{MARKER}\n### dry-lint\n\nNo duplicated concepts found in the changed functions."
    rows = ["| Changed function | Looks like | Verdict | Suggestion |", "| --- | --- | --- | --- |"]
    for f in shown:
        verdict = f"{f.verdict.label} {f.verdict.score:.2f}" if f.verdict else f"similarity {f.candidate.similarity:.2f}"
        suggestion = OWNERS.get(f.verdict.owner, "") if f.verdict else "not judged"
        if f.verdict and f.verdict.why:
            suggestion = f"{suggestion}. {f.verdict.why}" if suggestion else f.verdict.why
        rows.append(f"| `{f.candidate.new.qualname}` | `{f.candidate.existing.qualname}` | {verdict} | {suggestion} |")
    return "\n".join([
        MARKER, "### dry-lint", "",
        f"{len(shown)} changed function(s) look like code that already exists. One concept should have one "
        "implementation: reuse it, or parameterize the difference.", "", *rows, "",
        "Different concepts after all? Add `# dry-lint: distinct-from <qualified name>` to the new function.",
    ])


def as_json(findings: list[Finding], settings: Settings) -> str:
    return json.dumps([{**f.model_dump(mode="json"), "reported": f.reported(settings)} for f in findings], indent=2)
