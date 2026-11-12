# Frozen research test; see PROVENANCE.json.
# ruff: noqa: E401, I001
from rank_harness import score_query
import numpy as np


def test_full_background_self_exclusion_ties_and_language():
    docs = [
        dict(source_id=s, source_sha256=str(i))
        for i, s in enumerate(["q.py::q", "b.py::b", "a.py::a", "q.py::other", "x.ts::x"])
    ]
    panel = dict(cohort_id="test", repository="test/repo", revision="0" * 40, background_sha256="0" * 64)
    mapping = dict(
        row_id="test",
        pair_identity="p",
        family_component="f",
        split="evaluation_regression",
        label="duplicate",
        accepted_gold=True,
        calibration_eligible=True,
    )
    result = score_query(np.array([1, 0.8, 0.8, 0.99, 0.95]), 0, [(mapping, 1, "forward")], docs, "test", panel)[0]
    assert result["competitors"] == 4
    assert result["raw_rank"] == 4
    assert result["eligible_rank"] == 2
    assert result["raw_top100"] == [3, 4, 2, 1]
    assert result["eligible_top100"] == [2, 1]


def test_negative_scores_are_ranked_without_inherited_floor():
    docs = [dict(source_id=s, source_sha256=str(i)) for i, s in enumerate(["q.py::q", "b.py::b"])]
    panel = dict(cohort_id="test", repository="test/repo", revision="0" * 40, background_sha256="0" * 64)
    mapping = dict(
        row_id="test",
        pair_identity="p",
        family_component="f",
        split="evaluation_regression",
        label="separate",
        accepted_gold=True,
        calibration_eligible=True,
    )
    result = score_query(np.array([1, -0.9]), 0, [(mapping, 1, "forward")], docs, "test", panel)[0]
    assert result["raw_rank"] == result["eligible_rank"] == 1
    assert result["score"] == -0.9


def test_recording_from_other_model_is_unknown(tmp_path):
    from native_harness import answer_binding, replay_recorded, Descriptor, settings
    from dry_lint.models import Function, Candidate, Run
    import json, hashlib

    left = Function(path="a.py", name="a", line=1, end_line=2, code="def a():\n    return 1", hash="a")
    right = Function(path="b.py", name="b", line=1, end_line=2, code="def b():\n    return 1", hash="b")
    c = Candidate(new=left, existing=right, similarity=0.9, comparer="test:1")
    run = Run(repository="test/repo", revision="0" * 40, session="test")
    binding = answer_binding(c, run, Descriptor())
    key = hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    wrong = {**binding, "model": "another-model"}
    report = replay_recorded(
        [c],
        settings({"scope": {"include": ["*"], "exclude": []}}),
        run,
        tmp_path,
        {key: {"binding": wrong, "verdict": {}}},
    )
    assert len(report.findings) == 1
    assert report.findings[0].verdict is None
    assert report.findings[0].deferred and not report.findings[0].reported
