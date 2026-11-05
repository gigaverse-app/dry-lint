"""Public gold panels load and retrieve; calibrated examples retain their majority-label contract."""

import hashlib
import re
import sys
import tomllib
from collections import Counter
from pathlib import Path

import pytest

from dry_lint.bench import as_function, bench_comparer, load_gold
from dry_lint.detector import Detector
from dry_lint.plugins import load
from dry_lint.settings import Settings

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "gold.toml"
ROWS = tomllib.loads(EXAMPLES.read_text())["pair"]
CLEANUP = EXAMPLES.with_name("pytest-selective-gold.toml")
DUE = EXAMPLES.with_name("due-consolidation-gold.toml")


@pytest.mark.parametrize(
    "path", [EXAMPLES, CLEANUP, DUE], ids=["calibrated-examples", "cleanup-regressions", "due-consolidations"]
)
def test_every_example_is_a_gold_pair_bench_can_read(path: Path) -> None:
    pairs = load_gold(path)
    assert len(pairs) == len(tomllib.loads(path.read_text())["pair"])
    assert all(p.label in ("duplicate", "separate") for p in pairs)
    assert len({(p.new.id, p.existing.id) for p in pairs}) == len(pairs)


def test_due_consolidations_preserve_pinned_source_and_real_after_controls() -> None:
    rows = tomllib.loads(DUE.read_text())["pair"]
    assert Counter((r["phase"], r["label"]) for r in rows) == {
        ("before", "duplicate"): 7,
        ("after", "separate"): 3,
    }
    before = {r["case"].removesuffix("-before"): r for r in rows if r["phase"] == "before"}
    for row in rows:
        assert re.fullmatch(r"[a-f0-9]{40}", row["revision"])
        for side in ("new", "existing"):
            source = row[side]
            assert hashlib.sha256(source["code"].encode()).hexdigest() == source["sha256"]
            assert source["source"] == (
                f"https://github.com/gigaverse-app/due/blob/{row['revision']}/{source['source_id'].split('::')[0]}"
            )
            if row["phase"] == "after":
                original = before[row["case"].removesuffix("-after")]
                assert source["source_id"] == original[side]["source_id"]
        if row["phase"] == "after":
            original = before[row["case"].removesuffix("-after")]
            assert any(row[side]["code"] != original[side]["code"] for side in ("new", "existing"))


@pytest.mark.skipif(sys.version_info < (3, 12), reason="Pinned Due source uses Python 3.12 generic syntax")
def test_due_gold_extracts_implementations_instead_of_unparsed_fallbacks() -> None:
    extractor = load("extractors", Settings().extractors[0])
    for pair in load_gold(DUE):
        for side in (pair.new, pair.existing):
            function = as_function(side, extractor)
            assert function.qualname == side.id
            assert function.tokens and function.analysis is not None


def test_cleanup_gold_extracts_real_functions_and_keeps_known_positive_retrieval() -> None:
    """The panel must exercise extraction/retrieval, never silently fall back to unparsed text."""
    pairs = load_gold(CLEANUP)
    extractor = load("extractors", Settings().extractors[0])
    functions = {}
    for pair in pairs:
        for side in (pair.new, pair.existing):
            function = as_function(side, extractor)
            assert function.qualname == side.id
            assert function.tokens and function.analysis is not None
            functions[side.id] = function
    before = [function for identity, function in functions.items() if identity.startswith("before/")]
    settings = Settings()
    detector = Detector(before, settings, load("comparers", settings.comparer), [extractor])
    result = bench_comparer(pairs, detector)
    assert result.missing == 0 and result.duplicates == 8
    # The reduced frozen corpus retrieves seven positives with default top-three
    # neighbours. The snapshot pair is a documented miss, not a reason to relabel it.
    assert result.recall >= 7 / 8


def test_each_label_is_the_majority_of_three_labellers() -> None:
    for row in ROWS:
        votes = Counter(row["labellers"].values())
        assert sum(votes.values()) == 3
        assert row["label"] == ("duplicate" if votes["duplicate"] >= 2 else "separate"), row["new"]["id"]


def test_both_languages_have_duplicates_and_look_alikes_that_are_not() -> None:
    assert set(Counter((r["language"], r["label"]) for r in ROWS)) == {
        ("python", "duplicate"),
        ("python", "separate"),
        ("typescript", "duplicate"),
        ("typescript", "separate"),
    }
    assert all("jev" in r["scores"] and set(r["scores"]) <= {"jev", "opus", "sonnet"} for r in ROWS)


def test_no_example_carries_an_address_or_a_credential() -> None:
    risky = re.compile(
        r"https?://|www\.|@[a-z0-9-]+\.[a-z]|secret|password|token|api[_-]?key|bearer|BEGIN [A-Z]+ KEY", re.IGNORECASE
    )
    assert [r["new"]["id"] for r in ROWS if risky.search(r["new"]["code"] + r["existing"]["code"])] == []
