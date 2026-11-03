from pathlib import Path

import pytest

from dry_lint.detector import Candidate
from dry_lint.store import Verdict, VerdictStore, key

from conftest import function

NEW = function("new.py", "def clip(text, n):\n    if len(text) <= n:\n        return text\n    return text[: n - 1] + '…'\n")
OLD = function("old.py", "def shorten(text, limit):\n    if len(text) <= limit:\n        return text\n    return text[: limit - 1] + '…'\n")


def verdict(label: str, score: float = 0.9) -> Verdict:
    return Verdict(label=label, score=score, owner="existing", judge="test")


def candidate(new=NEW, old=OLD, similarity: float = 0.7) -> Candidate:
    return Candidate(new=new, existing=old, similarity=similarity)


def edited(f, before: str, after: str):
    return f.model_copy(update={"code": f.code.replace(before, after)})


@pytest.fixture
def store(tmp_path: Path) -> VerdictStore:
    return VerdictStore(tmp_path / "cache" / "verdicts.jsonl")


@pytest.mark.parametrize("label", ["duplicate", "drifted", "separate"])
def test_a_verdict_is_reused_while_neither_function_changes_logic(store: VerdictStore, label: str) -> None:
    store.remember(candidate(), verdict(label))
    cosmetic = edited(NEW, "return text\n", "return text  # unchanged\n")
    assert store.lookup(candidate(new=cosmetic, similarity=0.95), reopen_margin=0.05) == verdict(label)


@pytest.mark.parametrize("label", ["duplicate", "drifted"])
def test_a_duplicate_verdict_reopens_on_any_logic_change(store: VerdictStore, label: str) -> None:
    store.remember(candidate(), verdict(label))
    changed = edited(NEW, "n - 1", "n - 2")
    assert store.lookup(candidate(new=changed, similarity=0.5), reopen_margin=0.05) is None


def test_a_separate_verdict_survives_logic_changes_that_do_not_bring_the_pair_closer(store: VerdictStore) -> None:
    store.remember(candidate(similarity=0.7), verdict("separate", 0.2))
    changed = edited(OLD, "limit - 1", "limit - 2")
    assert store.lookup(candidate(old=changed, similarity=0.74), reopen_margin=0.05) == verdict("separate", 0.2)
    assert store.lookup(candidate(old=changed, similarity=0.76), reopen_margin=0.05) is None


def test_the_store_is_keyed_on_the_unordered_pair(store: VerdictStore) -> None:
    store.remember(candidate(), verdict("duplicate"))
    swapped = Candidate(new=OLD, existing=NEW, similarity=0.7)
    assert store.lookup(swapped, reopen_margin=0.05) == verdict("duplicate")
    assert key("b", "a") == key("a", "b") == ("a", "b")


def test_unknown_pairs_have_no_verdict(store: VerdictStore) -> None:
    assert store.lookup(candidate(), reopen_margin=0.05) is None


def test_saved_verdicts_load_back_and_export(store: VerdictStore) -> None:
    store.remember(candidate(), verdict("drifted"))
    store.save()
    loaded = VerdictStore(store.path)
    assert loaded.lookup(candidate(), reopen_margin=0.05) == verdict("drifted")
    [record] = loaded.export()
    assert (record["a"], record["b"]) == ("new.py::clip", "old.py::shorten")
    assert record["similarity_when_judged"] == 0.7 and record["verdict"]["label"] == "drifted"


def test_an_empty_store_saves_an_empty_file_and_ignores_blank_lines(store: VerdictStore) -> None:
    store.save()
    assert store.path.read_text() == ""
    store.path.write_text("\n\n")
    assert VerdictStore(store.path).records == {}


@pytest.mark.parametrize("old_source,new_source", [("tfidf", "dryer"), ("dryer", "tfidf"), ("dryer", "dryer")])
def test_structural_or_changed_metric_scores_cannot_reuse_a_changed_verdict(store, old_source, new_source) -> None:
    before = candidate().model_copy(update={"detector": old_source})
    store.remember(before, verdict("separate"))
    store.save()
    store = VerdictStore(store.path)
    unchanged = before.model_copy(update={"detector": new_source})
    assert store.lookup(unchanged, 0.05) == verdict("separate")
    changed = unchanged.model_copy(update={"new": edited(NEW, "n - 1", "n - 2"), "similarity": 0.1})
    assert store.lookup(changed, 0.05) is None


def test_legacy_records_default_to_tfidf(store) -> None:
    import json

    store.remember(candidate(), verdict("separate"))
    [record] = store.export()
    del record["detector"]
    store.path.parent.mkdir(parents=True)
    store.path.write_text(json.dumps(record))
    loaded = VerdictStore(store.path)
    assert loaded.lookup(candidate(), 0.05) == verdict("separate")
