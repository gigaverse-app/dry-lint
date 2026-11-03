"""Meaning and safety of the offline channel trial, independent of its retrieval results on any corpus."""

import json
import math
import runpy
import sys
from pathlib import Path

import pytest

from dry_lint.bench import GoldFunction, GoldPair
from dry_lint.comparers import TfidfComparer
from dry_lint.detector import Detector
from dry_lint.extractors import PythonExtractor
from dry_lint.models import Function, pair_key
from dry_lint.settings import Settings

from conftest import function

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
trial = runpy.run_path(str(SCRIPTS / "channel_trial.py"))
CslsComparer, Floored, LsiComparer = trial["CslsComparer"], trial["Floored"], trial["LsiComparer"]


def doc(path: str, *tokens: str, name: str = "run") -> Function:
    return Function(path=path, name=name, line=1, end_line=3, code=f"def {name}():\n    pass\n    pass", tokens=list(tokens))


def fillers(count: int = 30) -> list[Function]:
    """Unrelated documents, so a handful of shared tokens stay under the TF-IDF `max_df` cut."""
    return [doc(f"filler{i}.py", f"call:filler{i}", f"w:alone{i}") for i in range(count)]


def anywhere(_: Function) -> bool:
    return True


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    return runpy.run_path(str(SCRIPTS / "benchmark_channel_trial.py"))


@pytest.mark.parametrize("plural,singular", [
    ("users", "user"), ("settings", "setting"), ("entries", "entry"), ("classes", "class"), ("boxes", "box"),
    ("matches", "match"), ("dishes", "dish"), ("quizzes", "quizz"),
])
def test_regular_plurals_fold_to_their_singular(plural: str, singular: str) -> None:
    assert trial["singular"](plural) == singular


@pytest.mark.parametrize("word", ["status", "class", "analysis", "previous", "ids", "user", "bus", "is"])
def test_words_that_only_end_in_s_are_left_alone(word: str) -> None:
    assert trial["singular"](word) == word


def test_plural_folding_changes_identifier_words_but_never_code_identities() -> None:
    tokens = ["w:users", "fn:entries", "call:users", "attr:settings", "key:items", "ctl:loop"]
    assert trial["fold_plurals"](tokens) == ["w:user", "fn:entry", "call:users", "attr:settings", "key:items", "ctl:loop"]


def test_behaviour_channel_keeps_what_the_function_does_and_drops_its_words() -> None:
    tokens = ["fn:sync", "w:user", "call:save", "attr:name", "key:email", "ctl:try"]
    assert trial["behaviour_only"](tokens) == ["call:save", "attr:name", "key:email", "ctl:try"]


@pytest.mark.parametrize("comparer", [
    trial["experimental"](TfidfComparer(), "plural"), CslsComparer(TfidfComparer()), Floored(LsiComparer()),
])
def test_trial_comparers_never_claim_the_production_identity_or_verdict_reuse(comparer) -> None:
    assert comparer.name.startswith("trial-") and comparer.version == "1"
    assert comparer.similarity_reusable is False


def test_csls_prefers_a_distinctive_twin_over_an_equally_similar_hub() -> None:
    # The query is exactly as close to both. The hub's extra word is shared with a tight family; the twin's with loners.
    query = doc("q.py", "call:alpha", "call:beta")
    hub = doc("h.py", "call:alpha", "call:beta", "call:eta")
    twin = doc("t.py", "call:alpha", "call:beta", "call:tau")
    family = [doc(f"g{i}.py", "call:eta", f"call:x{i}") for i in range(4)]
    loners = [doc(f"u{i}.py", "call:tau", f"call:n{i}a", f"call:n{i}b", f"call:n{i}c") for i in range(4)]
    corpus = [query, hub, twin, *family, *loners, *fillers()]
    plain, corrected = TfidfComparer(0.0, 0.0), CslsComparer(TfidfComparer(0.0, 0.0), pool=4)
    plain.index(corpus)
    corrected.index(corpus)
    both = lambda other: other.path in {"h.py", "t.py"}  # noqa: E731
    assert plain.similarity(query, hub) == pytest.approx(plain.similarity(query, twin))
    assert corrected.radius(hub) > corrected.radius(twin)
    assert [f.path for f, _ in plain.neighbours(query, 2, both)] == ["h.py", "t.py"]
    ranked = corrected.neighbours(query, 2, both)
    assert [f.path for f, _ in ranked] == ["t.py", "h.py"]
    # Only the order changes: the reported similarity stays the raw cosine the floors apply to.
    assert ranked[0][1] == pytest.approx(plain.similarity(query, twin))
    assert corrected.similarity(query, hub) == pytest.approx(plain.similarity(query, hub))


def test_csls_radius_of_an_unindexed_or_isolated_function_is_defined() -> None:
    corrected = CslsComparer(TfidfComparer())
    corrected.index([doc("a.py", "call:only"), *fillers()])
    assert corrected.radius(doc("new.py", "call:unknown")) == 0.0
    assert corrected.radius(doc("a.py", "call:only")) == 0.0  # its only match is itself


