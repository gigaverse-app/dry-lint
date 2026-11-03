import math
from pathlib import Path

import pytest

from dry_lint.bench import GoldFunction, GoldPair, as_function, auc, bench_comparer, bench_judge, load_gold
from dry_lint.detector import Detector
from dry_lint.extractors import PythonExtractor
from dry_lint.models import Candidate, Verdict
from dry_lint.settings import Settings

from conftest import EXISTING, TWIN, Repo


def gold(new: str, existing: str, label: str, weight: float = 1.0) -> GoldPair:
    return GoldPair(new=GoldFunction(id=f"new.py::{new}", code=f"def {new}(x):\n    return x\n"),
                    existing=GoldFunction(id=f"old.py::{existing}", code=f"def {existing}(y):\n    return y\n"),
                    label=label, weight=weight)


class TableJudge:
    """Scores each pair by the new function's name."""

    name, version = "table", "1"

    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores

    def judge(self, candidates: list[Candidate], settings: Settings) -> list[Verdict]:
        return [Verdict(label="duplicate", score=self.scores[c.new.name], judge=self.name) for c in candidates]


def test_auc_is_the_chance_a_duplicate_outscores_a_separate_pair() -> None:
    assert auc([(0.9, True, 1), (0.1, False, 1)]) == 1.0
    assert auc([(0.5, True, 1), (0.5, False, 1)]) == 0.5
    assert auc([(0.2, True, 1), (0.6, False, 3), (0.1, False, 1)]) == pytest.approx(0.25)
    assert math.isnan(auc([(0.2, True, 1)]))


def test_the_judge_benchmark_reports_auc_precision_recall_and_bands() -> None:
    pairs = [gold("a", "x", "duplicate"), gold("b", "x", "duplicate"), gold("c", "x", "separate", weight=2),
             gold("d", "x", "separate"), gold("e", "x", "borderline")]
    result = bench_judge(pairs, TableJudge({"a": 0.95, "b": 0.65, "c": 0.85, "d": 0.05}), Settings(), PythonExtractor())
    assert (result.judge, result.pairs, result.duplicates) == ("table:1", 4, 2)
    assert result.precision == pytest.approx(1 / 3) and result.recall == 0.5 and result.recall_at_drop == 1.0
    assert result.auc == pytest.approx(4 / 6)  # a beats c (weight 2) and d; b beats only d
    assert [(b.low, b.duplicates, b.separate) for b in result.bands] == [(0.0, 0, 1), (0.6, 1, 0), (0.8, 0, 2), (0.9, 1, 0)]
    text = result.as_text(Settings())
    assert "AUC 0.67" in text and "precision 33%, recall 50%" in text and "recall 100%" in text


def test_a_judge_benchmark_without_labelled_pairs_is_empty_not_an_error() -> None:
    result = bench_judge([gold("e", "x", "borderline")], TableJudge({}), Settings(), PythonExtractor())
    assert (result.pairs, result.precision, result.recall, result.bands) == (0, 0.0, 0.0, [])


def test_gold_code_becomes_the_named_function() -> None:
    method = as_function(GoldFunction(id="pkg/box.py::Box.open", code="    def open(self):\n        return 1\n"), PythonExtractor())
    assert (method.qualname, method.tokens != []) == ("pkg/box.py::Box.open", True)
    with pytest.raises(ValueError, match="no function the python extractor can read"):
        as_function(GoldFunction(id="a.py::f", code="x = 1"), PythonExtractor())


def test_gold_sets_load_from_json_lines(tmp_path: Path) -> None:
    path = tmp_path / "gold.jsonl"
    path.write_text(gold("a", "x", "duplicate").model_dump_json() + "\n\n" + gold("b", "x", "separate").model_dump_json() + "\n")
    assert [g.label for g in load_gold(path)] == ["duplicate", "separate"]


def test_the_comparer_benchmark_checks_each_gold_duplicate_is_proposed(repo: Repo) -> None:
    detector = Detector.for_repository(repo.root, Settings())
    twin = GoldPair(new=GoldFunction(id="src/widgets/caption.py::preview_caption_text", code=TWIN),
                    existing=GoldFunction(id="src/text.py::shorten_text", code=EXISTING), label="duplicate")
    unrelated = GoldPair(new=GoldFunction(id="src/widgets/caption.py::register_widget", code=TWIN),
                         existing=GoldFunction(id="src/text.py::shorten_text", code=EXISTING), label="duplicate", weight=3)
    gone = gold("a", "x", "duplicate")
    result = bench_comparer([twin, unrelated, gone, gold("b", "x", "separate")], detector)
    assert (result.comparer, result.neighbours, result.duplicates, result.missing) == ("tfidf:1", 3, 2, 1)
    assert result.recall == pytest.approx(0.25)
    assert "partner among the top 3 proposed: 25%" in result.as_text()
    assert bench_comparer([gone], detector).recall == 0.0
