"""GitHub links for every repo; public-only, model-free source comparisons for the static viewer."""

import base64
import json
import os
import re
from typing import TYPE_CHECKING
from urllib.parse import quote, urlsplit

import httpx

from dry_lint.evidence import PairEvidence, SourceReference
from dry_lint.extractor_capabilities import capabilities, extractor_class_for
from dry_lint.functions import validate_source
from dry_lint.ledger import PullLedger
from dry_lint.models import Function, Run, Verdict, qualified
from dry_lint.plugins import plugin_class
from dry_lint.report import Report, escaped

if TYPE_CHECKING:
    from dry_lint.sticky import GitHub

VIEWER = "https://gigaverse-app.github.io/dry-lint/compare/"
MAX_PAIRS = 5
MAX_LINK = 12_000
MAX_RULES = 5
WHY_LIMIT = 600

# Each state's heading, in the order the table shows them, and what it means for the reader.
GROUPS = {
    "open": ("🔴 Still duplicated", "the judge found one concept at or above the reporting bar"),
    "not-reported": (
        "⚪ No longer reported",
        "absent from the latest scan; removal or consolidation is not established",
    ),
    "below threshold": ("🟡 Near misses", "judged one concept, but under the {bar} reporting bar, so not counted"),
    "deferred": ("⏳ Not judged yet", "the budget ran out before the judge reached them"),
    "unjudged": ("⏳ Not judged yet", "no judge answered"),
    "separate": ("⚪ Different concepts", "the judge found two concepts that only look alike"),
    "dismissed": ("🏷️ Dismissed", "marked as different concepts in the code"),
}
MODEL = re.compile(r"(claude|gemini)-([a-z]+-)?(\d+(?:[.-]\d+)*)(-[a-z]+)?")


def model_name(name: str) -> str:
    """A judge as a reader knows it: `Claude Sonnet 5.5` for `anthropic:dry-v1:claude-sonnet-5-5`, else its plugin."""
    if match := MODEL.search(name):
        family, tier, version, variant = match.groups()
        words = [
            family,
            tier.rstrip("-") if tier else "",
            version.replace("-", "."),
            variant.lstrip("-") if variant else "",
        ]
        return " ".join(word.capitalize() if word[:1].isalpha() else word for word in words if word)
    plugin, _, rest = name.partition(":")
    # A command judge is the program it runs: `command:claude` is `claude`.
    return rest.split(":", 1)[0] if plugin == "command" and rest else plugin.capitalize()


def decided_by(verdict: Verdict) -> str:
    first = model_name(f"{verdict.judge}:{verdict.judge_version}")
    return f"{model_name(verdict.second_opinion)}, rechecking {first}" if verdict.second_opinion else first


def reason(verdict: Verdict, evidence: PairEvidence) -> str:
    """The judge's reason with its NEW and EXISTING placeholders replaced by the two functions' names."""
    names = {"NEW": evidence.a.qualified, "EXISTING": evidence.b.qualified}
    return re.sub(r"\b(NEW|EXISTING)\b", lambda match: names[match.group(1)], verdict.why)


