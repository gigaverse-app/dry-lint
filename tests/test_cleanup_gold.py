"""Frozen public cleanup examples exercise retrieval without asking a model in CI."""

import ast
import hashlib
import textwrap
import tomllib
from collections import defaultdict
from pathlib import Path

import pytest

from dry_lint.bench import as_function, bench_comparer, load_gold
from dry_lint.detector import Detector
from dry_lint.extractors import PythonExtractor
from dry_lint.judges.command import prompt
from dry_lint.models import Candidate
from dry_lint.plugins import load
from dry_lint.settings import Settings

GOLD = Path(__file__).resolve().parents[1] / "examples" / "pytest-obligation-gold.toml"
ROWS = tomllib.loads(GOLD.read_text(encoding="utf-8"))["pair"]
PAIRS = load_gold(GOLD)


@pytest.mark.parametrize("row,pair", list(zip(ROWS, PAIRS, strict=True)), ids=[row["case"] for row in ROWS])
def test_frozen_source_reaches_the_judge_without_answer_leakage(row, pair) -> None:
    extractor = PythonExtractor()
    functions = []
    for source, side in ((row["new"], pair.new), (row["existing"], pair.existing)):
        code = textwrap.dedent(source["code"]).strip() + "\n"
        assert hashlib.sha256(code.encode()).hexdigest() == source["sha256"]
        assert f"/blob/{row['revision']}/" in source["source"]
        assert "dry-lint:" not in code
        parsed = ast.parse(code)
        assert isinstance(parsed.body[0], ast.FunctionDef | ast.AsyncFunctionDef)
        assert parsed.body[0].name == source["id"].rsplit(".", 1)[-1].split("::")[-1]
        function = as_function(side, extractor)
        assert function.qualname == source["id"]
        # The production extractor supplies the function body; decorators stay in the pinned source.
        assert function.code.strip() == ast.get_source_segment(code, parsed.body[0]).strip()
        functions.append(function)
    rendered = prompt(Candidate(new=functions[0], existing=functions[1], similarity=0))
    assert all(function.code in rendered for function in functions)
    assert row["rationale"] not in rendered
    assert row["label_source"] not in rendered


def test_cleanup_pairs_include_the_stop_reporting_control() -> None:
    transitions = defaultdict(dict)
    for row in ROWS:
        if transition := row.get("transition"):
            transitions[transition][row["case"].rsplit("-", 1)[-1]] = row["label"]
    assert set(transitions) == {"imports", "identities", "reply-lifetime", "gap-grammar"}
    assert all(labels == {"before": "duplicate", "after": "separate"} for labels in transitions.values())
    assert len({row["case"] for row in ROWS}) == len(ROWS)
    assert {pair.label for pair in PAIRS} == {"duplicate", "separate", "borderline"}


def test_known_repeated_operations_are_retrieved_in_the_frozen_positive_panel() -> None:
    """Guard retrieval of actual removed copies; this is not full-repository recall."""
    extractor, settings = PythonExtractor(), Settings()
    positives = [pair for pair in PAIRS if pair.label == "duplicate"]
    functions = {
        function.qualname: function
        for pair in positives
        for function in (as_function(pair.new, extractor), as_function(pair.existing, extractor))
    }
    detector = Detector(list(functions.values()), settings, load("comparers", settings.comparer), [extractor])
    result = bench_comparer(positives, detector)
    assert result.missing == 0
    assert result.duplicates == len(positives) == 6
    assert result.recall == 1.0
