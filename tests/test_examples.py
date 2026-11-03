"""The public example pairs (examples/gold.jsonl): usable by `dry-lint bench`, labelled by majority, safe to publish."""

import json
import re
from collections import Counter
from pathlib import Path

from dry_lint.bench import load_gold

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "gold.jsonl"
ROWS = [json.loads(line) for line in EXAMPLES.read_text().splitlines()]


def test_every_example_is_a_gold_pair_bench_can_read() -> None:
    pairs = load_gold(EXAMPLES)
    assert len(pairs) == len(ROWS) and all(p.label in ("duplicate", "separate") for p in pairs)
    assert len({(p.new.id, p.existing.id) for p in pairs}) == len(pairs)


def test_each_label_is_the_majority_of_three_labellers() -> None:
    for row in ROWS:
        votes = Counter(row["labellers"].values())
        assert sum(votes.values()) == 3
        assert row["label"] == ("duplicate" if votes["duplicate"] >= 2 else "separate"), row["new"]["id"]


def test_both_languages_have_duplicates_and_look_alikes_that_are_not() -> None:
    assert set(Counter((r["language"], r["label"]) for r in ROWS)) == {
        ("python", "duplicate"), ("python", "separate"), ("typescript", "duplicate"), ("typescript", "separate")}
    assert all(set(r["scores"]) == {"jev", "opus", "sonnet"} for r in ROWS)


def test_no_example_carries_an_address_or_a_credential() -> None:
    risky = re.compile(r"https?://|www\.|@[a-z0-9-]+\.[a-z]|secret|password|token|api[_-]?key|bearer|BEGIN [A-Z]+ KEY",
                       re.IGNORECASE)
    assert [r["new"]["id"] for r in ROWS if risky.search(r["new"]["code"] + r["existing"]["code"])] == []
