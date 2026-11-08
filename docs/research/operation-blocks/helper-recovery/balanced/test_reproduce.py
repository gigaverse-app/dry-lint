"""Report boundary and evidence mismatch checks use recorded real candidates."""

import copy

import pytest
import reproduce as r


def test_report_policy():
    data = r.load()
    candidate = r.Candidate.model_validate(data["entries"][0]["packet"]["candidate"])
    settings = r.Settings.model_validate(data["settings"])
    for label, score, expected in [
        ("duplicate", 0.45, False),
        ("duplicate", 0.5, True),
        ("drifted", 0.55, True),
        ("separate", 0.9, False),
    ]:
        verdict = r.Verdict(label=label, score=score, judge="recorded", judge_version="1")
        assert r.reported(candidate, verdict, settings) is expected


def test_identity_change_rejected():
    data = r.load()
    request = copy.deepcopy(data["requests"][0])
    request["identity"]["model"] = "wrong-model"
    with pytest.raises(AssertionError):
        r.verify_request(request, data["entries"][0], data["observations"][request["request_key"]])


def test_source_body_change_rejected():
    data = r.load()
    entry = data["entries"][0]
    review = copy.deepcopy(next(x for x in data["reviews"] if x["packet_id"] == entry["blind_id"]))
    review["endpoints"][0]["exact_body"] += "\nchanged"
    with pytest.raises(AssertionError):
        r.verify_review(entry, review)


def test_returned_model_must_match_recorded_request():
    data = r.load()
    entry = data["entries"][0]
    request = next(x for x in data["requests"] if x["case_id"] == entry["id"] and x["identity"]["kind"] == "claude")
    observation = copy.deepcopy(data["observations"][request["request_key"]])
    observation["raw_responses"][0]["json"]["model"] = "claude-sonnet-5-5"
    with pytest.raises(AssertionError):
        r.verify_request(request, entry, observation)


def test_missing_source_review_cannot_become_negative_truth():
    data = r.load()
    data["reviews"] = []
    with pytest.raises(KeyError):
        r.calculate(data)
