"""Labelling a replay: blind labels, a weighted sample, and numbers that describe every pair the replay proposed."""

import json
import sys
from pathlib import Path

import httpx
import pytest

from dry_lint.bench import load_gold
from dry_lint.labelling import (
    Answer,
    CommandLabeller,
    Labels,
    OpenRouterLabeller,
    Sampled,
    allocate,
    gold,
    label,
    labeller,
    majority,
    outcome_intervals,
    outcomes,
    parse,
    prompt,
    sample,
    stratum,
    summarise,
)
from dry_lint.models import Candidate, Verdict
from dry_lint.replay import Replay
from dry_lint.report import Finding
from dry_lint.settings import Settings

from conftest import function, run_cli


def finding(n: int, score: float | None, reported: bool = False, blocking: bool = False, new: str = "",
            existing: str = "") -> Finding:
    candidate = Candidate(new=function("a.py", f"def {new or f'f{n}'}():\n    return 1"),
                          existing=function("b.py", f"def {existing or f'g{n}'}():\n    return 1"), similarity=0.5)
    verdict = None if score is None else Verdict(label="duplicate" if score >= 0.6 else "separate", score=score, judge="j")
    return Finding(candidate=candidate, verdict=verdict, reported=reported, blocking=blocking)


def script(tmp_path: Path, name: str, body: str) -> str:
    """A labeller command: records each prompt it is asked, then answers from `body` (Python using `text`)."""
    path, log = tmp_path / f"{name}.py", tmp_path / f"{name}.log"
    path.write_text("import json, pathlib, sys\n"
                    "text = sys.stdin.read()\n"
                    f"pathlib.Path({str(log)!r}).open('a').write(json.dumps(text) + '\\n')\n" + body)
    return f'command:"{sys.executable}" "{path}"'


def asked(tmp_path: Path, name: str) -> list[str]:
    log = tmp_path / f"{name}.log"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


TWIN_AWARE = ("twin = 'preview_caption_text' in text and 'shorten_text' in text\n"
              "print('Thinking. ' + json.dumps({'label': 'CONSOLIDATE' if twin else 'SEPARATE', 'variation': 'drifted',"
              " 'owner': 'B', 'concept': 'shorten text'}))\n")


def test_the_prompt_shows_the_guideline_and_both_functions_and_nothing_about_scores() -> None:
    text = prompt(finding(1, 0.97).candidate)
    assert "CONSOLIDATE" in text and "a.py::f1" in text and "b.py::g1" in text
    assert "score" not in text.lower() and "judge" not in text.lower() and "similarity" not in text.lower()


@pytest.mark.parametrize("text,expected", [
    ('{"label": "pattern"}', "PATTERN"),
    ('So {not json} and {"x": 1} then {"label": "Consolidate"}', "CONSOLIDATE"),
    ('{"label": "maybe"}', None),
    ("nothing", None),
])
def test_an_answer_is_the_first_object_with_a_known_label(text, expected) -> None:
    assert (parse(text) or {}).get("label") == expected


@pytest.mark.parametrize("given,expected", [
    (["CONSOLIDATE", "CONSOLIDATE", "PATTERN"], "duplicate"),
    (["SEPARATE", "PATTERN", "CONSOLIDATE"], "separate"),
    (["CONSOLIDATE", "SEPARATE"], "borderline"),
    (["CONSOLIDATE", None, None], "duplicate"),  # only usable answers vote
    ([None], None),
    ([], None),
])
def test_the_label_is_a_strict_majority_of_usable_answers(given, expected) -> None:
    assert majority([Answer(key="k", labeller=str(i), label=g) for i, g in enumerate(given)]) == expected


def test_scores_fall_into_bench_bands_and_unjudged_pairs_have_their_own() -> None:
    assert stratum(finding(1, 0.65)) == "0.6-0.7" and stratum(finding(2, 1.0)) == "0.9-1.0"
    assert stratum(finding(3, None)) == "unjudged"


