import pytest

from dry_lint.comparers import TfidfComparer

from conftest import function

SHORTEN = function("a.py", "def shorten(text, limit):\n    if len(text) <= limit:\n        return text\n    return text[:limit]\n")
CLIP = function("b.py", "def clip(text, size):\n    if len(text) <= size:\n        return text\n    return text[:size]\n")
SAME_FILE = function("a.py", "def trim(text, limit):\n    if len(text) <= limit:\n        return text\n    return text[:limit]\n")
OTHER = [function(f"o{i}.py", f"def job_{word}(queue):\n    queue.push_{word}()\n    return queue.flush_{word}()\n")
         for i, word in enumerate(["alpha", "beta", "gamma", "delta", "omega", "sigma", "kappa"])]


@pytest.fixture
def comparer() -> TfidfComparer:
    comparer = TfidfComparer(min_similarity=0.2, min_similarity_small=0.2)
    comparer.index([SHORTEN, CLIP, SAME_FILE, *OTHER])
    return comparer


def test_neighbours_are_ranked_and_honour_the_allowed_filter(comparer: TfidfComparer) -> None:
    near = comparer.neighbours(SHORTEN, 3, allowed=lambda f: True)
    assert [f.qualname for f, _ in near][:2] == ["a.py::trim", "b.py::clip"]
    assert [s for _, s in near] == sorted((s for _, s in near), reverse=True)
    other_files = comparer.neighbours(SHORTEN, 3, allowed=lambda f: f.path != SHORTEN.path)
    assert [f.qualname for f, _ in other_files] == ["b.py::clip"]


def test_a_function_is_never_its_own_neighbour_and_k_caps_the_list(comparer: TfidfComparer) -> None:
    assert all(f.qualname != SHORTEN.qualname for f, _ in comparer.neighbours(SHORTEN, 10, allowed=lambda f: True))
    assert len(comparer.neighbours(SHORTEN, 1, allowed=lambda f: True)) == 1


def test_an_unindexed_function_can_still_be_queried(comparer: TfidfComparer) -> None:
    fresh = function("c.py", "def cut(text, limit):\n    if len(text) <= limit:\n        return text\n    return text[:limit]\n")
    assert comparer.neighbours(fresh, 1, allowed=lambda f: True)[0][1] > 0.5


def test_similarity_is_the_cosine_and_shared_names_what_drives_it(comparer: TfidfComparer) -> None:
    assert comparer.similarity(SHORTEN, SAME_FILE) == pytest.approx(comparer.similarity(SAME_FILE, SHORTEN))
    assert 0 < comparer.similarity(SHORTEN, CLIP) < comparer.similarity(SHORTEN, SAME_FILE) <= 1.0 + 1e-9
    assert comparer.similarity(SHORTEN, OTHER[0]) == 0
    shared = comparer.shared(SHORTEN, CLIP)
    assert "w:text" in shared and len(comparer.shared(SHORTEN, CLIP, limit=1)) == 1


def test_small_functions_use_the_small_function_floor() -> None:
    comparer = TfidfComparer(min_similarity=0.9, min_similarity_small=0.2)
    large = function("a.py", "def big(x):\n" + "    x += 1\n" * 8 + "    return x\n")
    assert comparer.floor(SHORTEN) == 0.2 and comparer.floor(large) == 0.9
