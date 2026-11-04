"""The optional source runs real upstream extraction and scoring through dry-lint."""

import json
import sys

import pytest

from dry_lint.cli import main
from dry_lint.detector import Detector
from dry_lint.dryer import DryerComparer
from dry_lint.extractors import PythonExtractor
from dry_lint.settings import Pattern, Settings

from conftest import Repo, function

dryer = pytest.importorskip("dryer")


def source_settings(**options) -> Settings:
    return Settings(comparer={"use": "dryer", **options})


def build(functions, settings: Settings) -> Detector:
    return Detector(functions, settings, DryerComparer(**settings.comparer.options()), [PythonExtractor()])


SHAPE = "def compute(values):\n    total = sum(values)\n    adjusted = total * 2\n    return adjusted\n"


@pytest.mark.parametrize("command", ["check", "scan", "detect"])
def test_dryer_cli_reports_real_structural_twins(repo: Repo, command: str, capsys) -> None:
    repo.write("src/first.py", SHAPE)
    repo.write("src/second.py", SHAPE.replace("compute", "calculate").replace("values", "numbers"))
    repo.commit()
    args = [command, "--root", str(repo.root), "--detector", "dryer", "--judge", "none", "--format", "json"]
    if command in {"check", "detect"}:
        args += ["--base", "main"]
    assert main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == 7
    candidates = payload["candidates"] if command == "detect" else [f["candidate"] for f in payload["findings"]]
    twins = [c for c in candidates if {c["new"]["name"], c["existing"]["name"]} == {"compute", "calculate"}]
    assert all(c["similarity_reusable"] is False for c in candidates)
    assert len(twins) == 1
    assert twins[0]["similarity"] == 1.0 and twins[0]["comparer"].startswith("dryer:")


def test_configuration_selects_source_and_cli_can_override(repo: Repo, capsys) -> None:
    repo.write(".dry-lint.toml", 'comparer = {use = "dryer", threshold = 1.0}\n')
    args = ["scan", "--root", str(repo.root), "--judge", "none", "--format", "json"]
    assert main(args) == 0
    assert all(f["candidate"]["comparer"].startswith("dryer:") for f in json.loads(capsys.readouterr().out)["findings"])
    assert main([*args, "--detector", "tfidf"]) == 0
    assert {f["candidate"]["comparer"] for f in json.loads(capsys.readouterr().out)["findings"]} == {"tfidf:2"}


@pytest.mark.parametrize("overrides", [{"min_lines": 5}, {"min_nodes": 1000}])
def test_minimum_sizes_exclude_both_queries_and_targets(overrides: dict) -> None:
    functions = [function(path, SHAPE) for path in ("a.py", "b.py")]
    detector = build(functions, source_settings(**overrides))
    assert detector.scan() == []
    assert detector.neighbours(functions[0]) == []


def test_dryer_uses_shared_exclusions_patterns_and_cross_file_budget(repo: Repo) -> None:
    for i, path in enumerate(("src/first.py", "src/second.py", "tests/third.py")):
        repo.write(path, SHAPE.replace("compute", f"compute_{i}"))
    repo.commit()
    settings = Settings(comparer="dryer", neighbours=1, patterns=[Pattern(members="*::compute_*", reason="template")])
    detector = Detector.for_repository(repo.root, settings)
    assert not any(f.path.startswith("tests/") for f in detector.functions)
    proposed = detector.candidates(detector.functions)
    pairs = [c for c in proposed if not c.filtered]
    skipped = [c.filtered for c in proposed if c.filtered]
    assert not any(c.new.name.startswith("compute_") for c in pairs)
    assert any("declared pattern: template" in reason for reason in skipped)
    for f in detector.functions:
        near = detector.neighbours(f)
        assert len(near) <= 1 and all(other.path != f.path for other, _ in near)


def test_scores_and_ranking_match_upstream_for_decorated_async_methods() -> None:
    from dryer.extract import entries_in_source
    from dryer.scan import find_duplicates

    source = "class Service:\n    @decorator\n    async def compute(self, values):\n        total = sum(values)\n        adjusted = total * 2\n        return adjusted\n"
    functions, entries = [], []
    for i, path in enumerate(("a.py", "b.py")):
        source = source.replace("compute", "calculate") if i else source
        functions.extend(PythonExtractor().functions(path, source))
        found, warning = entries_in_source("python", source, path, path)
        assert warning is None
        entries.extend(found)
    [expected] = find_duplicates(entries, threshold=0.82)
    [actual] = build(functions, source_settings()).scan()
    assert actual.similarity == expected.score == 1
    assert actual.new.line == expected.left.start_line == 3


def test_external_query_and_threshold_match_upstream() -> None:
    from dryer.extract import entries_in_source
    from dryer.shape import jaccard

    first = function("a.py", SHAPE)
    second = function("b.py", SHAPE.replace("* 2", "+ 2"))
    detector = build([second], source_settings(threshold=0.01))
    left, _ = entries_in_source("python", first.code, first.path, first.path)
    right, _ = entries_in_source("python", second.code, second.path, second.path)
    score = jaccard(left[0].fingerprints, right[0].fingerprints)
    assert detector.neighbours(first) == [(second, score)]
    assert build([second], source_settings(threshold=1)).neighbours(first) == []