@pytest.mark.parametrize("available,size", [
    ({"a": 50, "b": 50, "c": 50}, 30), ({"a": 2, "b": 100}, 40), ({"a": 3, "b": 4}, 100), ({"a": 9, "b": 9}, 1),
])
def test_allocation_reaches_the_size_it_can_and_never_exceeds_a_stratum(available, size) -> None:
    taken = allocate(available, {"a": 5, "b": 2, "c": 2}, size)
    assert sum(taken.values()) == min(max(size, len(available)), sum(available.values()))
    assert all(1 <= taken[n] <= available[n] for n in available)


def test_allocation_favours_the_strata_with_the_larger_shape() -> None:
    taken = allocate({"decides": 100, "obvious": 100}, {"decides": 5, "obvious": 2}, 35)
    assert taken["decides"] > taken["obvious"]


def test_the_sample_is_distinct_latest_reproducible_and_weighted_to_the_population() -> None:
    older = [finding(n, 0.1 * (n % 10)) for n in range(200)]
    newer = finding(7, 0.95, reported=True)  # the same pair as older[7], met again later
    findings = [*older, newer]
    pairs = sample(findings, 40)
    assert pairs == sample(findings, 40) and len(pairs) == 40
    assert len({p.finding.candidate.key for p in pairs}) == len(pairs)
    strata: dict[str, list[Sampled]] = {}
    for pair in pairs:
        strata.setdefault(pair.stratum, []).append(pair)
    distinct = {f.candidate.key: f for f in findings}.values()
    for name, members in strata.items():
        population = sum(stratum(f) == name for f in distinct)
        assert sum(p.weight for p in members) == pytest.approx(population)
    sevens = [p for p in pairs if p.finding.candidate.key == newer.candidate.key]
    assert all(p.finding.reported for p in sevens)  # the latest finding of a pair is the one sampled


def test_labelling_asks_each_labeller_once_per_pair_and_resumes(tmp_path) -> None:
    pairs = sample([finding(1, 0.9, new="preview_caption_text", existing="shorten_text"), finding(2, 0.2)], 2)
    panel = [labeller(script(tmp_path, n, TWIN_AWARE)) for n in ("one", "two")]
    answers = tmp_path / "gold.answers.jsonl"
    first = label(pairs, panel, answers, budget_usd=5)
    assert len(first) == 4 and all(a.label for a in first) and len(asked(tmp_path, "one")) == 2
    again = label(pairs, panel, answers, budget_usd=5)
    assert len(asked(tmp_path, "one")) == 2 and len(again) == 4  # answered pairs are never asked again


def test_a_labeller_that_never_answers_usably_is_retried_and_recorded_as_no_answer(tmp_path) -> None:
    pairs = sample([finding(1, 0.9)], 1)
    broken = labeller(script(tmp_path, "broken", "print('no json')\n"))
    failing = labeller(script(tmp_path, "failing", "sys.exit(2)\n"))
    answers = label(pairs, [broken, failing], tmp_path / "answers.jsonl", budget_usd=5)
    assert [a.label for a in answers] == [None, None]
    assert len(asked(tmp_path, "broken")) == 3 and len(asked(tmp_path, "failing")) == 3
    label(pairs, [broken], tmp_path / "answers.jsonl", budget_usd=5)
    assert len(asked(tmp_path, "broken")) == 6  # no usable answer yet, so it is asked again


def openrouter(seen: list[dict], cost: float | None = 0.5) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append({"body": json.loads(request.content), "auth": request.headers["Authorization"]})
        usage = {} if cost is None else {"cost": cost}
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"label": "SEPARATE"}'}}], "usage": usage})
    return httpx.MockTransport(handle)


def test_openrouter_labellers_ask_the_model_and_report_cost(monkeypatch) -> None:
    seen: list[dict] = []
    who = OpenRouterLabeller("vendor/model", api_key="secret", transport=openrouter(seen))
    assert who.ask("question") == ('{"label": "SEPARATE"}', 0.5)
    assert seen[0]["body"]["model"] == "vendor/model" and seen[0]["auth"] == "Bearer secret"
    assert seen[0]["body"]["usage"] == {"include": True}
    assert OpenRouterLabeller("m", api_key="k", transport=openrouter([], cost=None)).ask("q")[1] is None
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        labeller("vendor/model")
    assert isinstance(labeller("command:echo"), CommandLabeller)


