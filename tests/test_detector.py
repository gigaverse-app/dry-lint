import pytest

from dry_lint.detector import Detector, changed_lines, touched, why_skipped
from dry_lint.settings import Pattern, Settings

from conftest import Repo, function


def changed_functions(repo: Repo, detector: Detector, **where) -> list[str]:
    return [f.qualname for f in touched(detector.functions, changed_lines(repo.root, **where))]


def test_changed_lines_cover_the_lines_a_branch_added(repo: Repo) -> None:
    lines = changed_lines(repo.root, base="main")
    assert set(lines) == {"src/widgets/caption.py"}
    assert lines["src/widgets/caption.py"] == set(range(1, 12))


def test_changed_lines_of_staged_changes_ignore_unstaged_ones_and_deleted_files(repo: Repo) -> None:
    repo.write("src/text.py", (repo.root / "src/text.py").read_text().replace("limit - 1", "limit - 2"))
    repo.git("add", "src/text.py")
    repo.git("rm", "-q", "src/widgets/caption.py")
    repo.write("src/unstaged.py", "def later(x):\n    return x\n")
    assert changed_lines(repo.root, staged=True) == {"src/text.py": {5}}


def test_only_functions_overlapping_changed_lines_count_as_changed(repo: Repo) -> None:
    detector = Detector.for_repository(repo.root, Settings())
    assert changed_functions(repo, detector, base="main") == [
        "src/widgets/caption.py::preview_caption_text", "src/widgets/caption.py::register_widget"]


def test_a_reimplementation_of_an_existing_helper_becomes_a_candidate(repo: Repo) -> None:
    detector = Detector.for_repository(repo.root, Settings())
    changed = touched(detector.functions, changed_lines(repo.root, base="main"))
    candidates, skipped = detector.candidates(changed)
    pairs = {(c.new.qualname, c.existing.qualname) for c in candidates}
    assert ("src/widgets/caption.py::preview_caption_text", "src/text.py::shorten_text") in pairs
    assert not any(new.endswith("register_widget") for new, _ in pairs)
    assert skipped == []


def test_neighbours_come_from_other_files_and_respect_the_floor(repo: Repo) -> None:
    detector = Detector.for_repository(repo.root, Settings())
    for f in detector.functions:
        floor = detector.floor(f)
        for other, similarity in detector.neighbours(f):
            assert other.path != f.path and similarity >= floor
    strict = Detector.for_repository(repo.root, Settings(min_similarity=1.01, min_similarity_small=1.01))
    assert all(strict.neighbours(f) == [] for f in strict.functions)


def test_small_functions_use_the_small_function_floor(repo: Repo) -> None:
    detector = Detector.for_repository(repo.root, Settings(min_similarity=0.9, min_similarity_small=0.2))
    small = next(f for f in detector.functions if f.name == "sync_invoice")
    large = function("a.py", "def big(x):\n" + "    x += 1\n" * 8 + "    return x\n")
    assert detector.floor(small) == 0.2 and detector.floor(large) == 0.9


def test_a_pair_is_proposed_once_even_when_both_sides_changed(repo: Repo) -> None:
    detector = Detector.for_repository(repo.root, Settings())
    both = [f for f in detector.functions if f.name in {"shorten_text", "preview_caption_text"}]
    candidates, _ = detector.candidates(both)
    keys = [frozenset((c.new.qualname, c.existing.qualname)) for c in candidates]
    assert len(keys) == len(set(keys))


def test_scan_reports_mutual_nearest_neighbours_closest_first(repo: Repo) -> None:
    pairs = Detector.for_repository(repo.root, Settings()).scan()
    assert {(c.new.name, c.existing.name) for c in pairs} >= {("preview_caption_text", "shorten_text")} or \
        {(c.existing.name, c.new.name) for c in pairs} >= {("preview_caption_text", "shorten_text")}
    assert [c.similarity for c in pairs] == sorted((c.similarity for c in pairs), reverse=True)


A = function("a.py", "def load_user(store, key):\n    return store.read(key)\n")
B = function("b.py", "def load_account(store, key):\n    return store.read(key)\n")


@pytest.mark.parametrize("a, b, settings, reason", [
    (function("a.py", "def __init__(self, x):\n    self.x = x"), function("b.py", "def __init__(self, y):\n    self.y = y"),
     Settings(), "constructor or dunder pattern"),
    (A, function("b.py", "def load_account(store, key):\n    return load_user(store, key)\n"), Settings(), "one calls the other"),
    (A, B, Settings(patterns=[Pattern(members="*::load_*", reason="one loader per resource")]),
     "declared pattern: one loader per resource"),
    (A, function("b.py", "def load_account(store, key):\n    # dry-lint: distinct-from a.py::load_user\n    return store.read(key)\n"),
     Settings(), "inline distinct-from"),
    (A, B, Settings(), None),
])  # fmt: skip
def test_why_skipped_names_the_rule_that_makes_look_alikes_not_duplicates(a, b, settings, reason) -> None:
    assert why_skipped(a, b, settings) == reason
    assert why_skipped(b, a, settings) == reason


def test_skipped_pairs_are_listed_with_their_reason(repo: Repo) -> None:
    repo.write("src/widgets/caption.py", (repo.root / "src/widgets/caption.py").read_text().replace(
        "    if len(caption_text)", "    # dry-lint: distinct-from src/text.py::shorten_text\n    if len(caption_text)"))
    repo.commit("suppress")
    detector = Detector.for_repository(repo.root, Settings())
    candidates, skipped = detector.candidates(touched(detector.functions, changed_lines(repo.root, base="main")))
    assert not any(c.existing.name == "shorten_text" for c in candidates)
    assert skipped == ["src/widgets/caption.py::preview_caption_text ~ src/text.py::shorten_text: inline distinct-from"]


def test_each_function_gets_at_most_the_configured_number_of_neighbours(repo: Repo) -> None:
    detector = Detector.for_repository(repo.root, Settings(neighbours=1, min_similarity=0.0, min_similarity_small=0.0))
    assert all(len(detector.neighbours(f)) <= 1 for f in detector.functions)
    assert any(len(detector.neighbours(f)) == 1 for f in detector.functions)
