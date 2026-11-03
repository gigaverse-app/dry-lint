"""The optional source runs real upstream extraction and scoring through dry-lint."""

import json
import sys

import pytest

from dry_lint.cli import main
from dry_lint.detector import Detector
from dry_lint.settings import Pattern, Settings
from dry_lint.sources import make_source

from conftest import Repo, function

dryer = pytest.importorskip("dryer")

SHAPE = "def compute(values):\n    total = sum(values)\n    adjusted = total * 2\n    return adjusted\n"


@pytest.mark.parametrize("command", ["check", "scan"])
def test_dryer_cli_reports_real_structural_twins(repo: Repo, command: str, capsys) -> None:
    repo.write("src/first.py", SHAPE)
    repo.write("src/second.py", SHAPE.replace("compute", "calculate").replace("values", "numbers"))
    repo.commit()
    args = [command, "--root", str(repo.root), "--detector", "dryer", "--judge", "none", "--format", "json"]
    if command == "check":
        args += ["--base", "main"]
    assert main(args) == 0
    findings = json.loads(capsys.readouterr().out)
    twins = [
        f["candidate"]
        for f in findings
        if {f["candidate"]["new"]["name"], f["candidate"]["existing"]["name"]} == {"compute", "calculate"}
    ]
    assert len(twins) == 1
    assert twins[0]["similarity"] == 1.0 and twins[0]["detector"] == "dryer"


def test_configuration_selects_source_and_cli_can_override(repo: Repo, capsys) -> None:
    repo.write(".dry-lint.toml", 'detector = "dryer"\ndryer_threshold = 1.0\n')
    args = ["scan", "--root", str(repo.root), "--judge", "none", "--format", "json"]
    assert main(args) == 0
    assert all(f["candidate"]["detector"] == "dryer" for f in json.loads(capsys.readouterr().out))
    assert main([*args, "--detector", "tfidf"]) == 0
    assert {f["candidate"]["detector"] for f in json.loads(capsys.readouterr().out)} == {"tfidf"}


@pytest.mark.parametrize("overrides", [{"dryer_min_lines": 5}, {"dryer_min_nodes": 1000}])
def test_minimum_sizes_exclude_both_queries_and_targets(overrides: dict) -> None:
    functions = [function(path, SHAPE) for path in ("a.py", "b.py")]
    detector = Detector(functions, Settings(detector="dryer", **overrides))
    assert detector.scan() == []
    assert detector.neighbours(functions[0]) == []


def test_dryer_uses_shared_exclusions_patterns_and_cross_file_budget(repo: Repo) -> None:
    for i, path in enumerate(("src/first.py", "src/second.py", "tests/third.py")):
        repo.write(path, SHAPE.replace("compute", f"compute_{i}"))
    repo.commit()
    settings = Settings(detector="dryer", neighbours=1, patterns=[Pattern(members="*::compute_*", reason="template")])
    detector = Detector.for_repository(repo.root, settings)
    assert not any(f.path.startswith("tests/") for f in detector.functions)
    pairs, skipped = detector.candidates(detector.functions)
    assert not any(c.new.name.startswith("compute_") for c in pairs)
    assert any("declared pattern: template" in reason for reason in skipped)
    for f in detector.functions:
        near = detector.neighbours(f)
        assert len(near) <= 1 and all(other.path != f.path for other, _ in near)


def test_scores_and_ranking_match_upstream_for_decorated_async_methods() -> None:
    from dryer.extract import entries_in_source
    from dryer.scan import find_duplicates

    from dry_lint.functions import functions_in

    source = "class Service:\n    @decorator\n    async def compute(self, values):\n        total = sum(values)\n        adjusted = total * 2\n        return adjusted\n"
    functions, entries = [], []
    for i, path in enumerate(("a.py", "b.py")):
        source = source.replace("compute", "calculate") if i else source
        functions.extend(functions_in(source, path))
        found, warning = entries_in_source("python", source, path, path)
        assert warning is None
        entries.extend(found)
    [expected] = find_duplicates(entries, threshold=0.82)
    [actual] = Detector(functions, Settings(detector="dryer")).scan()
    assert actual.similarity == expected.score == 1
    assert actual.new.line == expected.left.start_line == 3


def test_external_query_and_threshold_match_upstream() -> None:
    from dryer.extract import entries_in_source
    from dryer.shape import jaccard

    first = function("a.py", SHAPE)
    second = function("b.py", SHAPE.replace("* 2", "+ 2"))
    detector = Detector([second], Settings(detector="dryer", dryer_threshold=0.01))
    left, _ = entries_in_source("python", first.code, first.path, first.path)
    right, _ = entries_in_source("python", second.code, second.path, second.path)
    score = jaccard(left[0].fingerprints, right[0].fingerprints)
    assert detector.neighbours(first) == [(second, score)]
    assert Detector([second], Settings(detector="dryer", dryer_threshold=1)).neighbours(first) == []


def test_size_bound_only_eliminates_impossible_matches() -> None:
    small = function("a.py", SHAPE)
    large = function(
        "b.py",
        SHAPE.replace(
            "    return adjusted",
            "    if adjusted:\n        while adjusted > 0:\n            adjusted -= 1\n    return adjusted",
        ),
    )
    assert Detector([small, large], Settings(detector="dryer", dryer_threshold=1)).scan() == []


def test_invalid_extraction_is_an_actionable_error() -> None:
    invalid = function("bad.py", "x = 1\n", name="broken")
    with pytest.raises(ValueError, match="Dryer could not extract bad.py::broken"):
        make_source([invalid], Settings(detector="dryer"))


def test_nested_functions_remain_with_their_parent() -> None:
    code = "def outer(values):\n    def inner(value):\n        return value * 2\n    mapped = [inner(v) for v in values]\n    return mapped\n"
    functions = [function("a.py", code), function("b.py", code.replace("outer", "wrapper"))]
    [pair] = Detector(functions, Settings(detector="dryer")).scan()
    assert {pair.new.name, pair.existing.name} == {"outer", "wrapper"}


def test_overload_signatures_do_not_inherit_the_implementation_fingerprint() -> None:
    from dry_lint.functions import functions_in

    source = "@overload\ndef compute(\n    values: list[int],\n) -> int: ...\n\n" + SHAPE
    functions = functions_in(source, "a.py") + [function("b.py", SHAPE.replace("compute", "calculate"))]
    detector = Detector(functions, Settings(detector="dryer"))
    assert detector.neighbours(functions[0]) == []
    assert [(other.name, score) for other, score in detector.neighbours(functions[1])] == [("calculate", 1.0)]


def test_missing_optional_package_explains_installation(repo: Repo, monkeypatch, capsys) -> None:
    monkeypatch.setitem(sys.modules, "dry_lint.sources.dryer", None)
    assert main(["scan", "--root", str(repo.root), "--detector", "dryer"]) == 2
    assert "install 'dry-lint[dryer]'" in capsys.readouterr().err


@pytest.mark.parametrize(
    "setting,value",
    [
        ("dryer_threshold", 0),
        ("dryer_threshold", 1.1),
        ("dryer_min_lines", 0),
        ("dryer_min_nodes", 0),
        ("detector", "unknown"),
    ],
)
def test_invalid_source_settings_are_rejected(setting: str, value: str | float) -> None:
    with pytest.raises(ValueError):
        Settings.model_validate({setting: value})
