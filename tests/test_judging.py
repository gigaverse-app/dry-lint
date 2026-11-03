from pathlib import Path

import pytest

from dry_lint.costs import Ledger, estimate
from dry_lint.judges import label_for
from dry_lint.judging import Judging, decide, default_store, open_store
from dry_lint.models import Candidate, Run, Verdict
from dry_lint.settings import Budget, Escalation, PluginChoice, Settings
from dry_lint.store import S3Store, VerdictStore

from conftest import Repo, function

SETTINGS = Settings(escalate=Escalation(use="second", between=(0.6, 0.8)))


def pair(name: str, filtered: str | None = None) -> Candidate:
    return Candidate(new=function("new.py", f"def {name}(text):\n    return text.strip()\n"),
                     existing=function("old.py", f"def old_{name}(text):\n    return text.strip()\n"),
                     similarity=0.7, comparer="tfidf:1", filtered=filtered)


class ScoringJudge:
    """A judge that scores each pair from a table, and records what it was asked."""

    def __init__(self, name: str, scores: dict[str, float], version: str = "1") -> None:
        self.name, self.version, self.scores, self.asked = name, version, scores, []

    def judge(self, candidates: list[Candidate], settings: Settings) -> list[Verdict]:
        self.asked += [c.new.name for c in candidates]
        return [Verdict(label=label_for(self.scores[c.new.name], 0.0, settings), score=self.scores[c.new.name],
                        why=f"{self.name} says so", judge=self.name, judge_version=self.version) for c in candidates]


def test_without_a_judge_every_proposed_pair_is_an_unjudged_finding(store: VerdictStore) -> None:
    findings = Judging(SETTINGS, None, None, store).findings([pair("a"), pair("b", filtered="one calls the other")])
    assert [(f.candidate.new.name, f.verdict) for f in findings] == [("a", None)]
    assert list(store.records()) == []


def test_each_pair_is_judged_once_and_then_answered_from_the_store(store: VerdictStore) -> None:
    first = ScoringJudge("first", {"a": 0.9, "b": 0.1})
    findings = Judging(SETTINGS, first, None, store).findings([pair("a"), pair("b")], source=Run(pull_request=3))
    assert first.asked == ["a", "b"] and [f.cached for f in findings] == [False, False]
    again = ScoringJudge("first", {"a": 0.0, "b": 0.0})
    cached = Judging(SETTINGS, again, None, store).findings([pair("a"), pair("b")])
    assert again.asked == [] and [f.verdict.score for f in cached] == [0.9, 0.1] and all(f.cached for f in cached)
    assert {r.source.pull_request for r in store.records()} == {3}


def test_only_first_scores_in_the_escalation_band_go_to_the_second_judge(store: VerdictStore) -> None:
    first = ScoringJudge("first", {"low": 0.3, "unsure": 0.7, "sure": 0.9}, version="v2")
    second = ScoringJudge("second", {"unsure": 0.95})
    findings = Judging(SETTINGS, first, second, store).findings([pair("low"), pair("unsure"), pair("sure")])
    assert second.asked == ["unsure"]
    by_name = {f.candidate.new.name: f.verdict for f in findings}
    assert (by_name["unsure"].score, by_name["unsure"].why, by_name["unsure"].second_opinion) == (0.95, "second says so", "second:1")
    assert (by_name["unsure"].judge, by_name["unsure"].judge_version) == ("first", "v2")  # stored under the first judge
    assert by_name["sure"].second_opinion is None and by_name["low"].score == 0.3


def test_an_escalated_answer_is_reused_like_any_other(store: VerdictStore) -> None:
    Judging(SETTINGS, ScoringJudge("first", {"unsure": 0.7}), ScoringJudge("second", {"unsure": 0.2}), store) \
        .findings([pair("unsure")])
    second = ScoringJudge("second", {"unsure": 0.9})
    [finding] = Judging(SETTINGS, ScoringJudge("first", {}), second, store).findings([pair("unsure")])
    assert finding.cached and finding.verdict.score == 0.2 and second.asked == []


def test_refresh_re_judges_verdicts_from_an_older_version_of_the_judge(store: VerdictStore) -> None:
    Judging(SETTINGS, ScoringJudge("first", {"a": 0.9}, version="v1"), None, store).findings([pair("a")])
    newer = ScoringJudge("first", {"a": 0.2}, version="v2")
    assert Judging(SETTINGS, newer, None, store).findings([pair("a")])[0].cached
    [refreshed] = Judging(SETTINGS, newer, None, store).findings([pair("a")], refresh=True)
    assert newer.asked == ["a"] and refreshed.verdict.judge_version == "v2"


