import json

import pytest

from dry_lint.costs import Spend
from dry_lint.models import Candidate, Run, Verdict
from dry_lint.report import (
    CLEAN,
    FORMATS,
    GRAY,
    MARKER,
    NOTE_SLOT,
    Finding,
    JudgingSummary,
    Report,
    as_check_run,
    as_github,
    as_json,
    as_markdown,
    as_sarif,
    as_text,
    badge,
    code,
    escaped,
    function_link,
    plain,
    render,
    short_paths,
)
from dry_lint.settings import Escalation, Settings

from conftest import function

SETTINGS = Settings(fail_at=0.91)  # raised above report_at, so there is a band that only warns
HEAD = "a" * 40
NEW = function("src/widgets/caption.py", "def clip(text, n):\n    return text[:n]\n")


def pair(existing: str = "shorten", path: str = "src/text.py", filtered: str | None = None) -> Candidate:
    return Candidate(new=NEW, existing=function(path, f"def {existing}(text, limit):\n    return text[:limit]\n"),
                     similarity=0.71, comparer="tfidf:1", filtered=filtered)


def finding(label: str | None, score: float = 0.9, owner: str = "existing", why: str = "", cached: bool = False,
            existing: str = "shorten") -> Finding:
    verdict = Verdict(label=label, score=score, owner=owner, why=why, judge="jev", judge_version="v") if label else None
    return Finding(candidate=pair(existing), verdict=verdict, cached=cached)


def report(*findings: Finding, filtered: list[Candidate] = (), judge: str | None = "jev:v") -> Report:
    return Report.build(list(findings), SETTINGS, filtered=filtered, run=Run(repository="o/r", pull_request=5, head=HEAD),
                        changed=2, judge=judge)


def test_only_unjudged_candidates_and_confident_duplicates_are_visible() -> None:
    built = report(finding(None, existing="a"), finding("duplicate", 0.8, existing="b"), finding("drifted", 0.95, existing="c"),
                   finding("duplicate", 0.79, existing="d"), finding("separate", 0.95, existing="e"))
    assert [f.candidate.existing.name for f in built.visible] == ["c", "b", "a"]
    assert [f.reported for f in built.findings] == [True, True, False, False, False]


def test_findings_are_ordered_blocking_then_drifted_then_by_score_and_count_their_family() -> None:
    built = report(finding("duplicate", 0.85, existing="a"), finding("duplicate", 0.95, existing="b"),
                   finding("drifted", 0.81, existing="c"), finding("duplicate", 0.88, existing="d"))
    assert [f.candidate.existing.name for f in built.findings] == ["b", "c", "d", "a"]
    assert [f.blocking for f in built.findings] == [True, False, False, False]
    assert {f.family for f in built.findings} == {4}


@pytest.mark.parametrize("label, score, reported, blocking", [
    ("duplicate", 0.79, False, False), ("duplicate", 0.8, True, False), ("drifted", 0.89, True, False),
    ("duplicate", 0.9, True, False), ("duplicate", 0.91, True, True), ("drifted", 0.97, True, True),
    ("separate", 0.95, False, False),
])  # fmt: skip
def test_blocking_means_a_reported_duplicate_at_or_above_fail_at(label, score, reported, blocking) -> None:
    [f] = report(finding(label, score)).findings
    assert (f.reported, f.blocking) == (reported, blocking)


def test_fail_at_below_report_at_never_blocks_an_unreported_pair() -> None:
    settings = Settings(report_at=0.8, fail_at=0.5)
    [f] = Report.build([finding("duplicate", 0.7)], settings).findings
    assert (f.reported, f.blocking) == (False, False)


def test_stats_count_every_kind_of_pair() -> None:
    built = report(finding("duplicate", cached=True, existing="a"), finding("separate", 0.1, existing="b"),
                   filtered=[pair("z", filtered="one calls the other")])
    assert built.stats == {"changed": 2, "candidates": 3, "filtered": 1, "cached": 1, "judged": 1, "reported": 1}


