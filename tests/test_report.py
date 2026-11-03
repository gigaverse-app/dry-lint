import json

import pytest

from dry_lint.models import Candidate, Run, Verdict
from dry_lint.report import (
    FORMATS,
    MARKER,
    Finding,
    Report,
    as_check_run,
    as_github,
    as_markdown,
    as_sarif,
    as_text,
    escaped,
    plain,
    render,
)
from dry_lint.settings import Settings

from conftest import function

SETTINGS = Settings()
NEW = function("src/widgets/caption.py", "def clip(text, n):\n    return text[:n]\n")


def pair(existing: str = "shorten", path: str = "src/text.py", filtered: str | None = None) -> Candidate:
    return Candidate(new=NEW, existing=function(path, f"def {existing}(text, limit):\n    return text[:limit]\n"),
                     similarity=0.71, comparer="tfidf:1", filtered=filtered)


def finding(label: str | None, score: float = 0.9, owner: str = "existing", why: str = "", cached: bool = False,
            existing: str = "shorten") -> Finding:
    verdict = Verdict(label=label, score=score, owner=owner, why=why, judge="jev", judge_version="v") if label else None
    return Finding(candidate=pair(existing), verdict=verdict, cached=cached)


def report(*findings: Finding, filtered: list[Candidate] = (), judge: str | None = "jev:v") -> Report:
    return Report.build(list(findings), SETTINGS, filtered=filtered, run=Run(repository="o/r", pull_request=5, head="abc"),
                        changed=2, judge=judge)


def test_only_unjudged_candidates_and_confident_duplicates_are_visible() -> None:
    built = report(finding(None, existing="a"), finding("duplicate", 0.8, existing="b"), finding("drifted", 0.95, existing="c"),
                   finding("duplicate", 0.79, existing="d"), finding("separate", 0.95, existing="e"))
    assert [f.candidate.existing.name for f in built.visible] == ["c", "b", "a"]
    assert [f.reported for f in built.findings] == [True, True, False, False, False]


def test_findings_are_ordered_drifted_first_then_by_score_and_count_their_family() -> None:
    built = report(finding("duplicate", 0.85, existing="a"), finding("duplicate", 0.95, existing="b"),
                   finding("drifted", 0.81, existing="c"))
    assert [f.candidate.existing.name for f in built.findings] == ["c", "b", "a"]
    assert {f.family for f in built.findings} == {3}


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


def test_github_annotations_are_warnings_for_duplicates_and_errors_for_drift() -> None:
    lines = as_github(report(finding("duplicate", existing="a"), finding("drifted", existing="b"),
                             finding("separate", existing="c"))).splitlines()
    assert [line.split(" ", 1)[0] for line in lines] == ["::error", "::warning"]
    assert lines[1].startswith("::warning file=src/widgets/caption.py,line=1,endLine=2,title=dry-lint::clip looks like")


def test_github_annotations_escape_percent_signs_and_judge_text_is_one_line() -> None:
    line = as_github(report(finding("duplicate", why="100% the same\nreally")))
    assert "100%25 the same really" in line and "\n" not in line


def test_markdown_comment_lists_findings_under_a_stable_marker() -> None:
    body = as_markdown(report(finding("duplicate", 0.88, "existing", "same truncation"), finding(None, existing="other")))
    assert body.startswith(MARKER)
    assert "| `src/widgets/caption.py::clip` | `src/text.py::shorten` | **duplicate** 0.88 | call the existing function; same truncation (2 look-alikes) |" in body
    assert "| similarity 0.71 | not judged (2 look-alikes) |" in body


def test_markdown_comment_says_so_when_nothing_is_found() -> None:
    body = as_markdown(report(finding("separate")))
    assert body.startswith(MARKER) and "No duplicated concepts" in body


def test_without_a_judge_the_comment_lists_nothing_and_says_how_to_get_one() -> None:
    body = as_markdown(report(finding(None), finding(None, existing="other"), judge=None))
    assert body.startswith(MARKER) and "No judge is configured" in body and "2 look-alike pair(s)" in body
    assert "`src/text.py::shorten`" not in body


def test_markdown_caps_the_rows_and_lists_settled_pairs_folded() -> None:
    many = [finding("duplicate", 0.9, existing=f"f{i}") for i in range(4)]
    body = as_markdown(report(*many, filtered=[pair("z", filtered="declared pattern: one per resource")]), max_findings=2)
    assert body.count("| `src/widgets/caption.py::clip`") == 2 and "And 2 more" in body
    assert "<details><summary>Not reported (1 settled by a rule)</summary>" in body
    assert "- `src/widgets/caption.py::clip` ~ `src/text.py::z`: declared pattern: one per resource" in body


def test_judge_text_cannot_inject_markdown_links_or_html() -> None:
    hostile = "ignore this [click](https://evil.example) <img src=x> | col " + "x" * 400
    body = as_markdown(report(finding("duplicate", why=hostile)))
    assert "[click](" not in body and "\\<img src=x\\>" in body and "<img" not in body.replace("\\<", "")
    assert "\\| col" in body
    assert len(escaped(hostile)) < 400 and plain(hostile).endswith("…") and len(plain(hostile)) == 300
    assert plain("  two\n lines ") == "two lines"


def test_markdown_uses_the_reason_alone_when_there_is_no_owner() -> None:
    assert "| **duplicate** 0.90 | same truncation |" in as_markdown(report(finding("duplicate", owner="", why="same truncation")))


def test_json_report_round_trips() -> None:
    built = report(finding("duplicate", existing="a"), finding("separate", existing="b"))
    loaded = Report.model_validate_json(render(built, "json", SETTINGS))
    assert loaded.model_dump() == built.model_dump() and json.loads(render(built, "json", SETTINGS))["schema"] == 2


def test_sarif_puts_each_finding_on_the_changed_function_with_the_existing_one_related() -> None:
    data = json.loads(as_sarif(report(finding("drifted", existing="a"), finding(None, existing="b"), finding("separate", existing="c"))))
    assert data["version"] == "2.1.0"
    [run] = data["runs"]
    assert [(r["ruleId"], r["level"]) for r in run["results"]] == [("dry-lint/drifted", "error"), ("dry-lint/candidate", "note")]
    first = run["results"][0]
    assert first["locations"][0]["physicalLocation"] == {"artifactLocation": {"uri": "src/widgets/caption.py"},
                                                         "region": {"startLine": 1, "endLine": 2}}
    assert first["relatedLocations"][0]["message"]["text"] == "src/text.py::a"
    assert first["partialFingerprints"]["dryLintPair/v1"] == pair("a").key


def test_the_check_run_is_neutral_with_findings_and_never_fails() -> None:
    body = json.loads(as_check_run(report(finding("drifted", existing="a"), finding("duplicate", existing="b"))))
    assert (body["name"], body["head_sha"], body["status"], body["conclusion"]) == ("dry-lint", "abc", "completed", "neutral")
    assert body["output"]["title"] == "2 duplicated concept(s)" and body["output"]["summary"].startswith(MARKER)
    assert [a["annotation_level"] for a in body["output"]["annotations"]] == ["failure", "warning"]
    clean = json.loads(as_check_run(report(finding("separate"))))
    assert (clean["conclusion"], clean["output"]["title"], clean["output"]["annotations"]) == ("success", "No duplicated concepts", [])


@pytest.mark.parametrize("form", FORMATS)
def test_every_format_renders(form: str) -> None:
    assert render(report(finding("duplicate")), form, SETTINGS)