def test_configured_judging_names_its_judges(store: VerdictStore, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TYPESAFE_AI_API_KEY", raising=False)
    assert Judging.configured(SETTINGS, store).name is None
    settings = Settings(judge=PluginChoice(use="command", command="llm-a"),
                        escalate=Escalation(use="command", command="llm-b", version="big"))
    judging = Judging.configured(settings, store)
    assert judging.name == "command:llm-a:1 > command:llm-b:big"
    assert Judging.configured(settings.model_copy(update={"escalate": None}), store).name == "command:llm-a:1"


def test_the_store_is_a_folder_in_the_git_directory_unless_configured(repo: Repo, tmp_path: Path) -> None:
    assert default_store(repo.root) == (repo.root / ".git" / "dry-lint" / "verdicts").resolve()
    assert open_store(Settings(), repo.root).backend.path == default_store(repo.root)
    assert open_store(Settings(), repo.root, tmp_path / "x").backend.path == tmp_path / "x"
    chosen = Settings(store=PluginChoice(use="dir", path="build/verdicts"))
    assert open_store(chosen, repo.root).backend.path == repo.root / "build/verdicts"


def test_other_store_backends_come_from_their_plugin(repo: Repo, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    store = open_store(Settings(store=PluginChoice(use="s3", uri="s3://bucket/prefix")), repo.root)
    assert isinstance(store.backend, S3Store) and store.backend.prefix == "prefix/"


class Billed(ScoringJudge):
    """A ScoringJudge with a per-token price, so the budget applies to it."""

    model = "claude-sonnet-5-5"


def pair_at(name: str, similarity: float) -> Candidate:
    return pair(name).model_copy(update={"similarity": similarity})


def test_the_budget_judges_the_closest_look_alikes_first_and_leaves_the_rest_unjudged(store: VerdictStore) -> None:
    first = Billed("first", {"near": 0.9, "far": 0.9, "mid": 0.9})
    one = estimate(first, [pair("near")], SETTINGS)
    settings = SETTINGS.model_copy(update={"budget": Budget(usd=one * 2.5)})
    judging = Judging(settings, first, None, store)
    findings = judging.findings([pair_at("far", 0.3), pair_at("near", 0.9), pair_at("mid", 0.6)])
    assert first.asked == ["near", "mid"]
    assert {f.candidate.new.name: f.verdict is not None for f in findings} == {"far": False, "near": True, "mid": True}
    assert [f.candidate.new.name for f in findings if f.deferred] == ["far"]  # reported as not cleared
    assert len(list(store.records())) == 2  # an unjudged pair is not stored, so the next run asks again
    summary = judging.summary()
    assert (summary.skipped, summary.spend[0].calls) == (1, 2)
    assert summary.usd == pytest.approx(estimate(first, [pair("near"), pair("mid")], SETTINGS))


def test_the_second_judge_takes_the_highest_first_scores_and_the_rest_keep_the_first_answer(store: VerdictStore) -> None:
    second = Billed("second", {"a": 0.95, "b": 0.95, "c": 0.95})
    one = estimate(second, [pair("a")], SETTINGS)
    settings = SETTINGS.model_copy(update={"budget": Budget(usd=one * 1.5)})
    first = ScoringJudge("first", {"a": 0.65, "b": 0.75, "c": 0.62})
    answers = decide([pair("a"), pair("b"), pair("c")], first, second, settings, Ledger(settings))
    assert second.asked == ["b"]
    assert [(v.score, v.second_opinion) for v in answers] == [(0.65, None), (0.95, "second:1"), (0.62, None)]


def test_without_a_ledger_nothing_is_limited(store: VerdictStore) -> None:
    second = Billed("second", {"a": 0.9})
    decide([pair("a")], ScoringJudge("first", {"a": 0.7}), second, SETTINGS.model_copy(update={"budget": Budget(usd=0)}))
    assert second.asked == ["a"]


def test_the_summary_names_the_preset_judges_band_thresholds_and_budget(store: VerdictStore) -> None:
    settings = SETTINGS.model_copy(update={"preset": "jev+sonnet", "report_at": 0.6, "fail_at": 0.7})
    summary = Judging(settings, ScoringJudge("first", {}), ScoringJudge("second", {}), store).summary()
    assert (summary.preset, summary.judge, summary.escalation, summary.band) == ("jev+sonnet", "first:1", "second:1", (0.6, 0.8))
    assert (summary.report_at, summary.fail_at, summary.budget_usd, summary.spend) == (0.6, 0.7, 0.25, [])
    assert Judging(settings, None, None, store).summary().judge is None