def test_size_bound_only_eliminates_impossible_matches() -> None:
    small = function("a.py", SHAPE)
    large = function(
        "b.py",
        SHAPE.replace(
            "    return adjusted",
            "    if adjusted:\n        while adjusted > 0:\n            adjusted -= 1\n    return adjusted",
        ),
    )
    assert build([small, large], source_settings(threshold=1)).scan() == []


def test_invalid_extraction_is_an_actionable_error() -> None:
    invalid = function("bad.py", "x = 1\n", name="broken")
    with pytest.raises(ValueError, match="Dryer could not extract bad.py::broken"):
        build([invalid], source_settings())


def test_nested_functions_remain_with_their_parent() -> None:
    code = "def outer(values):\n    def inner(value):\n        return value * 2\n    mapped = [inner(v) for v in values]\n    return mapped\n"
    functions = [function("a.py", code), function("b.py", code.replace("outer", "wrapper"))]
    [pair] = build(functions, source_settings()).scan()
    assert {pair.new.name, pair.existing.name} == {"outer", "wrapper"}


def test_shared_recall_rules_apply_to_dryer_before_ranking() -> None:
    from textwrap import indent

    local = "\n".join(f"class Resource{i}:\n{indent(SHAPE, '    ')}" for i in range(12))
    local += "\ndef declaration(\n    values: list[int],\n) -> int:\n    raise NotImplementedError\n"
    functions = PythonExtractor().functions("a.py", local) + PythonExtractor().functions("b.py", SHAPE)
    assert len(functions) == 13
    detector = build(functions, source_settings())
    assert [(other.path, score) for other, score in detector.neighbours(functions[0])] == [("b.py", 1.0)]
    pairs = detector.candidates([functions[0]])
    assert len(pairs) == 1 and pairs[0].new.name == pairs[0].existing.name == "compute"
    assert len(detector.scan()) == 1


def test_overload_signatures_do_not_inherit_the_implementation_fingerprint() -> None:

    source = "@overload\ndef compute(\n    values: list[int],\n) -> int: ...\n\n" + SHAPE
    functions = (
        [function("a.py", "def compute(\n    values: list[int],\n) -> int: ...")]
        + PythonExtractor().functions("a.py", source)
        + [function("b.py", SHAPE.replace("compute", "calculate"))]
    )
    detector = build(functions, source_settings())
    assert detector.neighbours(functions[0]) == []
    assert [(other.name, score) for other, score in detector.neighbours(functions[1])] == [("calculate", 1.0)]


def test_missing_optional_package_explains_installation(repo: Repo, monkeypatch, capsys) -> None:
    monkeypatch.setitem(sys.modules, "dryer.extract", None)
    assert main(["scan", "--root", str(repo.root), "--detector", "dryer"]) == 2
    assert "install 'dry-lint[dryer]'" in capsys.readouterr().err


@pytest.mark.parametrize(
    "setting,value",
    [
        ("threshold", 0),
        ("threshold", 1.1),
        ("min_lines", 0),
        ("min_nodes", 0),
    ],
)
def test_invalid_source_settings_are_rejected(setting: str, value: str | float) -> None:
    with pytest.raises(ValueError):
        DryerComparer(**{setting: value})


def test_similarity_is_available_below_size_gates_and_ignores_other_languages() -> None:
    left = function("a.py", SHAPE)
    right = function("b.py", SHAPE.replace("compute", "calculate"))
    foreign = right.model_copy(update={"path": "b.ts"})
    comparer = DryerComparer(min_lines=100)
    comparer.index([right, foreign])
    assert comparer.similarity(left, right) == 1
    assert comparer.similarity(left, foreign) == 0
    assert comparer.neighbours(left, 3, allowed=lambda _: True) == []


@pytest.mark.parametrize("threshold", [0.01, 0.5, 0.82, 1.0])
def test_indexed_neighbours_match_exhaustive_upstream_scores_and_tie_order(threshold: float) -> None:
    from dryer.extract import entries_in_source
    from dryer.shape import jaccard

    bodies = [
        SHAPE,
        SHAPE.replace("* 2", "+ 2"),
        SHAPE.replace("compute", "renamed"),
        SHAPE.replace("    return adjusted", "    if adjusted:\n        return adjusted + 1\n    return 0"),
        "def tiny():\n    return 1\n",
    ]
    functions = [function(f"{i}.py", code) for i, code in enumerate(bodies)]
    entries = [entries_in_source("python", f.code, f.path, f.path)[0][0] for f in functions]
    comparer = DryerComparer(threshold=threshold, min_lines=1, min_nodes=1)
    comparer.index(functions)
    for query, entry in zip(functions, entries, strict=True):
        expected = [
            (other, jaccard(entry.fingerprints, target.fingerprints))
            for other, target in zip(functions, entries, strict=True)
            if other.path != query.path and other.path != "1.py"
        ]
        expected = sorted((p for p in expected if p[1] >= threshold), key=lambda p: -p[1])[:3]
        assert comparer.neighbours(query, 3, allowed=lambda f: f.path != "1.py") == expected
    comparer.index([])
    assert comparer.neighbours(functions[0], 3, allowed=lambda _: True) == []
