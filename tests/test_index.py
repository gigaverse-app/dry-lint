import pytest

from dry_lint.index import TfidfIndex

DOCUMENTS = [["alpha", "beta", "gamma"], ["alpha", "beta", "delta"], ["omega", "sigma"], ["common", "x"],
             ["common", "y"], ["common", "z"], ["common", "w"]]  # fmt: skip


def test_identical_documents_have_cosine_one_and_rank_first() -> None:
    index = TfidfIndex(DOCUMENTS, max_df=0.5)
    position, score = index.similar(["alpha", "beta", "gamma"], limit=3)[0]
    assert position == 0 and score == pytest.approx(1.0)


def test_similar_ranks_by_shared_rare_tokens_and_honours_exclude() -> None:
    index = TfidfIndex(DOCUMENTS, max_df=0.5)
    ranked = index.similar(["alpha", "beta", "gamma"], limit=3, exclude={0})
    assert [position for position, _ in ranked] == [1]
    assert 0 < ranked[0][1] < 1


def test_tokens_in_more_than_max_df_of_documents_carry_no_weight() -> None:
    index = TfidfIndex(DOCUMENTS, max_df=0.5)
    assert "common" not in index.idf
    assert index.similar(["common"], limit=5) == []


def test_vectors_are_unit_length() -> None:
    vector = TfidfIndex(DOCUMENTS, max_df=0.5).vector(["alpha", "alpha", "omega"])
    assert sum(weight * weight for weight in vector.values()) == pytest.approx(1.0)
    assert TfidfIndex(DOCUMENTS).vector(["unknown"]) == {}
