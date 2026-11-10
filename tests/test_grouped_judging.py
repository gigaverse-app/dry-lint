"""One changed function and several look-alikes in one request: the question, the answer, and the scheduler."""

import json

import anthropic
import httpx2
import pytest

from dry_lint.discovery import CampaignStore
from dry_lint.judges.anthropic import AnthropicJudge
from dry_lint.judges.command import (
    GROUP_OPENING,
    GROUP_RULES,
    OPERATIONS_RULES,
    PAIR_OPENING,
    group_prompt,
    parse_group,
)
from dry_lint.judging import Judging
from dry_lint.models import AppliedPolicy, Candidate, Run
from dry_lint.presets import resolve
from dry_lint.settings import Settings
from dry_lint.store import DirectoryStore, VerdictStore

from conftest import claude, coverage_pair, function


def look_alike(number: int, lane: str = "exploration") -> Candidate:
    return coverage_pair(number).model_copy(update={"lane": lane})


def other_function(number: int) -> Candidate:
    """An exploration pair whose changed function is not `coverage_pair`'s."""
    return Candidate(
        new=function("other.py", "def other(value):\n    return value * 2"),
        existing=function(f"elsewhere{number}.py", f"def elsewhere(value):\n    return value * {number}"),
        similarity=0.8,
        lane="exploration",
    )


def policed(number: int) -> Candidate:
    """A look-alike an adopter rule applies to: its question carries the rule, so it is asked alone."""
    rule = AppliedPolicy(name="rule", reason="adapters stay apart", definition_hash="h")
    return look_alike(number).model_copy(update={"policies": [rule]})


