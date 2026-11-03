import math
from pathlib import Path

import pytest

from dry_lint.bench import (
    GoldFunction,
    GoldPair,
    as_function,
    auc,
    bench_comparer,
    bench_judge,
    intervals,
    load_gold,
    precision_recall,
)
from dry_lint.detector import Detector
from dry_lint.extractors import PythonExtractor
from dry_lint.models import Candidate, Verdict
from dry_lint.settings import Escalation, Settings

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
    assert "AUC 0.67" in text and "precision 33% (" in text and "90% intervals" in text and "recall 100%" in text


def test_a_judge_benchmark_without_labelled_pairs_is_empty_not_an_error() -> None:
    result = bench_judge([gold("e", "x", "borderline")], TableJudge({}), Settings(), PythonExtractor())
    assert (result.pairs, result.precision, result.recall, result.bands) == (0, 0.0, 0.0, [])


def test_gold_code_becomes_the_named_function() -> None:
    method = as_function(GoldFunction(id="pkg/box.py::Box.open", code="    def open(self):\n        return 1\n"), PythonExtractor())
    assert (method.qualname, method.tokens != []) == ("pkg/box.py::Box.open", True)
    truncated = as_function(GoldFunction(id="a.py::Box.f", code="    def f(self, x=[\n        1,"), PythonExtractor())
    assert (truncated.qualname, truncated.code, truncated.lines) == ("a.py::Box.f", "def f(self, x=[\n    1,", 2)


def test_gold_sets_load_from_json_lines(tmp_path: Path) -> None:
    path = tmp_path / "gold.jsonl"
    path.write_text(gold("a", "x", "duplicate").model_dump_json() + "\n\n" + gold("b", "x", "separate").model_dump_json() + "\n")
    assert [g.label for g in load_gold(path)] == ["duplicate", "separate"]


def test_a_toml_gold_set_holds_the_same_pairs_as_json_lines(tmp_path: Path) -> None:
    lines = tmp_path / "gold.jsonl"
    lines.write_text(gold("a", "x", "duplicate").model_dump_json() + "\n")
    readable = tmp_path / "gold.toml"
    readable.write_text("""[[pair]]
label = "duplicate"
weight = 1.0
note = "extra fields are ignored"

[pair.new]
id = "a.py::a"
code = '''
def a(x):
    return x
'''

[pair.existing]
id = "b.py::x"
code = '''
def x(text):
    return text
'''
""")
    [pair] = load_gold(readable)
    assert pair.model_dump(exclude={"new", "existing"}) == load_gold(lines)[0].model_dump(exclude={"new", "existing"})
    assert (pair.new.id, pair.new.code, pair.existing.id) == ("a.py::a", "def a(x):\n    return x\n", "b.py::x")
    empty = tmp_path / "empty.toml"
    empty.write_text("# no pairs yet\n")
    assert load_gold(empty) == []


def test_the_comparer_benchmark_checks_each_gold_duplicate_is_proposed(repo: Repo) -> None:
    detector = Detector.for_repository(repo.root, Settings())
    twin = GoldPair(new=GoldFunction(id="src/widgets/caption.py::preview_caption_text", code=TWIN),
                    existing=GoldFunction(id="src/text.py::shorten_text", code=EXISTING), label="duplicate")
    unrelated = GoldPair(new=GoldFunction(id="src/widgets/caption.py::register_widget", code=TWIN),
                         existing=GoldFunction(id="src/text.py::shorten_text", code=EXISTING), label="duplicate", weight=3)
    gone = gold("a", "x", "duplicate")
    result = bench_comparer([twin, unrelated, gone, gold("b", "x", "separate")], detector)
    assert (result.comparer, result.neighbours, result.duplicates, result.missing) == ("tfidf:2", 3, 2, 1)
    assert result.recall == pytest.approx(0.25)
    assert "partner among the top 3 proposed: 25%" in result.as_text()
    assert bench_comparer([gone], detector).recall == 0.0


def test_the_judge_benchmark_measures_escalation_as_it_runs() -> None:
    pairs = [gold("a", "x", "duplicate"), gold("b", "x", "separate")]
    first = TableJudge({"a": 0.7, "b": 0.85})
    second = TableJudge({"a": 0.95, "b": 0.2})
    second.name = "second"
    settings = Settings(escalate=Escalation(use="second", between=(0.6, 0.91)))
    result = bench_judge(pairs, first, settings, PythonExtractor(), escalation=second)
    assert result.judge == "table:1 > second:1"
    assert (result.precision, result.recall, result.auc) == (1.0, 1.0, 1.0)
    assert bench_judge(pairs, first, settings, PythonExtractor()).precision == 0.0