def test_text_report_gives_location_verdict_advice_and_a_way_out() -> None:
    text = as_text(report(finding("drifted", 0.91, "shared", "same truncation", cached=True)))
    assert text.startswith("src/widgets/caption.py:1: clip looks like src/text.py::shorten (drifted)")
    for part in ["judge 0.91 (cached)", "behave differently", "extract a shared helper", "same truncation",
                 "similarity 0.71", "# dry-lint: distinct-from src/text.py::shorten"]:
        assert part in text
    assert text.endswith("1 candidate pair(s), 0 skipped by rule, 1 from the store, 0 judged (judge jev:v), 1 reported")
    assert as_text(report(judge=None)).endswith("(no judge), 0 reported")


def test_github_annotations_are_errors_for_blocking_findings_and_warnings_for_the_rest() -> None:
    lines = as_github(report(finding("duplicate", 0.85, existing="a"), finding("drifted", 0.86, existing="b"),
                             finding("duplicate", 0.93, existing="c"), finding("separate", existing="d"))).splitlines()
    assert [line.split(" ", 1)[0] for line in lines] == ["::error", "::warning", "::warning"]
    assert lines[1].startswith("::warning file=src/widgets/caption.py,line=1,endLine=2,title=dry-lint::clip looks like")


def test_github_annotations_escape_percent_signs_and_judge_text_is_one_line() -> None:
    line = as_github(report(finding("duplicate", why="100% the same\nreally")))
    assert "100%25 the same really" in line and "\n" not in line


def test_markdown_comment_lists_findings_under_a_stable_marker() -> None:
    body = as_markdown(report(finding("duplicate", 0.88, "existing", "same truncation"), finding(None, existing="other")))
    assert body.startswith(MARKER) and "### dry-lint · 2 duplicated concepts" in body
    assert f'[caption.py:1](https://github.com/o/r/blob/{HEAD}/src/widgets/caption.py#L1-L2 "src/widgets/caption.py")' in body
    assert f'[text.py:1](https://github.com/o/r/blob/{HEAD}/src/text.py#L1-L2 "src/text.py")' in body
    assert "| 🟡 | `clip` ≈ `shorten` <sub>· 2 look-alikes</sub> |" in body
    assert "**duplicate**&nbsp;0.88<br><sub>call the existing one</sub> |" in body
    assert "| ⚪ | `clip` ≈ `other` <sub>· 2 look-alikes</sub> |" in body and "<sub>not judged</sub>" in body
    assert "> same truncation" in body
    assert "```python\n# dry-lint: distinct-from src/text.py::shorten\n```" in body
    assert "<sub>2 changed functions · 2 pairs compared · judge `jev:v`</sub>" in body


def test_markdown_headline_keeps_blockers_visible_without_repeating_counts_in_badges() -> None:
    body = as_markdown(report(finding("drifted", 0.95, existing="a"), finding("duplicate", 0.85, existing="b")))
    assert "### dry-lint · 2 duplicated concepts · 🔴 1 blocking" in body
    assert "**drifted**" in body and "judge `jev:v`" in body
    assert "img.shields.io" not in body
    calm = as_markdown(report(finding("duplicate", 0.85)))
    assert "### dry-lint · 1 duplicated concept" in calm and "blocking" not in calm and "drifted" not in calm


def test_badges_escape_shields_separators() -> None:
    assert badge("look-alike pairs", "a_b-c", GRAY).endswith("/look--alike_pairs-a__b--c-6E7781?style=flat-square&labelColor=24292F)")


def test_one_shared_fix_is_said_once_instead_of_on_every_row() -> None:
    body = as_markdown(report(finding("duplicate", 0.9, "shared", existing="a"), finding("duplicate", 0.85, "shared", existing="b")))
    assert "**Suggested fix:** extract a shared helper." in body
    assert "<sub>extract a shared helper</sub>" not in body


