"""GitHub links for every repo; public-only, model-free source comparisons for the static viewer."""

import base64
import json
import os
import re
from typing import TYPE_CHECKING
from urllib.parse import quote, urlsplit

import httpx

from dry_lint.comparison_helpers import python_helpers
from dry_lint.evidence import PairEvidence, SourceReference
from dry_lint.extractors import PythonExtractor
from dry_lint.ledger import PullLedger
from dry_lint.models import Function, Run
from dry_lint.report import Report, escaped
from dry_lint.typescript import TypeScriptExtractor

if TYPE_CHECKING:
    from dry_lint.sticky import GitHub

VIEWER = "https://gigaverse-app.github.io/dry-lint/compare/"
MAX_PAIRS = 5
MAX_LINK = 12_000


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
        extractor = (
            PythonExtractor()
            if source.path.endswith(".py")
            else TypeScriptExtractor()
            if source.path.endswith((".ts", ".tsx", ".mts", ".cts"))
            else None
        )
        if extractor is None:
            return False, None
        key = (source.repository, self.head, source.path)
        if key not in self.files:
            try:
                response = self.github.client.get(
                    f"/repos/{source.repository}/contents/{quote(source.path, safe='/')}",
                    params={"ref": self.head},
                    headers={"Accept": "application/vnd.github.raw+json"},
                )
                if response.status_code == 404:
                    self.files[key] = []
                else:
                    response.raise_for_status()
                    extractor.validate_source(source.path, response.text)
                    self.files[key] = extractor.functions(source.path, response.text)
                    self.source_text[key] = response.text
            except (httpx.HTTPError, ValueError, SyntaxError):
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
        if not result.path.endswith(".py") or key not in self.source_text:
            return []
        caller = next(function for function in self.files[key] if function.line == result.line)
        return [
            SourceReference.of(function, Run(repository=result.repository, head=result.revision))
            for function in python_helpers(self.source_text[key], caller)
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
        if state == "kept-out":
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
        ordered = sorted(entries.items(), key=lambda entry: entry[1][1] != "kept-out")
        lines = [
            "<details><summary><strong>Compare the code and recorded judgments</strong></summary>",
            "",
            "The recorded label is the judge's classification; confidence determines whether a duplicate or "
            "drifted pair meets the reporting bar. Low-confidence candidates and pairs judged separate are "
            "not counted as tangled.",
            "",
            "| Pair | Report outcome | Sources | Recorded classification and confidence |",
            "| :-- | :-- | :-- | :-- |",
        ]
        states = {
            "kept-out": "No longer reported",
            "open": "Still tangled",
            "dismissed": "Dismissed",
            "below threshold": "Not reported: low confidence",
            "separate": "Not reported: judged separate",
        }
        for key, (evidence, state) in ordered[:MAX_PAIRS]:
            verdict = evidence.verdict
            judgment = (
                f"{verdict.label}; confidence {verdict.score:.2f}; {verdict.judge}; "
                f"{'reused' if evidence.cached else 'recorded'}" + (f": {verdict.why}" if verdict.why else "")
                if verdict
                else "Not judged"
            )
            concept = f"{evidence.a.qualified} ≈ {evidence.b.qualified}"
            links = self.links(evidence, state)
            if sum(map(len, lines)) + len(links) > 20_000:
                links = f"[A]({evidence.a.url()}) · [B]({evidence.b.url()})"
            lines.append(f"| {escaped(concept)} | {states.get(state, state)} | {links} | {escaped(judgment)} |")
        if len(entries) > MAX_PAIRS:
            lines += ["", f"Showing {MAX_PAIRS} of {len(entries)} pairs; the scan reports retain the other findings."]
        lines += [
            "",
            "Source links use fixed commits. Comparisons reuse recorded judgments; no extra model calls.",
            "A surviving symbol is shown when exactly one original remains; this does not prove caller migration.",
            "",
            "</details>",
        ]
        return "\n".join(lines)
