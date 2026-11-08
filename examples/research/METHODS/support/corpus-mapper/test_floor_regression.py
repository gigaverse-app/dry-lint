"""Guard missing-span defaults and preserve the raw retrieval result during metadata repair."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_baseline import correct_floor, query_length  # noqa: E402


@pytest.mark.parametrize(
    "source,lines,provenance",
    [
        (
            {"source_id": "a.py::f", "code": "def f():\n    return 1\n"},
            2,
            "inferred_from_snippet_production_as_function",
        ),
        (
            {"source_id": "a.py::f", "code": "def f():\n    a=1\n    b=2\n    c=3\n    d=4\n    return a+b+c+d\n"},
            6,
            "inferred_from_snippet_production_as_function",
        ),
        (
            {"source_id": "a.py::f", "line": 10, "end_line": 17, "code": "def f():\n    return 1"},
            8,
            "supplied_valid_span",
        ),
        (
            {"source_id": "a.py::f", "end_line": 99, "code": "def f():\n    return 1"},
            2,
            "inferred_from_snippet_production_as_function",
        ),
        ({"source_id": "a.py::f", "line": 0, "end_line": 0}, None, "unknown_no_valid_span_or_snippet"),
        ({"source_id": "a.py::f"}, None, "unknown_no_valid_span_or_snippet"),
    ],
)
def test_query_length_requires_complete_valid_span(source, lines, provenance):
    assert query_length(source) == (lines, provenance)


def test_long_missing_span_snippet_uses_long_function_floor_and_preserves_ranks():
    row = dict(
        query="a.py::f",
        target="b.py::g",
        raw_rank=2,
        score=0.4,
        cross_file_rank=2,
        same_file=False,
        top1=False,
        top3=True,
        top20=True,
    )
    before = copy.deepcopy(row)
    correct_floor(
        row, {"source_id": "a.py::f", "code": "def f():\n    a=1\n    b=2\n    c=3\n    d=4\n    return a+b+c+d\n"}
    )
    assert row["query_lines"] == 6
    assert row["default_floor"] == 0.5
    assert row["first_loss"] == "score_floor"
    for key in before:
        assert row[key] == before[key]


def test_no_source_text_keeps_floor_unknown():
    row = dict(query="a.py::f", target="b.py::g", score=0.4, cross_file_rank=2, same_file=False)
    correct_floor(row, {"source_id": "a.py::f"})
    assert row["default_floor"] is None
    assert not row["default_floor_known"]
    assert row["first_loss"] == "unknown_query_length"