def viewer_link(
    url: str,
    evidence: PairEvidence,
    result: SourceReference | None,
    state: str,
    diff: str,
    helpers: list[SourceReference] = (),
) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return ""
    payload = {
        "schema": 2,
        "evidence": evidence.model_dump(),
        "result": result.model_dump() if result else None,
        "helpers": [helper.model_dump() for helper in helpers],
        "state": state,
        "diff": diff,
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    link = f"{url}#v2={encoded}"
    return link if len(link) <= MAX_LINK else ""


class Comparisons:
    def __init__(self, github: "GitHub", repository: str, head: str, viewer: str, number: int | None = None):
        self.github, self.repository, self.head, self.viewer, self.number = github, repository, head, viewer, number
        self.public: dict[str, bool] = {}
        self.files: dict[tuple[str, str, str], list[Function] | None] = {}
        self.source_text: dict[tuple[str, str, str], str] = {}
        self.extractors: dict[tuple[str, str, str], object] = {}
        self.base: str | None = None

    def pull_diff(self, server: str) -> str:
        """The pull request's own diff, base...head; empty when its base cannot be read or it has no changes."""
        if self.base is None:
            self.base = ""
            if self.number is not None:
                try:
                    self.base = str(self.github.pull(self.repository, self.number)["base"]["sha"])
                except (httpx.HTTPError, ValueError, KeyError, TypeError):
                    pass
        if not all(re.fullmatch(r"[a-fA-F0-9]{40}", sha) for sha in (self.base, self.head)) or self.base == self.head:
            return ""
        return f"{server}/{self.repository}/compare/{self.base}...{self.head}"

    def is_public(self, repository: str) -> bool:
        if repository not in self.public:
            try:
                response = self.github.client.get(f"/repos/{repository}")
                response.raise_for_status()
                metadata = response.json()
                self.public[repository] = metadata.get("visibility") == "public" and metadata.get("private") is False
            except (httpx.HTTPError, ValueError):
                self.public[repository] = False
        return self.public[repository]

    def current(self, source: SourceReference) -> tuple[bool, SourceReference | None]:
        """Only resolve an unchanged symbol identity; failed reads are not evidence that a symbol was deleted."""
        if source.repository != self.repository or not re.fullmatch(r"[a-fA-F0-9]{40}", self.head):
            return False, None
        cls = extractor_class_for(source.path)
        if cls is None:
            return False, None
        key = (source.repository, self.head, source.path)
        if key not in self.files:
            try:
                extractor = cls()
                self.extractors[key] = extractor
                response = self.github.client.get(
                    f"/repos/{source.repository}/contents/{quote(source.path, safe='/')}",
                    params={"ref": self.head},
                    headers={"Accept": "application/vnd.github.raw+json"},
                )
                if response.status_code == 404:
                    self.files[key] = []
                else:
                    response.raise_for_status()
                    validate_source(extractor, source.path, response.text)
                    self.files[key] = extractor.functions(source.path, response.text)
                    if model := capabilities(extractor).model_extractor:
                        self.files[key].extend(
                            plugin_class("extractors", model)().functions(source.path, response.text)
                        )
                    self.source_text[key] = response.text
            except (httpx.HTTPError, ValueError, SyntaxError, ImportError, TypeError):
                self.files[key] = None
        functions = self.files[key]
        if functions is None:
            return False, None
        found = [f for f in functions if f.name == source.name and f.owner == source.owner]
        if len(found) > 1:
            return False, None
        return True, SourceReference.of(found[0], Run(repository=self.repository, head=self.head)) if found else None

    def helpers(self, result: SourceReference) -> list[SourceReference]:
        key = (result.repository, result.revision, result.path)
        if key not in self.source_text:
            return []
        caller = next(function for function in self.files[key] if function.line == result.line)
        helpers = getattr(self.extractors[key], "comparison_helpers", None)
        if helpers is None or caller.declaration is not None:
            return []
        return [
            SourceReference.of(function, Run(repository=result.repository, head=result.revision))
            for function in helpers(self.source_text[key], caller)
        ]

    def links(self, evidence: PairEvidence, state: str) -> str:
        a, b = evidence.a, evidence.b
        links = [f"[A]({a.url()})", f"[B]({b.url()})"]
        server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
        diff = ""
        if a.repository == self.repository and re.fullmatch(r"[a-fA-F0-9]{40}", self.head) and a.revision != self.head:
            diff = f"{server}/{self.repository}/compare/{a.revision}...{self.head}"
            links.append(f"[Changes since finding]({diff})")
        # Every origin must be explicitly public. Internal, private, unknown and Enterprise stay on GitHub.
        if (
            not self.viewer
            or server != "https://github.com"
            or not all(self.is_public(repo) for repo in dict.fromkeys((self.repository, a.repository, b.repository)))
        ):
            return " · ".join(links)
        result = None
        if state == "not-reported":
            resolved = [self.current(source) for source in (a, b)]
            survivors = [reference for known, reference in resolved if known and reference]
            if all(known for known, _ in resolved) and len(survivors) == 1:
                result = survivors[0]
        # Found at the reviewed commit, the pair has no changes since; the pull request's diff is the context.
        if url := viewer_link(
            self.viewer, evidence, result, state, diff or self.pull_diff(server), self.helpers(result) if result else []
        ):
            links.append(f"[{'Three-way view' if result else 'Compare sources'}]({url})")
        return " · ".join(links)

    def render(self, ledger: PullLedger, reports: list[Report]) -> str:
        entries = {key: (pair.evidence, pair.state) for key, pair in ledger.pairs.items() if pair.evidence}
        for report in reports:
            for finding in report.findings:
                if finding.candidate.key not in entries and (evidence := PairEvidence.of(finding, report.run)):
                    state = (
                        "deferred"
                        if finding.deferred
                        else "open"
                        if finding.reported
                        else "unjudged"
                        if finding.verdict is None
                        else "separate"
                        if finding.verdict.label == "separate"
                        else "below threshold"
                    )
                    entries[finding.candidate.key] = (evidence, state)
        if not entries:
            return ""
        order = list(GROUPS)
        ordered = sorted(
            entries.items(), key=lambda entry: order.index(entry[1][1]) if entry[1][1] in GROUPS else len(order)
        )
        judging = next((r.judging for r in reversed(reports) if r.judging), None)
        bar = f"{judging.report_at:.2f}" if judging else "configured"
        lines = [
            "<details><summary><strong>Compare the code and recorded judgments</strong></summary>",
            "",
            "Every pair the detector proposed, grouped by the outcome. The **duplicate score** is the judge's "
            "estimate, from 0 to 1, that the two are one concept; only pairs at or above the reporting bar count "
            "as still duplicated.",
        ]
        shown = ordered[:MAX_PAIRS]
        for state in dict.fromkeys(state for _, (_, state) in shown):
            group = [
                (evidence, links) for _, (evidence, s) in shown if s == state for links in [self.links(evidence, state)]
            ]
            heading, meaning = GROUPS.get(state, (state, ""))
            count = sum(s == state for _, (_, s) in entries.items())
            lines += [
                "",
                f"**{heading} ({count})**" + (f": {meaning.format(bar=bar)}." if meaning else ""),
                "",
                "| Pair | Duplicate score | Decided by | Why | Sources |",
                "| :-- | --: | :-- | :-- | :-- |",
            ]
            for evidence, links in group:
                verdict = evidence.verdict
                score = (
                    f"{verdict.score:.2f}" + (" · already drifted" if verdict.label == "drifted" else "")
                    if verdict
                    else "—"
                )
                if sum(map(len, lines)) + len(links) > 20_000:
                    links = f"[A]({evidence.a.url()}) · [B]({evidence.b.url()})"
                lines.append(
                    f"| {escaped(evidence.a.qualified)} ≈ {escaped(evidence.b.qualified)} | {score} | "
                    f"{escaped(decided_by(verdict)) if verdict else 'not judged'} | "
                    f"{escaped(reason(verdict, evidence), WHY_LIMIT) if verdict and verdict.why else '—'} | "
                    f"{links} |"
                )
        if len(entries) > MAX_PAIRS:
            lines += ["", f"Showing {MAX_PAIRS} of {len(entries)} pairs; the scan reports retain the other findings."]
        settled = {candidate.key: candidate for report in reports for candidate in report.filtered}
        if settled:
            lines += ["", f"**🔗 Settled by a rule, not judged ({len(settled)})**", ""]
            lines += [
                f"- {escaped(qualified(c.new.owner, c.new.name))} ≈ {escaped(qualified(c.existing.owner, c.existing.name))}"
                f": {escaped(c.filtered or 'rule')}"
                for c in list(settled.values())[:MAX_RULES]
            ]
            if len(settled) > MAX_RULES:
                lines.append(f"- and {len(settled) - MAX_RULES} more")
        lines += [
            "",
            "Source links use fixed commits. Comparisons reuse recorded judgments; no extra model calls.",
            "A surviving symbol is shown when exactly one original remains; this does not prove caller migration.",
            "",
            "</details>",
        ]
        return "\n".join(lines)
