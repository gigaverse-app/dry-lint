"""Adopter ownership rules affect review, without mistaking a path convention for a verdict."""

import json

import httpx
import pytest

from dry_lint.detector import Detector
from dry_lint.discovery import CampaignStore
from dry_lint.feedback import Decision, Feedback
from dry_lint.judges.command import prompt
from dry_lint.judges.model_jev import MODEL_QUESTIONS, ModelJevJudge
from dry_lint.judging import Judging
from dry_lint.models import CandidatesFile, Run, Verdict, evidence
from dry_lint.policies import PairPolicy
from dry_lint.report import Report, as_markdown
from dry_lint.settings import Settings
from dry_lint.store import DirectoryStore, VerdictStore

from conftest import Repo


def configured_pairs(tmp_path, policies):
    repo = Repo(tmp_path / "adopter")
    for path, name in [
        ("prompts/reply.py", "ReplySchema"),
        ("domain/reply.py", "Reply"),
        ("domain/copy.py", "ReplyCopy"),
    ]:
        repo.write(path, f"from pydantic import BaseModel\nclass {name}(BaseModel):\n    topic: str\n    body: str\n")
    repo.commit()
    settings = Settings(extractors=["python-models"], comparer="model-shape", policies=policies)
    detector = Detector.for_repository(repo.root, settings)
    return settings, detector, detector.candidates(detector.functions)


def prompt_policy(**changes):
    return {
        "name": "prompt-domain",
        "left": {"paths": ["prompts/*"], "names": ["*Schema"], "role": "structured LLM answer"},
        "right": {"paths": ["domain/*"], "role": "conformed application model"},
        "reason": "Prompt fields evolve independently to tune LLM behavior.",
        **changes,
    }


def test_pair_policies_are_symmetric_and_preserve_same_owner_candidates(tmp_path):
    _, detector, pairs = configured_pairs(tmp_path, [prompt_policy(action="discard")])
    discarded = [p for p in pairs if p.filtered]
    assert len(discarded) == 2
    assert len([p for p in pairs if not p.filtered]) == 1
    assert all("prompt-domain" in p.filtered and "independently" in p.filtered for p in discarded)
    for pair in discarded:
        reverse = detector.pair(pair.existing, pair.new, pair.similarity)
        assert reverse.policies == pair.policies
        assert reverse.context_hash == pair.context_hash
    restored = CandidatesFile.model_validate_json(CandidatesFile(candidates=pairs).model_dump_json())
    assert restored.model_dump() == CandidatesFile(candidates=pairs).model_dump()


def test_guidance_and_priority_reach_review_without_discarding(tmp_path):
    _, _, pairs = configured_pairs(tmp_path, [prompt_policy(priority=-5)])
    assert all(p.filtered is None for p in pairs)
    assert [p.priority for p in pairs] == [0, -5, -5]
    assert "Prompt fields evolve independently" in prompt(pairs[-1], policy="model-contracts")
    assert "structured LLM answer" in prompt(pairs[-1], policy="model-contracts")
    campaign = CampaignStore(tmp_path / "campaign.sqlite3", Run(session="models", revision="tree"))
    assert [p.priority for p in campaign.order(list(reversed(pairs)))] == [0, -5, -5]
    # A high-priority exploration pair cannot spend the protected baseline's slots first.
    explored = pairs[0].model_copy(update={"lane": "exploration"})
    assert campaign.order([explored, pairs[-1]])[0].lane == "baseline"


def test_policy_edits_reopen_cached_verdicts_and_reviewed_dismissals(tmp_path):
    _, detector, pairs = configured_pairs(tmp_path, [prompt_policy()])
    original = next(p for p in pairs if p.policies)
    store = VerdictStore(DirectoryStore(tmp_path / "verdicts"))
    store.remember(original, Verdict(label="separate", score=0.1, judge="test", judge_version="1"))
    feedback = Feedback(
        decisions=[
            Decision(
                pair=original.key,
                evidence=evidence(original),
                action="dismiss",
                reason="Independent prompt ownership",
                reviewer="agent",
                revision="tree",
            )
        ]
    )
    assert store.lookup(original, "test", 0.05).verdict is not None
    assert feedback.apply([original])[0].filtered
    detector.settings.policies[0].reason = "These contracts now share one schema owner."
    changed = detector.pair(original.new, original.existing, original.similarity)
    assert changed.key == original.key
    assert store.lookup(changed, "test", 0.05).verdict is None
    assert feedback.apply([changed])[0].filtered is None


@pytest.mark.parametrize(
    "selector", [{"paths": ["elsewhere/*"]}, {"names": ["Other*"]}, {"repositories": ["other/repo"]}]
)
def test_all_selector_dimensions_must_match(tmp_path, selector):
    rule = prompt_policy(action="discard")
    rule["left"].update(selector)
    _, _, pairs = configured_pairs(tmp_path, [rule])
    assert all(not p.filtered and not p.policies for p in pairs)


@pytest.mark.parametrize("action,expected_calls", [("review", 2), ("discard", 1)])
def test_policy_controls_real_judge_admission_and_preserves_discard_receipts(tmp_path, action, expected_calls):
    settings, _, pairs = configured_pairs(tmp_path, [prompt_policy(action=action, priority=5)])
    settings.max_judgements = 2
    requests = []

    def answer(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"answers": {name: {"noul": 0.5} for name in MODEL_QUESTIONS}})

    judge = ModelJevJudge(api_key="test", transport=httpx.MockTransport(answer))
    judging = Judging(settings, judge, None, VerdictStore(DirectoryStore(tmp_path / "verdicts")))
    found = judging.findings(list(reversed(pairs)))
    assert len(requests) == expected_calls
    assert all(bool(r["state"]["adopter_policies"]) == (action == "review") for r in requests)
    report = Report.build(found, settings, judge=judging.name, filtered=[p for p in pairs if p.filtered])
    if action == "discard":
        assert len(report.filtered) == 2
        assert "prompt-domain" in as_markdown(report)
        assert "Prompt fields evolve independently" in report.model_dump_json()
    else:
        assert sum(f.deferred for f in found) == 1


def test_overlapping_selectors_preserve_ambiguous_roles_in_both_directions(tmp_path):
    _, _, pairs = configured_pairs(tmp_path, [])
    rule = PairPolicy(
        name="ambiguous", reason="Check both consumers", left={"role": "producer"}, right={"role": "consumer"}
    )
    pair = pairs[0]
    applied = rule.apply(pair.new, pair.existing)
    assert applied == rule.apply(pair.existing, pair.new)
    assert all(roles == ["consumer", "producer"] for roles in applied.roles.values())


def test_legacy_candidates_and_verdicts_do_not_acquire_policy_or_model_claims(tmp_path):
    _, _, pairs = configured_pairs(tmp_path, [])
    payload = CandidatesFile(candidates=pairs).model_dump()
    payload["schema"] = 9
    for pair in payload["candidates"]:
        pair.pop("policies")
    legacy = CandidatesFile.model_validate(payload)
    assert legacy.candidates[0].context_hash == pairs[0].context_hash
    assert legacy.candidates[0].policies == []
    assert Verdict.model_validate({"label": "separate", "score": 0.1, "judge": "old"}).model_assessment is None