def clean_report(*findings: Finding, filtered: list[Candidate] = (), changed: int = 2, functions: int = 1284,
                 scope: str = "change") -> Report:
    return Report.build(list(findings), SETTINGS, filtered=filtered, run=Run(repository="o/r", head=HEAD),
                        changed=changed, judge="jev:v", functions=functions, scope=scope)


def test_a_clean_report_says_so_and_shows_what_was_checked_to_earn_it() -> None:
    body = as_markdown(clean_report(finding("separate", 0.62), finding("duplicate", 0.7, cached=True, existing="trim"),
                                    filtered=[pair("z", filtered="declared pattern")]), report_at=0.8)
    assert body.startswith(f"{MARKER}\n{CLEAN}\n### dry-lint · ✨ No duplicated concepts")
    assert "img.shields.io" not in body and "only implementation" not in body
    for row in ("| 🔎 Changed functions | 🗂 Compared with | 🧶 Look-alike pairs |", "| 2 | 1,284 functions | 3 |",
                "| Settled by a rule | 1 |", "| Cleared by the judge | 2 (1 from the verdict store) |",
                "| Closest call | `clip` ≈ `trim` · duplicate 0.70 · under the 0.80 bar |"):
        assert row in body
    assert NOTE_SLOT in body and "<details>" not in body


def test_a_clean_report_without_look_alikes_names_the_scale_of_the_comparison() -> None:
    body = as_markdown(clean_report())
    assert "| 2 | 1,284 functions | 0 |" in body and body.count("1,284") == 1
    assert "Closest call" not in body and "Cleared by the judge" not in body and "Settled by a rule" not in body
    assert "| 2 | 0 |" in as_markdown(clean_report(functions=0))
    assert "Compared with" not in as_markdown(clean_report(functions=0))
    assert "**Nothing to compare.** This pull request changes no functions." in as_markdown(clean_report(changed=0))
    assert "under the" not in as_markdown(clean_report(finding("separate")))


def test_a_clean_audit_speaks_of_the_repository() -> None:
    body = as_markdown(clean_report(finding("separate"), changed=0, scope="repository"))
    assert "### dry-lint audit · ✨ No duplicated concepts in existing code" in body
    assert "| Cleared by the judge | 1 |" in body
    assert "| 🗂 Functions in the repository | 🧶 Look-alike pairs |" in body and "| 1,284 functions | 1 |" in body
    assert "Changed functions" not in body and "changed_functions" not in body
    assert "| 1,284 functions | 0 |" in as_markdown(clean_report(changed=0, scope="repository"))


def test_without_a_judge_the_comment_lists_nothing_and_says_how_to_get_one() -> None:
    body = as_markdown(report(finding(None), finding(None, existing="other"), judge=None))
    assert body.startswith(MARKER) and "No judge is configured" in body and "2 look-alike pairs, not judged" in body
    assert "shorten" not in body and "no judge" in body


def test_markdown_caps_the_rows_and_lists_settled_pairs_folded() -> None:
    many = [finding("duplicate", 0.9, existing=f"f{i}") for i in range(4)]
    body = as_markdown(report(*many, filtered=[pair("z", filtered="declared pattern: one per resource")]), max_findings=2)
    assert body.count("| 🟡 | `clip`") == 2 and "+ 2 more pairs not listed here" in body
    assert "<details><summary><strong>Settled by a rule (1)</strong></summary>" in body
    assert "- `src/widgets/caption.py::clip` ~ `src/text.py::z`: declared pattern: one per resource" in body
    assert "1 settled by a rule" in body


def test_judge_text_cannot_inject_markdown_links_or_html() -> None:
    hostile = "ignore this [click](https://evil.example) <img src=x> | col " + "x" * 400
    body = as_markdown(report(finding("duplicate", why=hostile)))
    assert "[click](" not in body and "\\<img src=x\\>" in body and "<img" not in body.replace("\\<", "")
    assert "\\| col" in body
    assert len(escaped(hostile)) < 400 and plain(hostile).endswith("…") and len(plain(hostile)) == 300
    assert plain("  two\n lines ") == "two lines"


