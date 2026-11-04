"""Accepted repository debt, separate from cached verdicts and PR prevention totals.

The allowance is an exact pair and its logic hashes, never a numeric budget. Removed
allowances cannot be spent on different pairs or used to reintroduce cleaned code.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dry_lint.detector import Detector
from dry_lint.models import Candidate, pair_key
from dry_lint.report import Report
from dry_lint.settings import Settings

State = Literal["remaining", "cleaned", "dismissed"]
START, END = "<!-- dry-lint-progress:start -->", "<!-- dry-lint-progress:end -->"


def contract(settings: Settings) -> str:
    """Keep detection scope and judging policy fixed; human dismissals may change."""
    policy = settings.model_dump(
        include={
            "include",
            "exclude",
            "extractors",
            "comparer",
            "neighbours",
            "judge",
            "escalate",
            "drop_below",
            "report_at",
            "fail_at",
            "drift_at",
        }
    )
    return hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()


class Entry(BaseModel):
    """One original accepted pair, with its immutable evidence and current outcome."""

    model_config = ConfigDict(extra="forbid")
    hashes: dict[str, str]
    context_hash: str = ""
    state: State = "remaining"

    @model_validator(mode="after")
    def two_functions(self) -> "Entry":
        if len(self.hashes) != 2 or not all(self.hashes.values()):
            raise ValueError("A baseline entry requires two distinct functions and their structure hashes")
        return self

    @property
    def key(self) -> str:
        return pair_key(*sorted(self.hashes))

    @classmethod
    def of(cls, candidate: Candidate) -> "Entry":
        return cls(
            hashes={f.qualname: f.hash for f in (candidate.new, candidate.existing)},
            context_hash=candidate.context_hash,
        )

    def accepts(self, candidate: Candidate) -> bool:
        other = Entry.of(candidate)
        return self.state == "remaining" and self.hashes == other.hashes and self.context_hash == other.context_hash


class Baseline(BaseModel):
    """Committed adoption state. Its independent schema is not a verdict-store schema."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)
    schema_version: Literal[1] = Field(default=1, alias="schema")
    contract: str
    started_at: str
    checked_at: str
    entries: list[Entry]

    @model_validator(mode="after")
    def unique_pairs(self) -> "Baseline":
        if len({e.key for e in self.entries}) != len(self.entries):
            raise ValueError("Duplicate baseline pair")
        return self

    @classmethod
    def read(cls, path: Path, settings: Settings) -> "Baseline":
        result = cls.model_validate_json(path.read_text(encoding="utf-8"))
        if result.contract != contract(settings):
            raise ValueError("Baseline detection/judging policy differs; restore the adoption settings before checking")
        return result

    @classmethod
    def start(cls, report: Report, settings: Settings) -> "Baseline":
        require_complete(report)
        return cls(
            contract=contract(settings),
            started_at=report.run.head,
            checked_at=report.run.head,
            entries=[Entry.of(f.candidate) for f in report.findings if f.blocking],
        )

    def count(self, state: State) -> int:
        return sum(e.state == state for e in self.entries)

    def validate_successor(self, previous: "Baseline") -> None:
        old, new = {e.key: e for e in previous.entries}, {e.key: e for e in self.entries}
        if self.contract != previous.contract or self.started_at != previous.started_at or old.keys() != new.keys():
            raise ValueError("A baseline update cannot change its original scope or accepted pair set")
        for key, entry in new.items():
            before = old[key]
            if (
                entry.hashes != before.hashes
                or entry.context_hash != before.context_hash
                or before.state != "remaining"
                and entry.state != before.state
            ):
                raise ValueError("A baseline update cannot widen an allowance or reopen settled debt")

    def apply(self, report: Report) -> Report:
        accepted = {e.key: e for e in self.entries if e.state == "remaining"}
        # INVARIANT: an old duplicate never grants permission for new or changed duplicate logic.
        findings = [
            f.model_copy(update={"blocking": False, "reported": False})
            if f.candidate.key in accepted and accepted[f.candidate.key].accepts(f.candidate)
            else f
            for f in report.findings
        ]
        return report.model_copy(update={"findings": findings})

    def candidates(self, detector: Detector) -> list[Candidate]:
        found = {c.key: c for c in detector.candidates(detector.functions)}
        functions = {f.qualname: f for f in detector.functions}
        for entry in self.entries:
            if entry.state != "remaining" or not all(name in functions for name in entry.hashes):
                continue
            a, b = (functions[name] for name in sorted(entry.hashes))
            pair = detector.pair(a, b, detector.comparer.similarity(a, b))
            found[pair.key] = pair  # Always revisit debt, even if it fell out of the nearest-neighbour ranking.
        return list(found.values())

    def advance(self, report: Report) -> "Baseline":
        require_complete(report)
        if any(f.blocking for f in self.apply(report).findings):
            raise ValueError("New or changed duplicates cannot be added to the baseline")
        findings = {f.candidate.key: f for f in report.findings}
        dismissed = {c.key for c in report.filtered}
        entries = []
        for entry in self.entries:
            state = entry.state
            if state == "remaining":
                finding = findings.get(entry.key)
                if entry.key in dismissed:
                    state = "dismissed"
                elif finding is None or (finding.verdict is not None and finding.verdict.label == "separate"):
                    state = "cleaned"
            entries.append(entry.model_copy(update={"state": state}))
        if entries == self.entries:
            return self  # Keep no-change audits idempotent, without timestamp-only baseline edits.
        return self.model_copy(update={"entries": entries, "checked_at": report.run.head})

    def badge(self) -> dict[str, str | int]:
        return {
            "schemaVersion": 1,
            "label": "dry-lint",
            "color": "7E4FC9",
            "labelColor": "24292F",
            "message": f"{self.count('cleaned')} cleaned · {self.count('remaining')} remaining",
        }

    def markdown(self, repository: str, branch: str, directory: str) -> str:
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
            raise ValueError("README progress needs --repository OWNER/NAME")
        source = f"https://raw.githubusercontent.com/{repository}/{quote(branch, safe='')}/{directory}/progress.json"
        badge = f"https://img.shields.io/endpoint?url={quote(source, safe='')}"
        return (
            f"{START}\n[![dry-lint cleanup progress]({badge})](https://github.com/gigaverse-app/dry-lint)\n\n"
            "**Cleaning up duplication with dry-lint.** CI checks new changes against the accepted backlog.\n\n"
            "| Duplicate pairs cleaned | Remaining | Dismissed |\n| ---: | ---: | ---: |\n"
            f"| {self.count('cleaned')} | {self.count('remaining')} | {self.count('dismissed')} |\n\n"
            f"[Accepted backlog]({directory}/baseline.json). Counts cover judged pairs in the configured scope, "
            "not lines of code; dismissals do not count as cleanup.\n"
            f"[Read the audit](https://github.com/{repository}/actions/workflows/dry-lint-audit.yml) "
            "to choose the next refactor.\n"
            f"{END}"
        )


def require_complete(report: Report) -> None:
    """An unassessed pair is unknown, never evidence of a clean required check."""
    if report.judge is None:
        raise ValueError("Strict checking requires a configured judge; supply the adopter's credentials")
    if any(f.verdict is None or f.deferred for f in report.findings) or (
        report.judging and any(s.failed or s.skipped for s in report.judging.spend)
    ):
        raise ValueError("Judging is incomplete; restore the judge or increase its budget and rerun")


def update_readme(text: str, block: str) -> str:
    """Replace only our block; preserve malformed/unrelated content by appending a fresh block."""
    if START in text and END in text and text.index(START) < text.index(END):
        return text[: text.index(START)] + block + text[text.index(END) + len(END) :]
    return text.rstrip() + "\n\n" + block + "\n"
