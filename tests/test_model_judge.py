"""The real Jev HTTP client emits review evidence; it cannot silently approve model consolidation."""

import json

import httpx
import pytest

from dry_lint.discovery import CampaignStore, reservation_cost
from dry_lint.judges import make_judge
from dry_lint.judges.jev import JevJudge
from dry_lint.judges.model_jev import MODEL_QUESTIONS, ModelJevJudge
from dry_lint.judging import Judging
from dry_lint.model_shapes import PythonModelExtractor
from dry_lint.models import Candidate, Run
from dry_lint.policies import PairPolicy
from dry_lint.report import Report, as_text
from dry_lint.settings import PluginChoice, Settings
from dry_lint.store import DirectoryStore, VerdictStore


def model_pair():
    units = PythonModelExtractor().functions(
        "models.py",
        """
from pydantic import BaseModel
class PromptAnswer(BaseModel):
    title: str
    text: str
class DomainResult(BaseModel):
    title: str
    text: str
""",
    )
    pair = Candidate(new=units[0], existing=units[1], similarity=1)
    policy = PairPolicy(
        name="prompt-domain",
        left={"names": ["Prompt*"]},
        right={"names": ["Domain*"]},
        reason="These schemas evolve independently for prompt tuning and runtime use.",
    )
    pair.policies = [policy.apply(pair.new, pair.existing)]
    return pair


@pytest.mark.parametrize("score", [0.1, 0.95])
def test_model_scores_remain_review_tasks_and_cache_preserves_the_facts(tmp_path, score):
    requests = []

    def answer(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "answers": {name: {"noul": score if name == "shared_authority" else 0.8} for name in MODEL_QUESTIONS},
                "usage": {"input_tokens": 1200, "output_tokens": 100},
            },
        )

    judge = make_judge(PluginChoice(use="jev-models", api_key="test", transport=httpx.MockTransport(answer)))
    pair = model_pair()
    settings = Settings(judge="jev-models", escalate="none", discovery={"enabled": True})
    judging = Judging(settings, judge, None, VerdictStore(DirectoryStore(tmp_path / "verdicts")))
    run = Run(session="models", revision="tree")
    judging.campaign = CampaignStore(tmp_path / "campaign.sqlite3", run)
    found = judging.findings([pair], run)
    report = Report.build(found, settings)
    assert len(report.review_required) == 1
    assert report.findings[0].reported is False
    assert report.findings[0].verdict.score == score
    assert report.findings[0].verdict.model_assessment.policy_requires_separate_owners == 0.8
    assert "prompt-domain" in as_text(report)
    assert "resolve nested types" in as_text(report)
    assert "source_context" not in requests[0]["state"]["new_model"]
    assert requests[0]["state"]["adopter_policies"][0]["name"] == "prompt-domain"
    assert judging.campaign.snapshot().usd == pytest.approx(0.000048)
    cached = judging.findings([pair], run)
    assert cached[0].cached and cached[0].review_required
    assert len(requests) == 1
    restored = Report.model_validate_json(report.model_dump_json())
    assert restored.review_required[0].verdict.model_assessment == found[0].verdict.model_assessment


def test_context_and_guidance_change_model_judge_identity_and_actual_budget_input():
    pair = model_pair()
    plain = ModelJevJudge(api_key="test")
    context = ModelJevJudge(api_key="test", context=True, guidance="Inspect schema ownership.")
    assert context.version != plain.version
    body = context.request_body(pair)
    assert body["state"]["new_model"]["source_context"] == pair.new.context
    assert body["state"]["guidance"] == "Inspect schema ownership."
    assert body["state"]["new_model"]["declaration"]["fields"] == {"title": "str", "text": "str"}
    cost = reservation_cost(context, pair, Settings())
    assert cost >= len(context.input_text(pair).encode()) * 0.04 / 1_000_000
    with pytest.raises(ValueError, match="maximum output"):
        reservation_cost(context, pair, Settings(prices={"jev-models": (0.04, 1)}))


def test_unresolved_or_invalid_provider_data_never_invents_a_safe_verdict():
    judge = ModelJevJudge(api_key="test")
    pair = model_pair()
    pair.new.declaration = None
    with pytest.raises(ValueError, match="two extracted model declarations"):
        judge.request_body(pair)
    with pytest.raises(ValueError):
        judge.verdict({name: {"noul": 1.1} for name in MODEL_QUESTIONS}, Settings())


@pytest.mark.parametrize("data", [{}, {"answers": {}}, {"answers": {"shared_authority": None}}])
def test_incomplete_provider_answers_stay_in_the_agent_queue(tmp_path, data):
    judge = ModelJevJudge(api_key="test", transport=httpx.MockTransport(lambda request: httpx.Response(200, json=data)))
    settings = Settings(judge="jev-models", escalate="none", discovery={"enabled": True})
    judging = Judging(settings, judge, None, VerdictStore(DirectoryStore(tmp_path / "verdicts")))
    run = Run(session="models", revision="tree")
    judging.campaign = CampaignStore(tmp_path / "campaign.sqlite3", run)
    [finding] = judging.findings([model_pair()], run)
    assert finding.review_required and finding.verdict is None
    assert judging.summary().spend[0].failed == 1


def test_generic_jev_also_receives_adopter_policy_evidence():
    pair = model_pair()
    body = JevJudge(api_key="test").request_body(pair)
    assert body["state"]["adopter_policies"] == [p.model_dump() for p in pair.policies]