def answer(*objects: dict) -> dict:
    return {"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(list(objects))}]}


def verdict(existing: int, label: str = "separate", score: float = 0.1) -> dict:
    return {"existing": existing, "label": label, "score": score, "owner": "", "why": f"pair {existing}"}


PAIR_ANSWER = {"stop_reason": "end_turn", "content": [{"type": "text", "text": '{"label":"separate","score":0.2}'}]}


def by_question(requests: list) -> anthropic.DefaultHttpxClient:
    """Answers each request by what it asks: a verdict per EXISTING function, or one verdict for a pair.

    Requests of one batch are in flight together, so a fixed sequence of replies would reach them in any order.
    """

    def reply(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        text = sent(request)
        count = sum(line.startswith("# EXISTING ") for line in text.splitlines()) if "# EXISTING 1:" in text else 0
        body = answer(*[verdict(n) for n in range(1, count + 1)]) if count else PAIR_ANSWER
        usage = {"input_tokens": 900, "output_tokens": 120}
        message = {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-haiku-5-5"}
        return httpx2.Response(200, json={**message, "stop_sequence": None, "usage": usage, **body})

    return anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(reply))


def grouped(tmp_path, replies=None, group=3, **discovery):
    settings = resolve(Settings(preset="balanced", discovery={"enabled": True, **discovery}))
    requests: list = []
    options = {**settings.judge.options(), "group": group}
    client = by_question(requests) if replies is None else claude(replies, requests)
    judge = AnthropicJudge(api_key="test", http_client=client, **options)
    store = VerdictStore(DirectoryStore(tmp_path / "verdicts"))
    return settings, judge, store, requests


def check(setup, tmp_path, candidates, revision="tree1"):
    settings, judge, store, _ = setup
    run = Run(repository="owner/repo", session="feature", revision=revision)
    judging = Judging(settings, judge, None, store)
    judging.campaign = CampaignStore(tmp_path / "campaign.sqlite3", run)
    findings = {f.candidate.key: f for f in judging.findings(candidates, run)}
    return findings, judging.campaign.snapshot()


def sent(request) -> str:
    return json.loads(request.content)["messages"][0]["content"]


def test_the_grouped_question_is_the_pair_question_with_another_opening() -> None:
    # INVARIANT: a grouped answer is held to the same rules as a pair's; only the opening sentence differs.
    assert OPERATIONS_RULES.removeprefix(PAIR_OPENING) == GROUP_RULES.removeprefix(GROUP_OPENING)
    text = group_prompt([look_alike(1), look_alike(2)])
    assert text.startswith(GROUP_RULES)
    assert text.count("# NEW: new.py::new") == 1
    assert "# EXISTING 1: existing1.py::existing" in text and "# EXISTING 2: existing2.py::existing" in text
    assert text.index("# EXISTING 1:") < text.index("# EXISTING 2:")


def test_a_grouped_question_refuses_two_changed_functions_or_adopter_policies() -> None:
    with pytest.raises(ValueError, match="one changed function"):
        group_prompt([look_alike(1), other_function(1)])
    with pytest.raises(ValueError, match="no adopter policies"):
        group_prompt([look_alike(1), policed(2)])


def test_a_grouped_answer_is_read_by_the_number_each_object_names() -> None:
    text = "Thinking aloud [not json]. " + json.dumps([verdict(2, "duplicate", 0.9), verdict(1)])
    first, second, third = parse_group(text, 3, "judge", "v")
    assert (first.label, first.why) == ("separate", "pair 1")
    assert (second.label, second.score, second.judge_version) == ("duplicate", 0.9, "v")
    assert third is None  # the answer left it out: unknown, never guessed


def test_a_pair_answered_twice_or_out_of_range_gets_no_verdict() -> None:
    answers = parse_group(json.dumps([verdict(1), verdict(1, "duplicate", 0.9), verdict(7), verdict(2)]), 2, "j", "v")
    assert answers[0] is None and answers[1].why == "pair 2"


def test_unnumbered_answers_are_read_by_position_only_when_none_is_missing() -> None:
    unnumbered = [{"label": "separate", "score": 0.1}, {"label": "duplicate", "score": 0.8}]
    assert [v.label for v in parse_group(json.dumps(unnumbered), 2, "j", "v")] == ["separate", "duplicate"]
    with pytest.raises(ValueError, match="without a JSON array"):
        parse_group(json.dumps(unnumbered), 3, "j", "v")
    with pytest.raises(ValueError, match="without a JSON array"):
        parse_group('{"label":"separate","score":0.1}', 2, "j", "v")


def test_the_group_size_is_part_of_the_judges_version(monkeypatch) -> None:
    alone = AnthropicJudge(api_key="k", model="claude-haiku-5-5", max_tokens=2048)
    together = AnthropicJudge(api_key="k", model="claude-haiku-5-5", max_tokens=2048, group=5)
    assert alone.group == 1 and "group" not in alone.version  # ungrouped judges keep their version and answers
    assert together.version == alone.version + ":group-1x5"
    assert AnthropicJudge(api_key="k", group=3).version != AnthropicJudge(api_key="k", group=5).version
    with pytest.raises(ValueError, match="1 to 8"):
        AnthropicJudge(api_key="k", group=9)
    with pytest.raises(ValueError, match="shared-operations"):
        AnthropicJudge(api_key="k", group=2, prompt_policy="model-contracts")


def test_look_alikes_of_one_changed_function_share_a_request_and_keep_their_own_verdicts(tmp_path) -> None:
    setup = grouped(tmp_path, answer(verdict(1), verdict(2, "duplicate", 0.9), verdict(3)))
    pairs = [look_alike(1), look_alike(2), look_alike(3)]
    findings, state = check(setup, tmp_path, pairs)
    requests = setup[3]

    assert len(requests) == 1
    assert sent(requests[0]).count("# EXISTING ") == 3
    assert json.loads(requests[0].content)["max_tokens"] == 2048 + 2 * 600
    labels = {key: finding.verdict.label for key, finding in findings.items()}
    assert sorted(labels.values()) == ["duplicate", "separate", "separate"]
    # Every pair has its own reservation and settlement; together they cost what the one request cost.
    assert len(state.attempts) == 3 and all(a.status == "answered" for a in state.attempts)
    assert state.usd == pytest.approx(900 * 1e-7 + 120 * 5e-7)
    # Each verdict is stored for its own pair, under the grouped judge's version.
    store, judge = setup[2], setup[1]
    for pair in pairs:
        assert store.lookup(pair, judge.name, 0.0, judge.version, exact_source=True).verdict is not None


def test_baseline_pairs_and_other_changed_functions_are_never_grouped(tmp_path) -> None:
    setup = grouped(tmp_path)
    pairs = [look_alike(1, "baseline"), look_alike(2, "baseline"), look_alike(3), look_alike(4), other_function(1)]
    findings, _ = check(setup, tmp_path, pairs)
    texts = [sent(request) for request in setup[3]]

    assert all(finding.verdict is not None for finding in findings.values())
    assert sorted(text.count("# EXISTING ") for text in texts) == [0, 0, 0, 2]
    group = next(text for text in texts if "# EXISTING 1:" in text)
    assert "existing3.py" in group and "existing4.py" in group and "elsewhere" not in group


def test_a_pair_with_an_adopter_policy_is_asked_alone_with_its_policy(tmp_path) -> None:
    setup = grouped(tmp_path)
    findings, _ = check(setup, tmp_path, [policed(1), look_alike(2), look_alike(3)])
    texts = [sent(request) for request in setup[3]]

    alone = next(text for text in texts if "ADOPTER POLICIES" in text)
    assert "# EXISTING: existing1.py::existing" in alone
    together = next(text for text in texts if "# EXISTING 1:" in text)
    assert "existing1.py" not in together and "ADOPTER POLICIES" not in together
    assert all(finding.verdict is not None for finding in findings.values())


def test_a_group_holds_no_more_pairs_than_the_judge_allows(tmp_path) -> None:
    setup = grouped(tmp_path, group=2)
    findings, _ = check(setup, tmp_path, [look_alike(n) for n in range(1, 6)])

    assert sorted(sent(request).count("# EXISTING ") for request in setup[3]) == [0, 2, 2]
    assert all(finding.verdict is not None for finding in findings.values())


def test_the_pair_cap_counts_every_pair_of_a_group(tmp_path) -> None:
    # INVARIANT: grouping never asks about more pairs than the caps allow; a group stops growing at the cap.
    setup = grouped(tmp_path, answer(verdict(1), verdict(2)), exploration_calls_per_revision=2)
    findings, state = check(setup, tmp_path, [look_alike(n) for n in range(1, 5)])

    assert len(setup[3]) == 1 and len(state.attempts) == 2
    unasked = [finding for finding in findings.values() if finding.verdict is None]
    assert len(unasked) == 2 and all(f.deferred and f.budget_deferred for f in unasked)


def test_a_pair_the_grouped_answer_omits_fails_alone(tmp_path) -> None:
    setup = grouped(tmp_path, answer(verdict(1), verdict(3)))
    pairs = [look_alike(1), look_alike(2), look_alike(3)]
    findings, state = check(setup, tmp_path, pairs)

    judged = [finding for finding in findings.values() if finding.verdict is not None]
    assert len(judged) == 2
    missing = next(finding for finding in findings.values() if finding.verdict is None)
    assert missing.deferred and not missing.budget_deferred  # unfinished work, not a budget gap and not a "no"
    assert sorted(a.status for a in state.attempts) == ["answered", "answered", "failed"]
    # Nothing was stored for it, so a later run asks again.
    store, judge = setup[2], setup[1]
    assert store.lookup(missing.candidate, judge.name, 0.0, judge.version, exact_source=True).verdict is None


def test_a_request_that_fails_fails_every_pair_in_it_and_stores_nothing(tmp_path) -> None:
    unreadable = {"stop_reason": "end_turn", "content": [{"type": "text", "text": "I cannot decide."}]}
    setup = grouped(tmp_path, unreadable)
    findings, state = check(setup, tmp_path, [look_alike(1), look_alike(2)])

    assert all(f.verdict is None and f.deferred and not f.budget_deferred for f in findings.values())
    assert [a.status for a in state.attempts] == ["failed", "failed"]
    assert list(setup[2].backend.keys()) == []


def test_grouped_answers_are_reused_for_the_same_pairs_and_never_by_another_group_size(tmp_path) -> None:
    """
    The reuse rule (AGENTS.md): a grouped answer is the answer to another question than a pair's, so it is stored
    under a version that names the group size. The same judge reuses it for the same exact pair; a judge that asks
    alone, or in another group size, does not.
    """
    reply = answer(verdict(1), verdict(2, "duplicate", 0.9))
    setup = grouped(tmp_path, reply, group=2)
    pairs = [look_alike(1), look_alike(2)]
    check(setup, tmp_path, pairs)
    assert len(setup[3]) == 1

    # The same judge, a later push with the same two pairs: both verdicts come from the store.
    again, _ = check(setup, tmp_path, pairs, revision="tree2")
    assert len(setup[3]) == 1 and all(finding.cached for finding in again.values())

    settings, judge, store, _ = setup
    alone = AnthropicJudge(api_key="test", http_client=claude(PAIR_ANSWER, []), **settings.judge.options())
    wider = AnthropicJudge(api_key="test", http_client=claude(reply, []), **{**settings.judge.options(), "group": 3})
    for other in (alone, wider):
        assert other.name == judge.name and other.version != judge.version
        for pair in pairs:
            assert store.lookup(pair, other.name, 0.0, other.version, exact_source=True).verdict is None


def test_a_stored_look_alike_is_not_asked_again_inside_a_group(tmp_path) -> None:
    setup = grouped(tmp_path, group=3)
    check(setup, tmp_path, [look_alike(1), look_alike(2)])
    findings, _ = check(setup, tmp_path, [look_alike(n) for n in range(1, 5)], revision="tree2")

    second = sent(setup[3][1])
    assert "existing1.py" not in second and "existing2.py" not in second
    assert "existing3.py" in second and "existing4.py" in second
    assert sum(finding.cached for finding in findings.values()) == 2


def test_a_judge_that_cannot_group_is_asked_one_pair_at_a_time(tmp_path) -> None:
    setup = grouped(tmp_path, group=1)
    findings, _ = check(setup, tmp_path, [look_alike(1), look_alike(2), look_alike(3)])

    assert len(setup[3]) == 3 and all("# EXISTING 1:" not in sent(request) for request in setup[3])
    assert all(finding.verdict is not None for finding in findings.values())