def test_labelling_stops_when_this_run_reaches_its_budget(tmp_path) -> None:
    pairs = sample([finding(n, 0.1 * n) for n in range(10)], 10)
    who = OpenRouterLabeller("m", api_key="k", transport=openrouter([], cost=1.0))
    answers = label(pairs, [who], tmp_path / "answers.jsonl", budget_usd=1.5, workers=1)
    assert len(answers) == 2  # the second answer took this run past its budget
    more = label(pairs, [who], tmp_path / "answers.jsonl", budget_usd=1.5, workers=1)
    assert len(more) == 4  # a new run has its own budget


def labelled_rows() -> tuple[list[Sampled], list[Answer]]:
    pairs = [Sampled(finding=finding(1, 0.95, reported=True, blocking=True), stratum="0.9-1.0", weight=1.0),
             Sampled(finding=finding(2, 0.65, reported=True), stratum="0.6-0.7", weight=2.0),
             Sampled(finding=finding(3, 0.2), stratum="0.1-0.3", weight=10.0),
             Sampled(finding=finding(4, 0.2), stratum="0.1-0.3", weight=10.0),
             Sampled(finding=finding(5, 0.7), stratum="0.7-0.8", weight=1.0)]
    votes = [["CONSOLIDATE"] * 3, ["PATTERN", "SEPARATE", "CONSOLIDATE"], ["CONSOLIDATE", "CONSOLIDATE", "SEPARATE"],
             ["SEPARATE"] * 3, ["CONSOLIDATE", "SEPARATE"]]
    answers = [Answer(key=p.finding.candidate.key, labeller=f"l{i}", label=v, variation="drifted" if i else "",
                      owner="B") for p, given in zip(pairs, votes) for i, v in enumerate(given)]
    return pairs, answers


def test_outcomes_count_what_the_judging_caught_missed_and_got_wrong() -> None:
    pairs, answers = labelled_rows()
    rows = gold(pairs, answers)
    assert [g.label for _, g in rows] == ["duplicate", "separate", "duplicate", "separate", "borderline"]
    totals = outcomes(rows)
    assert totals == {"real": 11.0, "reported_real": 1.0, "reported_false": 2.0, "blocking_real": 1.0,
                      "blocking_false": 0.0, "missed": 10.0}  # the borderline pair counts for nothing
    first = rows[0][1]
    assert first.drifted is True and first.owner == "existing" and first.stratum == "0.9-1.0"
    assert rows[1][1].drifted is None and rows[1][1].owner is None


def test_outcome_intervals_have_no_width_where_a_stratum_was_labelled_in_full() -> None:
    pairs, answers = labelled_rows()
    rows = gold(pairs, answers)
    spans = outcome_intervals(rows, resamples=200)
    assert spans["blocking_real"] == (1.0, 1.0)  # one pair in its stratum: no sampling error
    assert spans["missed"][0] <= outcomes(rows)["missed"] <= spans["missed"][1]
    assert outcome_intervals([]) == dict.fromkeys(spans, (0.0, 0.0))


def test_the_summary_writes_bench_gold_and_measures_the_judging_on_it(tmp_path) -> None:
    pairs, answers = labelled_rows()
    path = tmp_path / "gold" / "gold.jsonl"
    labels = summarise(pairs, answers, ["l0", "l1", "l2"], Settings(), path, commits=50, judge="j")
    written = load_gold(path)
    assert len(written) == labels.labelled == 5 and labels.borderline == 1 and labels.duplicates == 2
    assert labels.unanimous == 2 and labels.usd is None  # some answers did not report a cost
    assert labels.judge is not None and labels.judge.pairs == 4 and labels.judge.duplicates == 2
    text = labels.as_text()
    assert "5 of 5 sampled pairs" in text and "per 100 commits" in text and "a full count" in text
    assert "judging on the labelled pairs" in text
    unjudged = summarise(pairs, answers, ["l0"], Settings(), path, commits=50, judge=None)
    assert unjudged.judge is None and "judging on the labelled pairs" not in unjudged.as_text()
    priced = summarise(pairs, [a.model_copy(update={"usd": 0.01}) for a in answers], ["l0"], Settings(), path, 50, "j")
    assert priced.usd == pytest.approx(0.14) and "est. $0.14" in priced.as_text()