def test_names_that_could_break_a_code_span_or_table_are_escaped_instead() -> None:
    assert code("clip") == "`clip`" and code("a`b|c") == "a\\`b\\|c"


def test_rows_say_the_verdict_alone_when_there_is_no_owner() -> None:
    assert "| **duplicate**&nbsp;0.85 |" in as_markdown(report(finding("duplicate", 0.85, owner="", why="same truncation")))


def test_markdown_labels_blocking_findings_first_and_lists_every_override() -> None:
    body = as_markdown(report(finding("duplicate", 0.85, existing="a"), finding("duplicate", 0.93, existing="b")))
    assert body.index("| 🔴 | `clip` ≈ `b`") < body.index("| 🟡 | `clip` ≈ `a`")
    assert "**duplicate**&nbsp;0.93<br><sub>blocks</sub>" in body
    assert "🔴 fails the check" in body and "🟡 duplicate" in body and "🟠" not in body
    for override in ("`# dry-lint: distinct-from <qualified name>` in the changed function", "`# dry-lint: ignore`",
                     "`patterns`", "`.dry-lint.toml`", "the `dry-lint: override` label"):
        assert override in body
    assert "blocking" not in as_markdown(report(finding("duplicate", 0.85)))


def test_overrides_use_the_comment_syntax_of_the_findings_languages() -> None:
    typescript = Finding(candidate=pair("shorten").model_copy(update={"new": function("src/caption.ts", "def clip(text, n):\n    return text[:n]\n")}),
                         verdict=Verdict(label="duplicate", score=0.9, owner="new", judge="jev", judge_version="v"))
    only = as_markdown(report(typescript))
    assert "`// dry-lint: ignore`" in only and "start with `//`" not in only
    assert "```ts\n// dry-lint: distinct-from src/text.py::shorten\n```" in only
    mixed = as_markdown(report(typescript, finding("duplicate", existing="other")))
    assert "`# dry-lint: ignore`" in mixed and "In TypeScript and TSX, the comments start with `//`." in mixed


def test_paths_show_only_as_much_as_tells_the_two_files_apart() -> None:
    assert short_paths("a/b/view.tsx", "c/d/other.tsx") == ("view.tsx", "other.tsx")
    assert short_paths("chat/x/Quoted.tsx", "live/y/Quoted.tsx") == ("x/Quoted.tsx", "y/Quoted.tsx")
    assert short_paths("src/same.py", "src/same.py") == ("same.py", "same.py")
    assert short_paths("Quoted.tsx", "live/Quoted.tsx") == ("Quoted.tsx", "live/Quoted.tsx")


