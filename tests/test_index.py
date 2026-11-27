import random

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


def test_a_floor_returns_the_same_documents_scores_and_order_as_the_full_ranking():
    # Skewed token frequencies give long postings for common tokens, tied scores, and documents
    # that share only lightly weighted tokens with the query.
    generator = random.Random(7)
    vocabulary = [f"t{n}" for n in range(60)]
    weights = [1 / (n + 1) for n in range(60)]
    documents = [generator.choices(vocabulary, weights, k=generator.randint(1, 12)) for _ in range(400)]
    documents += documents[:20]
    index = TfidfIndex(documents, max_df=0.6)
    for floor in (0.05, 0.3, 0.5, 0.9, 1.0):
        for position, document in enumerate(documents):
            full = index.similar(document, exclude={position})
            expected = [(other, score) for other, score in full if score >= floor]
            assert index.similar(document, exclude={position}, floor=floor) == expected
            assert index.similar(document, limit=3, exclude={position}, floor=floor) == expected[:3]


def test_a_floor_finds_nothing_for_a_document_without_indexed_tokens():
    index = TfidfIndex(DOCUMENTS, max_df=0.5)
    assert index.similar(["unseen"], floor=0.3) == []
