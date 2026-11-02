import json

from dry_lint.detector import Candidate
from dry_lint.report import MARKER, Finding, as_github, as_json, as_markdown, as_text, visible
from dry_lint.settings import Settings
from dry_lint.store import Verdict

from conftest import function

CANDIDATE = Candidate(
    new=function("src/widgets/caption.py", "def clip(text, n):\n    return text[:n]\n"),
    existing=function("src/text.py", "def shorten(text, limit):\n    return text[:limit]\n"),
    similarity=0.71,
)
SETTINGS = Settings()


def finding(label: str | None, score: float = 0.9, owner: str = "existing", why: str = "", cached: bool = False) -> Finding:
    verdict = Verdict(label=label, score=score, owner=owner, why=why, judge="test") if label else None
    return Finding(candidate=CANDIDATE, verdict=verdict, cached=cached)


def test_only_unjudged_candidates_and_confident_duplicates_are_shown() -> None:
    shown = [finding(None), finding("duplicate", 0.8), finding("drifted", 0.95)]
    hidden = [finding("duplicate", 0.79), finding("separate", 0.95)]
    assert visible(shown + hidden, SETTINGS) == shown
    assert [f.reported(SETTINGS) for f in shown] == [False, True, True]


def test_text_report_gives_location_verdict_advice_and_a_way_out() -> None:
    text = as_text([finding("drifted", 0.91, "shared", "same truncation", cached=True)], SETTINGS, skipped=["x ~ y: rule"])
    assert text.startswith("src/widgets/caption.py:1: clip looks like src/text.py::shorten (drifted)")
    for part in ["judge 0.91 (cached)", "behave differently", "extract a shared helper", "same truncation",
                 "similarity 0.71", "# dry-lint: distinct-from src/text.py::shorten"]:
        assert part in text
    assert text.endswith("1 candidate pair(s), 1 judged, 1 shown, 1 skipped by rule")


def test_github_annotations_are_warnings_for_duplicates_and_errors_for_drift() -> None:
    lines = as_github([finding("duplicate"), finding("drifted"), finding("separate")], SETTINGS).splitlines()
    assert [line.split(" ", 1)[0] for line in lines] == ["::warning", "::error"]
    assert lines[0].startswith("::warning file=src/widgets/caption.py,line=1,endLine=2,title=dry-lint::clip looks like")


def test_github_annotations_escape_newlines_and_percent_signs() -> None:
    line = as_github([finding("duplicate", why="100% the same\nreally")], SETTINGS)
    assert "100%25 the same%0Areally" in line and "\n" not in line


def test_markdown_comment_lists_findings_under_a_stable_marker() -> None:
    body = as_markdown([finding("duplicate", 0.88, "existing", "same truncation"), finding(None)], SETTINGS)
    assert body.startswith(MARKER)
    assert "| `src/widgets/caption.py::clip` | `src/text.py::shorten` | duplicate 0.88 | call the existing function. same truncation |" in body
    assert "| similarity 0.71 | not judged |" in body


def test_markdown_comment_says_so_when_nothing_is_found() -> None:
    body = as_markdown([finding("separate")], SETTINGS)
    assert body.startswith(MARKER) and "No duplicated concepts" in body


def test_markdown_uses_the_reason_alone_when_there_is_no_owner() -> None:
    assert "| duplicate 0.90 | same truncation |" in as_markdown([finding("duplicate", owner="", why="same truncation")], SETTINGS)


def test_json_report_includes_every_finding_and_whether_it_is_reported() -> None:
    data = json.loads(as_json([finding("duplicate"), finding("separate")], SETTINGS))
    assert [item["reported"] for item in data] == [True, False]
    assert data[0]["candidate"]["new"]["name"] == "clip" and data[0]["verdict"]["label"] == "duplicate"