def test_floored_channel_drops_neighbours_below_its_floor_only() -> None:
    inner = TfidfComparer(0.0, 0.0)
    a, b, c = doc("a.py", "call:x", "call:y"), doc("b.py", "call:x", "call:y"), doc("c.py", "call:x", "call:z")
    floored = Floored(inner, floor=0.9)
    floored.index([a, b, c, *fillers()])
    assert [f.path for f, _ in floored.neighbours(a, 3, anywhere)] == ["b.py"]
    assert floored.similarity(a, c) == pytest.approx(inner.similarity(a, c))
    assert floored.name == inner.name and floored.version == inner.version


def test_lsi_connects_functions_whose_words_keep_the_same_company() -> None:
    # fetch and load never share a function, but both keep company with cache; mail belongs to another topic.
    caching = [doc(f"a{i}.py", word, "call:cache") for i, word in enumerate(["call:fetch", "call:load"] * 3)]
    mailing = [doc(f"b{i}.py", word, "call:outbox") for i, word in enumerate(["call:mail", "call:smtp"] * 3)]
    query, related, unrelated = doc("q.py", "call:fetch"), doc("r.py", "call:load"), doc("u.py", "call:mail")
    corpus = [*caching, *mailing, query, related, unrelated, *fillers()]
    lsi, tfidf = LsiComparer(rank=2), TfidfComparer()
    lsi.index(corpus)
    tfidf.index(corpus)
    assert tfidf.similarity(query, related) == 0.0
    assert lsi.similarity(query, related) > 0.99
    assert lsi.similarity(query, unrelated) == pytest.approx(0.0, abs=0.05)
    assert lsi.similarity(query, related) == pytest.approx(lsi.similarity(related, query))


def test_lsi_neighbours_respect_k_and_allowed_and_exclude_the_function_itself() -> None:
    corpus = [doc("a.py", "call:x", "call:y"), doc("b.py", "call:x", "call:y"), doc("c.py", "call:x", "call:y"), *fillers()]
    lsi = LsiComparer(rank=8)
    lsi.index(corpus)
    found = lsi.neighbours(corpus[0], 1, lambda o: o.path != "b.py")
    assert [f.path for f, _ in found] == ["c.py"]
    assert all(f.qualname != corpus[0].qualname for f, _ in lsi.neighbours(corpus[0], 5, anywhere))


def test_lsi_is_deterministic_for_a_seed() -> None:
    corpus = [doc("a.py", "call:x", "call:y"), doc("b.py", "call:x", "call:z"), *fillers()]
    first, second = LsiComparer(rank=4, seed=3), LsiComparer(rank=4, seed=3)
    first.index(corpus)
    second.index(corpus)
    assert first.similarity(corpus[0], corpus[1]) == second.similarity(corpus[0], corpus[1])


def test_lsi_handles_an_empty_corpus_and_functions_without_known_tokens() -> None:
    lsi = LsiComparer()
    lsi.index([])
    assert lsi.neighbours(doc("a.py", "call:x"), 3, anywhere) == []
    lsi.index(fillers())
    assert lsi.similarity(doc("a.py", "call:never"), fillers()[0]) == 0.0


def detector_for(sources: dict[str, str]) -> Detector:
    functions = [function(path, source) for path, source in sources.items()]
    return Detector(functions, Settings(), TfidfComparer(), [PythonExtractor()])


def test_mutual_nearest_reproduces_the_detector_scan(repo) -> None:
    detector = Detector.for_repository(repo.root, Settings())
    pairs = trial["mutual_nearest"](detector, trial["nearest"](detector))
    assert pairs == {frozenset((c.new.qualname, c.existing.qualname)) for c in detector.scan()}
    assert pairs  # the caption twin and the text helper


def test_mutual_nearest_applies_the_production_rules() -> None:
    detector = detector_for({"a.py": "def helper(text):\n    return text.strip().lower()",
                             "b.py": "def caller(text):\n    return helper(text.strip().lower())"})
    assert trial["mutual_nearest"](detector, trial["nearest"](detector)) == set()


def test_calibrated_floor_keeps_the_requested_share_of_functions() -> None:
    top = {"a": [("x", 0.9)], "b": [("x", 0.7)], "c": [("x", 0.5)], "d": [("x", 0.3)], "e": []}
    floor = trial["calibrated_floor"](top, 0.4)
    assert floor == 0.7
    assert trial["share_with_neighbour"]({k: [p for p in v if p[1] >= floor] for k, v in top.items()}) == 0.4
    assert trial["calibrated_floor"](top, 0.0) == math.inf
    assert trial["calibrated_floor"](top, 1.0) == 0.3  # cannot keep more than have a neighbour at all
    assert trial["share_with_neighbour"]({}) == 0.0


def gold_line(new: str, existing: str, label: str) -> str:
    pair = GoldPair(new=GoldFunction(id=new, code=""), existing=GoldFunction(id=existing, code=""), label=label)
    return pair.model_dump_json() + "\n"