def test_figures_round_to_whole_numbers_from_ten_up() -> None:
    labels = Labels(gold="g", labellers=["l"], sampled=1, labelled=1, unanimous=1, duplicates=1, borderline=0,
                    usd=0.0, commits=100, outcomes={n: v for n, v in zip(("real", "reported_real", "reported_false",
                                                                           "blocking_real", "blocking_false", "missed"),
                                                                          (25.4, 3.25, 0, 0, 0, 22.0))},
                    intervals=dict.fromkeys(("real", "reported_real", "reported_false", "blocking_real",
                                             "blocking_false", "missed"), (1.0, 30.0)))
    text = labels.as_text()
    assert "real duplicates proposed  25 (1.0-30)" in text and "reported                  3.2" in text


def test_bench_replay_labels_a_sample_writes_gold_and_reports_outcomes(history, tmp_path, blocking_twin_judge,
                                                                      capsys) -> None:
    panel = [arg for n in ("one", "two", "three") for arg in ("--labeller", script(tmp_path, n, TWIN_AWARE))]
    gold_path = tmp_path / "labels" / "gold.jsonl"
    args = ("--replay", "5", "--ref", "main", "--judge", "command", "--judge-command", blocking_twin_judge,
            "--label", "10", "--gold-out", str(gold_path), *panel)
    assert run_cli(history, tmp_path, *args, command="bench") == 0
    out = capsys.readouterr().out
    assert "labels: " in out and "3 labellers" in out and "real duplicates proposed" in out
    written = load_gold(gold_path)
    assert any(g.label == "duplicate" and g.new.id.endswith("preview_caption_text") for g in written)
    calls = len(asked(tmp_path, "one"))
    assert run_cli(history, tmp_path, *args, "--format", "json", command="bench") == 0
    result = Replay.model_validate_json(capsys.readouterr().out)
    assert result.labels is not None and result.labels.duplicates >= 1
    assert len(asked(tmp_path, "one")) == calls  # the second run reused every answer
    assert (gold_path.parent / "gold.answers.jsonl").exists()


def test_labels_go_inside_the_git_directory_by_default(history, tmp_path, capsys) -> None:
    panel = ("--labeller", script(tmp_path, "one", TWIN_AWARE))
    assert run_cli(history, tmp_path, "--replay", "2", "--ref", "main", "--judge", "none", "--label", "3", *panel,
                   command="bench") == 0
    assert (history.root / ".git" / "dry-lint" / "gold" / "replay.jsonl").exists()
    assert "labels: " in capsys.readouterr().out


@pytest.mark.parametrize("args,message", [
    (("--gold", "gold.jsonl", "--label", "5"), "use it with --replay"),
    (("--replay", "2", "--ref", "main", "--label", "0"), "at least 1"),
])
def test_label_refuses_what_it_cannot_do(history, tmp_path, capsys, args, message) -> None:
    assert run_cli(history, tmp_path, "--judge", "none", *args, command="bench") == 2
    assert message in capsys.readouterr().err


def test_a_missing_openrouter_key_stops_before_the_replay_starts(history, tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert run_cli(history, tmp_path, "--replay", "2", "--ref", "main", "--judge", "none", "--label", "3",
                   command="bench") == 2
    captured = capsys.readouterr()
    assert "OPENROUTER_API_KEY" in captured.err and "replay 1/" not in captured.err


def test_a_pair_no_labeller_answered_is_left_out_of_the_gold() -> None:
    pairs, answers = labelled_rows()
    unanswered = Sampled(finding=finding(9, 0.5), stratum="0.5-0.6", weight=3.0)
    rows = gold([*pairs, unanswered], answers + [Answer(key=unanswered.finding.candidate.key, labeller="l0", label=None)])
    assert unanswered.finding.candidate.key not in {p.finding.candidate.key for p, _ in rows} and len(rows) == 5
