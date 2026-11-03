import json

from dry_lint.models import SCHEMA, Candidate, CandidatesFile, Run, pair_key

from conftest import function

PAIR = Candidate(new=function("a.py", "def f(x):\n    return x\n"), existing=function("b.py", "def g(y):\n    return y\n"),
                 similarity=0.6, comparer="tfidf:1")


def test_a_pair_key_is_short_stable_and_ignores_order() -> None:
    assert pair_key("a.py::f", "b.py::g") == pair_key("b.py::g", "a.py::f") == PAIR.key
    assert len(PAIR.key) == 16 and pair_key("a.py::f", "b.py::h") != PAIR.key


def test_candidates_files_carry_their_schema_and_round_trip_without_tokens() -> None:
    file = CandidatesFile(run=Run(repository="o/r", pull_request=4, head="abc", base="main"), changed=2, candidates=[PAIR])
    data = json.loads(file.model_dump_json())
    assert data["schema"] == SCHEMA and data["run"]["pull_request"] == 4
    assert "tokens" not in data["candidates"][0]["new"] and data["candidates"][0]["new"]["hash"] == PAIR.new.hash
    loaded = CandidatesFile.model_validate_json(file.model_dump_json())
    assert loaded.candidates[0].key == PAIR.key and loaded.candidates[0].new.tokens == []
    assert CandidatesFile.model_validate({"schema": 1}).schema_version == 1


def test_schema_one_candidates_default_to_exact_hash_reuse() -> None:
    legacy = PAIR.model_dump(exclude={"similarity_reusable"})
    loaded = CandidatesFile.model_validate({"schema": 1, "candidates": [legacy]})
    assert loaded.candidates[0].similarity_reusable is False