def test_source_links_pin_the_commit_escape_paths_and_support_enterprise(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://git.example.com")
    built = report(finding("duplicate")).model_copy(deep=True)
    built.findings[0].candidate.new.path = 'src/a [draft](1)".py'
    body = as_markdown(built)
    assert f"https://git.example.com/o/r/blob/{HEAD}/src/a%20%5Bdraft%5D%281%29%22.py#L1-L2 \"src/a \\[draft\\]\\(1\\)'.py\"" in body
    assert function_link(built.findings[0].candidate.new, built.run).startswith("[clip](https://git.example.com/")
    built.run = Run()
    body = as_markdown(built)
    assert "/blob/" not in body and "src/a \\[draft\\]\\(1\\)\".py:1" in body
    assert function_link(built.findings[0].candidate.new, built.run) == escaped(built.findings[0].candidate.new.qualname)


def test_evidence_separates_judge_scores_from_similarity_and_cache() -> None:
    body = as_markdown(report(finding("drifted", 0.95, cached=True)))
    assert "🔴 **`clip` ≈ `shorten`** · drifted 0.95 · similarity 0.71 · from the verdict store" in body
    assert "the copies already behave differently" in body and "1 from the verdict store" in body
    assert "· new verdict" in as_markdown(report(finding("duplicate")))


def test_a_repository_scan_reads_as_an_audit_of_existing_code_that_never_blocks() -> None:
    scan = clean_report(finding("drifted", 0.95, owner="new"), changed=0, scope="repository").as_warnings()
    assert scan.repository_wide and not report(finding("duplicate")).repository_wide
    body = as_markdown(scan)
    assert "### dry-lint audit · 1 duplicated concept in existing code" in body
    assert "Not introduced by this pull request, and never blocking." in body
    assert "1 pair judged" in body and "changed function" not in body and "<sub>changed</sub>" not in body
    assert "keep the first copy" in body and "in either function" in body and "dry-lint: override" not in body


def test_the_status_note_has_a_slot_between_the_result_and_the_evidence() -> None:
    body = as_markdown(report(finding("duplicate")))
    assert body.index("### dry-lint") < body.index(NOTE_SLOT) < body.index("| :-: |")


def test_json_report_round_trips() -> None:
    built = report(finding("duplicate", existing="a"), finding("separate", existing="b"))
    loaded = Report.model_validate_json(render(built, "json", SETTINGS))
    assert loaded.model_dump() == built.model_dump() and json.loads(render(built, "json", SETTINGS))["schema"] == 5


def test_sarif_puts_each_finding_on_the_changed_function_with_the_existing_one_related() -> None:
    data = json.loads(as_sarif(report(finding("drifted", 0.95, existing="a"), finding(None, existing="b"), finding("separate", existing="c"))))
    assert data["version"] == "2.1.0"
    [run] = data["runs"]
    assert [(r["ruleId"], r["level"]) for r in run["results"]] == [("dry-lint/drifted", "error"), ("dry-lint/candidate", "note")]
    first = run["results"][0]
    assert first["locations"][0]["physicalLocation"] == {"artifactLocation": {"uri": "src/widgets/caption.py"},
                                                         "region": {"startLine": 1, "endLine": 2}}
    assert first["relatedLocations"][0]["message"]["text"] == "src/text.py::a"
    assert first["partialFingerprints"]["dryLintPair/v1"] == pair("a").key


def test_the_check_run_fails_only_for_blocking_findings_unless_warn_only() -> None:
    blocking = report(finding("drifted", 0.93, existing="a"), finding("duplicate", 0.85, existing="b"))
    body = json.loads(as_check_run(blocking))
    assert (body["name"], body["head_sha"], body["status"], body["conclusion"]) == ("dry-lint", HEAD, "completed", "failure")
    assert body["output"]["title"] == "2 duplicated concept(s)" and body["output"]["summary"].startswith(MARKER)
    assert [a["annotation_level"] for a in body["output"]["annotations"]] == ["failure", "warning"]
    warnings = json.loads(as_check_run(blocking, warn_only=True))
    assert warnings["conclusion"] == "neutral"
    assert [a["annotation_level"] for a in warnings["output"]["annotations"]] == ["warning", "warning"]
    assert "blocking" not in warnings["output"]["summary"]
    assert blocking.findings[0].blocking
    assert json.loads(as_check_run(report(finding("duplicate", 0.85))))["conclusion"] == "neutral"
    clean = json.loads(as_check_run(report(finding("separate"))))
    assert (clean["conclusion"], clean["output"]["title"], clean["output"]["annotations"]) == ("success", "No duplicated concepts", [])


@pytest.mark.parametrize("form", FORMATS)
def test_every_format_renders(form: str) -> None:
    assert render(report(finding("duplicate")), form, SETTINGS)


def test_a_path_that_could_close_a_code_fence_is_shown_escaped_instead() -> None:
    built = report(finding("duplicate")).model_copy(deep=True)
    built.findings[0].candidate.existing.path = "src/```evil.py"
    body = as_markdown(built)
    assert "```python" not in body and "distinct-from src/\\`\\`\\`evil.py::shorten" in body


def test_the_judging_line_names_judges_band_thresholds_and_the_bill() -> None:
    summary = JudgingSummary(preset="jev+sonnet", judge="jev:reuse-v2", escalation="anthropic:dry-v1:claude-sonnet-5-5",
                             band=(0.5, 0.91), report_at=0.6, fail_at=0.7, budget_usd=0.25,
                             spend=[Spend(judge="jev:reuse-v2", calls=4, usd=0.0002),
                                    Spend(judge="anthropic:dry-v1:claude-sonnet-5-5", calls=1, skipped=2, usd=0.0033)])
    assert summary.line() == ("preset jev+sonnet · jev:reuse-v2 > anthropic:dry-v1:claude-sonnet-5-5 on [0.5, 0.91) · "
                              "reports at 0.6, fails at 0.7 · est. $0.004 of $0.25 budget · 2 pairs not judged (budget)")
    later = summary.model_copy(update={"budget_usd": 0.04, "spent_before": 0.02, "pull_request": True})
    assert "est. $0.004 ($0.024 so far) of $0.04 for this pull request" in later.line()
    plain = JudgingSummary(judge="jev:reuse-v2", report_at=0.8, fail_at=0.8, budget_usd=0.25,
                           spend=[Spend(judge="claude-code:x", calls=3, usd=0.01, subscription=True), Spend(judge="c", calls=1, usd=None)])
    assert plain.line() == "jev:reuse-v2 · reports and fails at 0.8 · cost unknown · 3 subscription calls"
    assert JudgingSummary().line() == "no judge · reports and fails at 0.8 · est. $0.000 of $0 budget"
    failed = summary.model_copy(update={"spend": [Spend(judge="claude-code:dry-v1:claude-opus-5-5", failed=3,
                                                        error="OAuth session expired")]})
    assert failed.line().endswith("· claude-code:dry-v1:claude-opus-5-5 failed (OAuth session expired): 3 pairs kept "
                                  "the first judge's answer, asked again next run")


def test_every_view_states_the_judging() -> None:
    summary = JudgingSummary(preset="jev", judge="jev:reuse-v2", report_at=0.8, fail_at=0.8, budget_usd=0.25)
    built = Report.build([finding("duplicate")], SETTINGS, run=Run(repository="o/r", head="abc"), judge="jev:reuse-v2",
                         judging=summary)
    assert as_text(built).endswith("judging: preset jev · jev:reuse-v2 · reports and fails at 0.8 · est. $0.000 of $0.25 budget")
    assert "<sub>preset jev · jev:reuse-v2 · reports and fails at 0.8" in as_markdown(built)
    clean = Report.build([finding("separate", 0.3)], SETTINGS, judge="jev:reuse-v2", judging=summary)
    assert as_markdown(clean).endswith("<sub>preset jev · jev:reuse-v2 · reports and fails at 0.8 · est. $0.000 of "
                                       "$0.25 budget</sub>")  # the bill shows on a clean pull request too
    assert Report.model_validate_json(as_json(built)).judging == summary


def escalated(score: float, second_opinion: str | None) -> Finding:
    verdict = Verdict(label="duplicate", score=score, judge="jev", judge_version="v", second_opinion=second_opinion)
    return Finding(candidate=pair(), verdict=verdict)


@pytest.mark.parametrize("score, second_opinion, reported", [
    (0.6, "opus", True),     # the second judge's answer: its own threshold
    (0.6, None, False),      # the first judge alone, past the budget: held to its own bar
    (0.85, None, True),
])  # fmt: skip
def test_answers_without_a_second_opinion_are_held_to_the_first_judges_own_bar(score, second_opinion, reported) -> None:
    settings = Settings(escalate=Escalation(use="opus", between=(0.5, 0.91), first_at=0.8), report_at=0.55, fail_at=0.55)
    [marked] = Report.build([escalated(score, second_opinion)], settings).findings
    assert (marked.reported, marked.blocking) == (reported, reported)


def test_without_a_first_judge_bar_every_answer_meets_the_same_thresholds() -> None:
    settings = Settings(escalate=Escalation(use="opus", between=(0.5, 0.91)), report_at=0.55, fail_at=0.55)
    assert Report.build([escalated(0.6, None)], settings).findings[0].reported
    assert Report.build([escalated(0.6, None)], Settings(escalate=None, report_at=0.55)).findings[0].reported
