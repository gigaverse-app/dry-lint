"""Accepted repository debt, separate from cached verdicts and PR prevention totals.

The allowance is an exact pair and its logic hashes, never a numeric budget. Removed
allowances cannot be spent on different pairs or used to reintroduce cleaned code.
"""

from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dry_lint.detector import Detector
from dry_lint.function_index import digest, repository_name
from dry_lint.models import Candidate, Function, pair_key
from dry_lint.report import BacklogCleanup, Report
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
    return digest(policy)


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

    def candidates(self, detector: Detector, changed: list[Function] | None = None) -> list[Candidate]:
        """
        The detector's pairs and the remaining debt. A sweep revisits all of it; a check (`changed`) revisits the debt
        whose functions the change touched and keeps its own pairs, so a rerouted side still gets a verdict.
        """
        found = {c.key: c for c in detector.candidates(detector.functions if changed is None else changed)}
        functions = {f.qualname: f for f in detector.functions}
        touched = None if changed is None else {f.qualname for f in changed}
        for entry in self.entries:
            if entry.state != "remaining" or not all(name in functions for name in entry.hashes):
                continue
            if touched is not None and (touched.isdisjoint(entry.hashes) or entry.key in found):
                continue
            a, b = (functions[name] for name in sorted(entry.hashes))
            pair = detector.pair(a, b, detector.comparer.similarity(a, b))
            found[pair.key] = pair  # Always revisit debt, even if it fell out of the nearest-neighbour ranking.
        return list(found.values())

    def cleared(self, report: Report, removed: set[str]) -> list[BacklogCleanup]:
        """
        The remaining debt a change cleaned up, on the evidence `advance` accepts: a side it removed (`removed` holds
        the functions present at its merge base and gone now) or a `separate` verdict on the pair as it is now.
        """
        findings = {f.candidate.key: f for f in report.findings}
        # A survivor still reported as a duplicate moved the duplication (a renamed copy) rather than removing it.
        duplicated = {side.qualname for f in self.apply(report).findings if f.reported
                      for side in (f.candidate.new, f.candidate.existing)}
        found = []
        for entry in self.entries:
            if entry.state != "remaining":
                continue
            finding = findings.get(entry.key)
            if removed & entry.hashes.keys() and not (entry.hashes.keys() - removed) & duplicated:
                how = "removed"
            elif finding is not None and finding.verdict is not None and finding.verdict.label == "separate":
                how = "separate"
            else:
                continue
            new, existing = sorted(entry.hashes)
            found.append(BacklogCleanup(new=new, existing=existing, how=how))
        return found

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
        repository_name(repository)
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
