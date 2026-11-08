"""Accepted repository debt, separate from cached verdicts and PR prevention totals.

The allowance is an exact pair and its logic hashes, never a numeric budget. Removed
allowances cannot be spent on different pairs or used to reintroduce cleaned code.
"""

import html
import re
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlencode

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dry_lint.detector import Detector
from dry_lint.function_index import digest, repository_name
from dry_lint.git import git
from dry_lint.ledger import COUNTER
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
        """
        The unchanged pair this entry accepted. An entry recorded without a context hash, before the detector gave
        every pair one, is matched on its functions alone, as it was when accepted; both must still be unchanged.
        """
        other = Entry.of(candidate)
        return (
            self.state == "remaining"
            and self.hashes == other.hashes
            and (not self.context_hash or self.context_hash == other.context_hash)
        )


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
        return cls.parse(path.read_text(encoding="utf-8"), settings)

    @classmethod
    def parse(cls, raw: str, settings: Settings) -> "Baseline":
        result = cls.model_validate_json(raw)
        if result.contract != contract(settings):
            raise ValueError("Baseline detection/judging policy differs; restore the adoption settings before checking")
        return result

    @classmethod
    def for_repository(
        cls, root: Path, path: Path, settings: Settings, *, base: str | None = None, staged: bool = False
    ) -> tuple["Baseline", "Baseline | None"]:
        """Read proposed allowances and enforce the target branch's immutable pair set."""
        relative = (root / path).resolve().relative_to(root.resolve()).as_posix()
        raw = git(root, "show", f":{relative}") if staged else (root / path).read_text(encoding="utf-8")
        proposed, previous = cls.parse(raw, settings), None
        previous_ref = "HEAD" if staged else base
        if previous_ref:
            git(root, "rev-parse", "--verify", f"{previous_ref}^{{commit}}")
            if git(root, "ls-tree", "--name-only", previous_ref, "--", relative):
                previous = cls.model_validate_json(git(root, "show", f"{previous_ref}:{relative}"))
                proposed.validate_successor(previous)
        return proposed, previous

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
        accepted = self.matching([f.candidate for f in report.findings])
        # INVARIANT: an old duplicate never grants permission for new or changed duplicate logic.
        findings = [
            f.model_copy(update={"blocking": False, "reported": False}) if f.candidate.key in accepted else f
            for f in report.findings
        ]
        return report.model_copy(update={"findings": findings})

    def matching(self, candidates: list[Candidate]) -> set[str]:
        accepted = {e.key: e for e in self.entries if e.state == "remaining"}
        return {c.key for c in candidates if c.key in accepted and accepted[c.key].accepts(c)}

    def candidates(self, detector: Detector, changed: list[Function] | None = None) -> list[Candidate]:
        """
        The detector's pairs and the remaining debt. A sweep revisits all of it; a check (`changed`) revisits the debt
        whose functions the change touched and keeps its own pairs, so a rerouted side still gets a verdict.
        """
        found = {c.key: c for c in detector.candidates(detector.functions if changed is None else changed)}
        functions: dict[str, list[Function]] = {}
        for function in detector.functions:
            functions.setdefault(function.qualname, []).append(function)
        touched = None if changed is None else {f.qualname for f in changed}
        for entry in self.entries:
            if entry.state != "remaining" or not all(name in functions for name in entry.hashes):
                continue
            if entry.key in found or touched is not None and touched.isdisjoint(entry.hashes):
                continue
            # Accessors can share a qualified name. Revisit the accepted body rather than silently
            # substituting its setter and recording a negative verdict as cleanup of the getter.
            a, b = (
                next(
                    (f for f in functions[name] if detector.hashed(f).hash == entry.hashes[name]),
                    functions[name][-1],
                )
                for name in sorted(entry.hashes)
            )
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
        duplicated = {
            side.qualname
            for f in self.apply(report).findings
            if f.reported or f.review_required
            for side in (f.candidate.new, f.candidate.existing)
        }
        found = []
        for entry in self.entries:
            if entry.state != "remaining":
                continue
            finding = findings.get(entry.key)
            if removed & entry.hashes.keys() and not (entry.hashes.keys() - removed) & duplicated:
                how = "removed"
            elif (
                finding is not None
                and not finding.review_required
                and finding.verdict is not None
                and finding.verdict.label == "separate"
            ):
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
        cleaned = {
            entry.key
            for entry in self.entries
            if (finding := findings.get(entry.key)) is None
            or finding.verdict is not None
            and finding.verdict.label == "separate"
        }
        return self.retire(dismissed=dismissed, cleaned=cleaned, revision=report.run.head)

    def retire(self, *, dismissed: set[str], cleaned: set[str], revision: str) -> "Baseline":
        """One irreversible state transition, with caller-specific evidence deciding what resolved a pair."""
        entries = []
        for entry in self.entries:
            state = entry.state
            if state == "remaining":
                if entry.key in dismissed:
                    state = "dismissed"
                elif entry.key in cleaned:
                    state = "cleaned"
            entries.append(entry.model_copy(update={"state": state}))
        if entries == self.entries:
            return self  # Keep no-change audits idempotent, without timestamp-only baseline edits.
        return self.model_copy(update={"entries": entries, "checked_at": revision})

    def badge(self) -> dict[str, str | int]:
        return {
            "schemaVersion": 1,
            "label": "dry-lint",
            "color": "7E4FC9",
            "labelColor": "24292F",
            "message": f"{self.count('cleaned')} cleaned · {self.count('remaining')} remaining",
        }

    def card(self, repository: str, key: str, models: "Baseline | None" = None) -> str:
        """
        The repository's counter sign: new duplicates kept out of its pull requests, live from the counter, beside this
        backlog's old duplicates cleaned up and remaining. The backlog travels in the sign's address, so it changes
        when a sweep rewrites the block.
        """
        query = {
            "key": key,
            "name": repository,
            "cleaned": self.count("cleaned"),
            "remaining": self.count("remaining"),
            "dismissed": self.count("dismissed"),
        }
        if models is not None:
            query.update({f"models_{state}": models.count(state) for state in ("cleaned", "remaining", "dismissed")})
        light = f"{COUNTER}/v1/sign.svg?{urlencode(query)}"
        dark = f"{COUNTER}/v1/sign.svg?{urlencode({'theme': 'dark', **query})}"
        alt = (
            f"dry-lint in {repository}: new duplicates kept out of its pull requests, "
            f"{self.count('cleaned')} old duplicates cleaned up, {self.count('remaining')} remaining"
        )
        if models is not None:
            alt = (
                f"dry-lint in {repository}: confirmed function duplicates kept out of pull requests; "
                f"function debt: {self.count('remaining')} remaining, {self.count('cleaned')} retired, {self.count('dismissed')} dismissed; "
                f"reviewed model debt: {models.count('remaining')} remaining, {models.count('cleaned')} retired, {models.count('dismissed')} dismissed"
            )
        return (
            '<a href="https://github.com/gigaverse-app/dry-lint"><picture>'
            f'<source media="(prefers-color-scheme: dark)" srcset="{html.escape(dark)}">'
            f'<img alt="{html.escape(alt)}" src="{html.escape(light)}" width="100%"></picture></a>\n\n'
        )

    def markdown(
        self,
        repository: str,
        branch: str,
        directory: str,
        key: str = "",
        *,
        models: "Baseline | None" = None,
        models_path: str = ".dry-lint/models.json",
        filename: str = "baseline.json",
    ) -> str:
        """
        The README block. With the repository's counter key it is the repository's sign, which shows the backlog, and
        its sources; without one, a progress badge and a table of the backlog.
        """
        repository_name(repository)
        audit = f"https://github.com/{repository}/actions/workflows/dry-lint-audit.yml"
        source = f"https://raw.githubusercontent.com/{repository}/{quote(branch, safe='')}/{directory}/progress.json"
        badge = f"https://img.shields.io/endpoint?url={quote(source, safe='')}"
        image = (
            self.card(repository, key, models)
            if key
            else (f"[![dry-lint cleanup progress]({badge})](https://github.com/gigaverse-app/dry-lint)\n\n")
        )
        model_row = (
            f"| Models | {models.count('remaining')} | {models.count('cleaned')} | {models.count('dismissed')} |"
            if models is not None
            else "| Models | Not initialized | — | — |"
        )
        model_link = f" · [Reviewed model debt]({quote(models_path, safe='/')})" if models is not None else ""
        return (
            f"{START}\n{image}"
            "**Reviewed duplication debt** · Counts from the committed baselines.\n\n"
            "| Accepted pairs | Remaining | Retired | Dismissed |\n| :-- | --: | --: | --: |\n"
            f"| Functions | {self.count('remaining')} | {self.count('cleaned')} | {self.count('dismissed')} |\n"
            f"{model_row}\n\n"
            f"[Accepted backlog]({quote(directory + '/' + filename, safe='/')}) · [Weekly audit]({audit}){model_link}\n\n"
            "Retired means a side was removed, or (functions only) the judge now finds the pair separate. "
            "It is not a count of refactors. Dismissals stay separate; an uninitialized model baseline is unknown.\n"
            f"{END}"
        )