def test_intervals_contain_the_estimate_and_widen_with_heavy_rare_pairs() -> None:
    steady = [("high", True, 1.0, True)] * 9 + [("high", False, 1.0, True)]
    (p_low, p_high), (r_low, r_high) = intervals(steady)
    assert p_low <= precision_recall(steady)[0] <= p_high and (r_low, r_high) == (1.0, 1.0)
    rare = steady + [("low", True, 30.0, False)] + [("low", False, 30.0, False)] * 9
    (_, _), (r_low, r_high) = intervals(rare)
    assert r_high - r_low > 0.5  # one heavily weighted duplicate can swing recall
    assert intervals([]) == ((0.0, 0.0), (0.0, 0.0))


def test_a_separate_label_is_never_reported_whatever_its_score() -> None:
    class Contrary(TableJudge):
        def judge(self, candidates, settings):
            return [Verdict(label="separate", score=0.95, judge=self.name) for _ in candidates]

    result = bench_judge([gold("a", "x", "duplicate")], Contrary({}), Settings(), PythonExtractor())
    assert (result.precision, result.recall) == (0.0, 0.0)


def test_the_benchmark_measures_the_failing_threshold_and_the_cost_too() -> None:
    class PricedTable(TableJudge):
        model = "claude-sonnet-5-5"

    pairs = [gold("a", "x", "duplicate"), gold("b", "x", "duplicate"), gold("c", "x", "separate")]
    settings = Settings(report_at=0.6, fail_at=0.8)
    result = bench_judge(pairs, PricedTable({"a": 0.9, "b": 0.7, "c": 0.65}), settings, PythonExtractor())
    assert (result.precision, result.recall) == (pytest.approx(2 / 3), 1.0)
    assert (result.fail_at, result.fail_precision, result.fail_recall) == (0.8, 1.0, 0.5)
    assert 0.0005 < result.usd_per_pair < 0.01
    text = result.as_text(settings)
    assert "at fail_at 0.8: precision 100%" in text and "cost: est. $0.00" in text
    unpriced = bench_judge(pairs, TableJudge({"a": 0.9, "b": 0.7, "c": 0.65}), Settings(), PythonExtractor())
    assert unpriced.usd_per_pair is None and "cost: unknown" in unpriced.as_text(Settings())
    assert "at fail_at" not in unpriced.as_text(Settings())


def test_the_benchmark_refuses_to_measure_when_the_second_judge_fails() -> None:
    class Broken(TableJudge):
        def judge(self, candidates: list[Candidate], settings: Settings) -> list[Verdict]:
            raise ValueError("OAuth session expired")

    settings = Settings(escalate=Escalation(use="second", between=(0.5, 1.0)))
    with pytest.raises(ValueError, match="failed, so nothing was measured: OAuth session expired"):
        bench_judge([gold("a", "x", "duplicate")], TableJudge({"a": 0.7}), settings, PythonExtractor(), Broken({}))


def test_subscription_calls_are_counted_and_priced_at_their_models_list_price() -> None:
    class Subscribed(TableJudge):
        subscription = True

    class SubscribedSonnet(Subscribed):
        model = "claude-sonnet-5-5"

    unknown = bench_judge([gold("a", "x", "duplicate")], Subscribed({"a": 0.9}), Settings(), PythonExtractor())
    assert (unknown.usd_per_pair, unknown.subscription_calls) == (None, 1)
    assert "1 subscription calls" in unknown.as_text(Settings())
    sonnet = bench_judge([gold("a", "x", "duplicate")], SubscribedSonnet({"a": 0.9}), Settings(), PythonExtractor())
    assert sonnet.usd_per_pair > 0 and sonnet.subscription_calls == 1


def test_the_benchmark_holds_unescalated_answers_to_the_first_judges_bar_as_a_report_does() -> None:
    pairs = [gold("a", "x", "duplicate"), gold("b", "y", "separate")]
    first, second = TableJudge({"a": 0.7, "b": 0.7}), TableJudge({"a": 0.9, "b": 0.7})
    second.name = "second"
    settings = Settings(escalate=Escalation(use="second", between=(0.75, 0.91), first_at=0.8), report_at=0.6)
    alone = bench_judge(pairs, first, settings, PythonExtractor(), escalation=second)
    assert (alone.precision, alone.recall) == (0.0, 0.0)  # 0.7 is below the first judge's 0.8, and not escalated
    lowered = settings.model_copy(update={"escalate": Escalation(use="second", between=(0.6, 0.91), first_at=0.8)})
    both = bench_judge(pairs, first, lowered, PythonExtractor(), escalation=second)
    assert (both.precision, both.recall) == (0.5, 1.0)  # the second judge's answers meet report_at
