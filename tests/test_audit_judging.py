"""The audit reads the judging line exactly as reports render it, so the two cannot drift apart."""

import pytest

from dry_lint.costs import Spend
from dry_lint.report import JudgingSummary, escaped

OPUS = "claude-code:dry-v1:claude-opus-5-5"


@pytest.fixture
def audit(load_script):
    return load_script("audit_judging")


def comment(summary: JudgingSummary) -> str:
    return "\n".join(["<!-- dry-lint -->", "### dry-lint · ✨ No duplicated concepts", "",
                      "<sub>[dry-lint](https://github.com/gigaverse-app/dry-lint) · [run](https://x)</sub>",
                      f"<sub>{escaped(summary.line())}</sub>"])


def summary(**fields) -> JudgingSummary:
    return JudgingSummary(preset="jev+claude-code", judge="jev:reuse-v2", escalation=OPUS, band=(0.5, 0.91),
                          report_at=0.55, fail_at=0.55, budget_usd=0.04, pull_request=True, **fields)


def test_each_pull_request_reports_its_preset_spend_budget_and_outcome(audit) -> None:
    later_push = comment(summary(spend=[Spend(judge=OPUS, calls=2, usd=0.012, subscription=True)], spent_before=0.03))
    capped = comment(summary(spend=[Spend(judge=OPUS, calls=5, skipped=3, usd=0.039, subscription=True)]))
    failed = comment(summary(spend=[Spend(judge=OPUS, failed=2, error="OAuth session expired (401)")]))
    replies = {
        ("pr", "list"): [
            {"number": 1, "labels": [], "statusCheckRollup": [{"name": "Duplicated concepts", "conclusion": "SUCCESS"}]},
            {"number": 2, "labels": [{"name": "dry-lint: override"}],
             "statusCheckRollup": [{"name": "Duplicated concepts", "conclusion": "FAILURE"}]},
            {"number": 3, "labels": [], "statusCheckRollup": None},
            {"number": 4, "labels": [], "statusCheckRollup": []},
        ],
        1: [{"body": "an unrelated comment"}, {"body": later_push}],
        2: [{"body": capped}],
        3: [{"body": failed}],
        4: [{"body": "no dry-lint here"}],
    }

    def fetch(*args: str) -> object:
        return replies[args[:2]] if args[0] == "pr" else replies[int(args[-1].split("/")[-2])]

    rows = audit["audit"]("o/r", 4, fetch=fetch)
    assert [(r.number, r.preset, r.spent, r.budget) for r in rows] == [
        (1, "jev+claude-code", 0.042, 0.04), (2, "jev+claude-code", 0.039, 0.04), (3, "jev+claude-code", 0.0, 0.04)]
    assert [(r.capped, r.check_failed, r.overridden) for r in rows] == [(False, False, False), (True, True, True),
                                                                          (False, False, False)]
    assert rows[2].judge_failed == f"{OPUS}: OAuth session expired (401)"
    text = audit["summary"](rows)
    assert "3 pull requests with a dry-lint comment; 3 show what judging spent" in text
    assert "average $0.0270, median $0.0390, most $0.0420" in text
    assert "budget ran out: 1" in text and "a judge failed: 1" in text
    assert "check failed: 1; let through with 'dry-lint: override': 1" in text and f"#3: {OPUS}" in text


def test_a_comment_without_a_judging_line_counts_but_shows_no_spending(audit) -> None:
    [row] = [audit["judged"](5, "<!-- dry-lint -->\n### dry-lint · 1 look-alike pair, not judged", [], [])]
    assert (row.preset, row.spent, row.capped) == ("", None, False)
    assert audit["summary"]([row]).splitlines()[:2] == ["1 pull requests with a dry-lint comment; 0 show what judging spent",
                                                        "presets: none shown"]
