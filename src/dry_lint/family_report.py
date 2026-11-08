"""One useful consolidation per grounded family; unconfirmed siblings are always separate."""

from collections.abc import Callable

from pydantic import Field

from dry_lint.family_judging import FamilyFinding
from dry_lint.family_models import BoundClaim, FamilyFile, SourceReference
from dry_lint.report import escaped, plain


class FamilyReport(FamilyFile):
    findings: list[FamilyFinding] = Field(default_factory=list)

    @property
    def charged_usd(self) -> float:
        return sum(finding.charged_usd for finding in self.findings)

    @property
    def consolidations(self) -> int:
        # Confirmed family proposals; the pair report counts pair findings, a different finding type.
        # dry-lint: distinct-from src/dry_lint/report.py::Report.stats
        # dry-lint: distinct-from src/dry_lint/report.py::Report.deferred
        return sum(finding.reported for finding in self.findings)

    def markdown(self) -> str:
        return self._render(lambda value: escaped(value, 1600), markdown=True)

    def text(self) -> str:
        return self._render(lambda value: plain(value, 1600), markdown=False)

    def _render(self, clean: Callable[[str], str], *, markdown: bool) -> str:
        lines = ["## Operation families" if markdown else "Operation families", ""]
        for finding in self.findings:
            members = {member.owner_id: member for member in finding.request.members}

            def anchor_text(anchor: SourceReference, owners=members) -> str:
                owner = owners[anchor.owner_id].function.qualname
                return clean(f"{owner}:{anchor.start_line}-{anchor.end_line}")

            def claim_text(claim: BoundClaim) -> str:
                return f"{clean(claim.text)} (source: {'; '.join(anchor_text(anchor) for anchor in claim.evidence)})"

            if finding.record is None:
                lines += [f"Family unconfirmed — {clean(finding.status.replace('_', ' '))}", ""]
                for member in finding.request.members:
                    lines.append(f"- {clean(member.function.qualname)} — unconfirmed")
                if finding.error:
                    lines.append(f"- Failure: {clean(finding.error)}")
            else:
                answer = finding.record.answer
                if finding.reported:
                    common = answer.common
                    assert common is not None  # validated by FamilyFinding
                    lines += ["Consolidation proposed by judge", "", f"Operation: {claim_text(common.operation)}", ""]
                    lines += [f"Shared contract: {claim_text(common.shared_contract)}", "", "Proposed helper:", ""]
                    for label, value in (
                        ("Signature", common.helper.signature),
                        ("Inputs", common.helper.inputs),
                        ("Outputs", common.helper.outputs),
                        ("Side effects", common.helper.side_effects),
                    ):
                        lines.append(f"- {label}: {claim_text(value)}")
                    lines += ["", "Confirmed members (model assessment; inspect source before refactoring):", ""]
                    for member in answer.members:
                        if member.status != "confirmed":
                            continue
                        lines.append(f"- {'; '.join(anchor_text(anchor) for anchor in member.anchors)}")
                        for label, detail in (
                            ("Caller differences", member.caller_differences),
                            ("Ordering", member.ordering),
                            ("Exceptions", member.exceptions),
                            ("Existing helper/delegate", member.existing_reuse),
                            ("Migration", member.migration),
                        ):
                            assert detail is not None
                            lines.append(f"  {label}: {claim_text(detail)}")
                else:
                    lines += [f"No confirmed consolidation — {clean(answer.decision)}: {clean(answer.reason)}", ""]
                siblings = [member for member in answer.members if member.status != "confirmed"]
                if siblings:
                    lines += ["", "Additional unconfirmed siblings (not included in this consolidation):", ""]
                    for member in siblings:
                        name = clean(members[member.owner_id].function.qualname)
                        lines.append(f"- {name} — {member.status}: {clean(member.reason)}")
                actual = finding.record.actual_usd
                usage = "unknown" if actual is None else f"${actual:.6f}"
                lines += ["", f"Response cost: {usage}; {clean(finding.status)}."]
            lines += [f"Charged to shared campaign this run: ${finding.charged_usd:.6f}.", ""]
        return "\n".join(lines).rstrip() + "\n"