def test_trial_cli_scores_every_variant_on_a_real_repository(repo, tmp_path, monkeypatch, harness) -> None:
    gold = tmp_path / "gold.jsonl"
    gold.write_text(gold_line("src/widgets/caption.py::preview_caption_text", "src/text.py::shorten_text", "duplicate")
                    + gold_line("src/widgets/caption.py::register_widget", "src/text.py::shorten_text", "borderline"))
    out = tmp_path / "trial"
    monkeypatch.setattr(sys, "argv", ["trial", "--root", str(repo.root), "--out", str(out), "--gold", str(gold)])
    runpy.run_path(str(SCRIPTS / "benchmark_channel_trial.py"), run_name="__main__")
    results = json.loads((out / "results.json").read_text())
    assert results["head"] == repo.git("rev-parse", "HEAD").strip() and not results["dirty"]
    assert set(results["variants"]) == set(harness["VARIANTS"]) and results["unavailable"] == {}
    assert results["channels"]["tfidf"]["comparer"] == "tfidf:2"
    assert all(c["comparer"].startswith(("trial-", "dryer:")) for n, c in results["channels"].items() if n != "tfidf")
    for name, channel in results["channels"].items():
        if channel["floor"] is not None:  # calibrated channels keep a neighbour as often as production TF-IDF
            assert channel["share_with_neighbour"] == pytest.approx(results["channels"]["tfidf"]["share_with_neighbour"], abs=0.02)
        pairs = json.loads((out / f"{name}-scan.json").read_text())
        assert all(pair["comparer"] == channel["comparer"] and not pair["similarity_reusable"] or name == "tfidf"
                   for pair in pairs)
    baseline = results["variants"]["baseline"]
    assert baseline["gold"] == [{"group": "gold", "key": baseline["gold"][0]["key"], "positive": True,
                                 "check": True, "scan": True}]  # borderline pairs are not scored
    for variant in results["variants"].values():
        # A reserved slot only adds candidates: every variant built on production TF-IDF keeps its pairs.
        if variant["channels"][0] == "tfidf":
            assert set(baseline["scan_keys"]) <= set(variant["scan_keys"])
            assert variant["extra_candidates_per_function"] >= 0
    sample = json.loads((out / "sample.json").read_text())
    assert baseline["gold"][0]["key"] not in {row["key"] for row in sample}  # never relabel a labelled pair
    assert all(row["new"]["code"] and row["existing"]["code"] for row in sample)


def test_missing_optional_channels_are_reported_not_substituted(repo, tmp_path, harness) -> None:
    def unavailable():
        raise ValueError("Dryer requires the optional dependency")

    channels = {**harness["CHANNELS"], "dryer": (None, unavailable, 1)}
    results = harness["run"](repo.root, tmp_path / "trial", [], channels=channels)
    assert results["unavailable"] == {"dryer": "Dryer requires the optional dependency"}
    assert results["variants"]["dryer"] == {"unavailable": ["dryer"]}
    assert "channels" in results["variants"]["baseline"]


def test_gold_pairs_must_exist_in_the_corpus(repo, tmp_path, harness) -> None:
    gold = tmp_path / "gold.jsonl"
    gold.write_text(gold_line("src/text.py::shorten_text", "missing.py::gone", "separate"))
    with pytest.raises(ValueError, match="missing from corpus"):
        harness["run"](repo.root, tmp_path / "trial", [gold])


class Restless(TfidfComparer):
    """A comparer that answers one pass over the corpus and then goes quiet, so a fresh scan finds nothing."""

    def neighbours(self, function, k, allowed):
        self.calls = getattr(self, "calls", 0) + 1
        return super().neighbours(function, k, allowed) if self.calls <= len(self.functions) else []


def test_trial_refuses_to_run_when_its_scan_differs_from_the_detector(repo, tmp_path, harness) -> None:
    channels = {"tfidf": (None, Restless, 3)}
    with pytest.raises(AssertionError, match="reproduce Detector.scan"):
        harness["run"](repo.root, tmp_path / "trial", [], channels=channels)


def test_sample_draw_is_reproducible_skips_labelled_pairs_and_never_repeats(harness) -> None:
    pairs = [frozenset((f"a{i}", f"b{i}")) for i in range(30)]
    scans = {"tfidf": set(pairs[:12]), "plural": set(pairs[5:20]), "lsi": set(pairs[18:30])}
    labelled = {pair_key(*pairs[0]), pair_key(*pairs[12])}
    first = harness["draw"](scans, labelled, harness["random"].Random(1))
    second = harness["draw"](scans, labelled, harness["random"].Random(1))
    assert first == second
    drawn = [pair for _, pair in first]
    assert len(drawn) == len(set(drawn)) == 8 + 4 + 4
    assert not {pair_key(*p) for p in drawn} & labelled
    assert all(pair not in scans["tfidf"] for stratum, pair in first if stratum != "tfidf")