def readme_key(text: str) -> str:
    """The counter key of a sign already in a README's block, so a sweep that cannot look it up keeps the sign."""
    block = text[text.index(START) : text.index(END)] if START in text and END in text else ""
    found = re.search(r"/v1/sign\.svg\?[^\"\s]*?\bkey=([0-9a-f]{64})", block)
    return found.group(1) if found else ""


def require_complete(report: Report, *, check: bool = False, allow_review_tasks: bool = False) -> None:
    """An unassessed pair is unknown, never evidence of a clean required check."""
    if report.judge is None:
        raise ValueError("Strict checking requires a configured judge; supply the adopter's credentials")
    unresolved = (
        f
        for f in report.findings
        if not (check and f.budget_deferred) and not (allow_review_tasks and f.review_required)
    )
    if any(f.verdict is None or f.deferred or f.review_required for f in unresolved) or (
        report.judging and any(s.failed or (s.skipped and not check) for s in report.judging.spend)
    ):
        raise ValueError("Judging is incomplete; resolve agent review tasks or restore the judge and rerun")


HEADING = "## Duplicate code"


def update_readme(text: str, block: str) -> str:
    """
    Replace only our block; preserve malformed/unrelated content by appending a fresh block. A first block gets a
    visible heading, outside the markers, so a maintainer can rename or move it and later updates leave it alone.
    """
    if START in text and END in text and text.index(START) < text.index(END):
        return text[: text.index(START)] + block + text[text.index(END) + len(END) :]
    return text.rstrip() + f"\n\n{HEADING}\n\n" + block + "\n"
