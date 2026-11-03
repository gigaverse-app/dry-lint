"""The preset replay measures what `check` would have proposed on each past commit, and nothing else."""

import json
import runpy
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from dry_lint.bench import GoldFunction, GoldPair
from dry_lint.models import Candidate, Function, Verdict
from dry_lint.settings import Settings

from conftest import EXISTING, TWIN, Repo, filler_module

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture
def replay(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    return runpy.run_path(str(SCRIPTS / "replay_presets.py"))


@pytest.fixture
def history(tmp_path: Path) -> Repo:
    """main: a helper and fillers; a twin of the helper; a docs-only change; an ignored second twin."""
    repo = Repo(tmp_path / "repo")
    repo.write("src/text.py", EXISTING)
    repo.write("src/filler.py", filler_module())
    repo.commit("helper")
    repo.write("src/widgets/caption.py", TWIN)
    repo.commit("twin")
    repo.write("README.md", "docs\n")
    repo.commit("docs")
    repo.write("src/other/ignored.py", TWIN.replace("def preview_caption_text(caption_text, max_len):",
                                                    "def label_text(caption_text, max_len):  # dry-lint: ignore"))
    repo.write("tests/test_text.py", "def test_x():\n    assert True\n    assert True\n")
    repo.commit("ignored twin")
    return repo


@pytest.mark.parametrize("row,expected", [
    ({"rank": 1, "similarity": 0.9, "floor": 0.5}, {"baseline", "k5", "floor"}),
    ({"rank": 4, "similarity": 0.6, "floor": 0.5}, {"k5"}),
    ({"rank": 2, "similarity": 0.45, "floor": 0.5}, {"floor"}),
    ({"rank": 5, "similarity": 0.45, "floor": 0.5}, set()),
    ({"behaviour": True, "behaviour_similarity": 0.8, "floor": 0.5}, {"behaviour"}),
])
def test_each_option_proposes_exactly_what_its_retrieval_would(replay, row, expected) -> None:
    assert replay["sources"](row) == expected


def test_production_candidates_are_a_subset_of_every_wider_option(replay) -> None:
    for rank in range(1, 6):
        for similarity in (0.25, 0.45, 0.55, 0.95):
            found = replay["sources"]({"rank": rank, "similarity": similarity, "floor": 0.5})
            if "baseline" in found:
                assert {"k5", "floor"} <= found


def test_a_pair_belongs_to_the_first_option_that_proposes_it(replay) -> None:
    assert replay["stratum"]({"behaviour", "k5", "baseline"}) == "baseline"
    assert replay["stratum"]({"behaviour", "floor"}) == "floor"


def test_replay_proposes_the_helper_for_the_twin_commit_and_skips_what_check_would_skip(replay, history, tmp_path) -> None:
    out = tmp_path / "out"
    meta = replay["replay"](history.root, "HEAD", 10, out)
    commits = replay["read"](out / "commits.jsonl")
    assert len(commits) == 4  # every first-parent commit, the root included
    by_order = {i: c for i, c in enumerate(commits)}  # newest first
    assert by_order[0]["settled"] >= 1  # the ignored twin is settled by its inline comment, never a candidate
    assert by_order[1]["changed"] == 0  # docs only: nothing analysed changed
    assert by_order[3]["changed"] == 0  # the root has no parent to compare with
    rows = replay["read"](out / "replay.jsonl")
    twin = [r for r in rows if r["new"]["name"] == "preview_caption_text"]
    assert twin and twin[0]["existing"]["name"] == "shorten_text" and "baseline" in replay["sources"](twin[0])
    assert all("tests/" not in r["new"]["path"] and "label_text" != r["new"]["name"] for r in rows)
    assert meta["behaviour_floor"] == json.loads((out / "replay.json").read_text())["behaviour_floor"]
    # Resumable: a second run replays nothing again.
    replay["replay"](history.root, "HEAD", 10, out)
    assert len(replay["read"](out / "commits.jsonl")) == 4 and len(replay["read"](out / "replay.jsonl")) == len(rows)


def test_replay_honours_extra_exclusions_and_a_fixed_behaviour_floor(replay, history, tmp_path) -> None:
    out = tmp_path / "out"
    meta = replay["replay"](history.root, "HEAD", 10, out, exclude=["src/widgets/*"], behaviour_floor=0.75)
    assert meta["behaviour_floor"] == 0.75
    assert all(r["new"]["path"] != "src/widgets/caption.py" for r in replay["read"](out / "replay.jsonl"))


def test_replay_refuses_a_worktree_with_tracked_changes(replay, history, tmp_path) -> None:
    (history.root / "src/text.py").write_text("changed = 1\n")
    with pytest.raises(ValueError, match="tracked changes"):
        replay["replay"](history.root, "HEAD", 10, tmp_path / "out")


def gold_file(path: Path, rows: list[dict]) -> Path:
    first = rows[0]
    pair = GoldPair(new=GoldFunction(id=Function.model_validate(first["new"]).qualname, code=""),
                    existing=GoldFunction(id=Function.model_validate(first["existing"]).qualname, code=""),
                    label="duplicate")
    path.write_text(pair.model_dump_json() + "\n")
    return path


def test_sample_weights_each_stratum_back_to_its_population_and_skips_labelled_pairs(replay, history, tmp_path) -> None:
    out = tmp_path / "out"
    replay["replay"](history.root, "HEAD", 10, out)
    rows = replay["read"](out / "replay.jsonl")
    gold = gold_file(tmp_path / "gold.jsonl", rows)
    labelled = replay["pair_key"](Function.model_validate(rows[0]["new"]).qualname,
                                  Function.model_validate(rows[0]["existing"]).qualname)
    sizes = {"baseline": 1, "k5": 1, "floor": 1, "behaviour": 1}
    first = replay["sample"](out, [gold], sizes=sizes)
    population = json.loads((out / "population.json").read_text())
    assert first == replay["sample"](out, [gold], sizes=sizes)  # reproducible
    assert labelled not in {row["key"] for row in first}
    for row in first:
        assert row["weight"] == population[row["stratum"]] / sum(1 for r in first if r["stratum"] == row["stratum"])
        assert replay["stratum"](set(row["sources"])) == row["stratum"]
    assert sorted(row["id"] for row in first) == list(range(1, len(first) + 1))


def openrouter(answers: dict[str, list[object]], seen: list[dict]) -> httpx.MockTransport:
    """A stand-in OpenRouter: each model answers from its list in turn; an int is an HTTP status."""
    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        script = answers[body["model"]]
        answer = script.pop(0) if len(script) > 1 else script[0]
        if isinstance(answer, int):
            return httpx.Response(answer)
        return httpx.Response(200, json={"choices": [{"message": {"content": answer}}], "usage": {"cost": 0.01}})
    return httpx.MockTransport(handle)


def sampled(replay, history, tmp_path) -> Path:
    out = tmp_path / "out"
    replay["replay"](history.root, "HEAD", 10, out)
    replay["sample"](out, sizes={"baseline": 2, "k5": 2, "floor": 2, "behaviour": 2})
    return out


def test_labelling_is_blind_majority_voted_resumable_and_stops_at_the_budget(replay, history, tmp_path) -> None:
    out = sampled(replay, history, tmp_path)
    rows = json.loads((out / "sample.json").read_text())
    consolidate = 'Reasoning first. {"label": "consolidate", "concept": "shorten text"}'
    seen: list[dict] = []
    answers = {"a": [consolidate], "b": [500, '{"label": "SEPARATE"}'], "c": ["no json here"]}
    result = replay["label"](out, "key", budget=0.001, models=("a", "b", "c"), workers=2,
                             transport=openrouter(answers, seen))
    assert result["spent"] >= 0.001 and result["unanswered"] > 0  # stopped after the first batch
    prompts = [m["content"] for body in seen for m in body["messages"]]
    assert all("stratum" not in text and "similarity" not in text and "Function A:" in text for text in prompts)
    result = replay["label"](out, "key", budget=100, models=("a", "b", "c"), workers=2, transport=openrouter(answers, seen))
    assert result["unanswered"] == len(rows)  # model c never gives a usable answer; nothing else is left
    decided = replay["consensus"](out, ("a", "b", "c"))
    assert decided == {}  # a and b split, c is silent: no majority
    assert all(v["positive"] and v["unanimous"] for v in replay["consensus"](out, ("a",)).values())
    calls = len(seen)
    replay["label"](out, "key", budget=100, models=("a",), transport=openrouter(answers, seen))
    assert len(seen) == calls  # answered pairs are never asked again


def test_consensus_needs_a_strict_majority(replay, tmp_path) -> None:
    out = tmp_path
    lines = [{"id": 1, "model": m, "answer": {"label": label}} for m, label in
             (("a", "CONSOLIDATE"), ("b", "CONSOLIDATE"), ("c", "PATTERN"))]
    lines += [{"id": 2, "model": m, "answer": {"label": label}} for m, label in (("a", "SEPARATE"), ("b", "PATTERN"))]
    replay["append"](out / "labels.jsonl", lines)
    decided = replay["consensus"](out, ("a", "b", "c"))
    assert decided[1] == {"positive": True, "unanimous": False, "votes": {"a": "CONSOLIDATE", "b": "CONSOLIDATE", "c": "PATTERN"}}
    assert decided[2]["positive"] is False and decided[2]["unanimous"]


def test_openrouter_judge_asks_with_the_product_prompt(replay) -> None:
    seen: list[dict] = []
    transport = openrouter({"anthropic/claude-sonnet-5.5": ['{"label": "duplicate", "score": 0.9}']}, seen)
    judge = replay["OpenRouterJudge"](api_key="key", transport=transport)
    pair = Candidate(new=Function(path="a.py", name="f", line=1, end_line=2, code="def f():\n    return 1"),
                     existing=Function(path="b.py", name="g", line=1, end_line=2, code="def g():\n    return 1"),
                     similarity=0.0)
    verdict = judge.judge([pair], Settings())[0]
    assert verdict.score == 0.9 and "a.py::f" in seen[0]["messages"][0]["content"]


class Fixed:
    """A judge that scores every pair the same; `fail_first` raises on its first batch, as a lost connection would."""

    version = "1"

    def __init__(self, name: str, score: float, fail_first: bool = False) -> None:
        self.name, self.score, self.fail_first = name, score, fail_first

    def judge(self, candidates: list[Candidate], settings: Settings) -> list[Verdict]:
        if self.fail_first:
            self.fail_first = False
            raise httpx.ConnectError("lost")
        return [Verdict(label="duplicate", score=self.score, judge=self.name) for _ in candidates]


def test_judging_records_each_judge_once_per_pair_and_resumes_after_failures(replay, history, tmp_path) -> None:
    out = sampled(replay, history, tmp_path)
    rows = json.loads((out / "sample.json").read_text())
    replay["judge"](out, {"jev": lambda: Fixed("jev", 0.7), "sonnet": lambda: Fixed("sonnet", 0.95, fail_first=True)})
    verdicts = replay["read"](out / "verdicts.jsonl")
    assert sum(v["judge"] == "jev" for v in verdicts) == len(rows)
    assert sum(v["judge"] == "sonnet" for v in verdicts) == max(len(rows) - 8, 0)
    replay["judge"](out, {"jev": lambda: Fixed("jev", 0.1), "sonnet": lambda: Fixed("sonnet", 0.95)})
    verdicts = replay["read"](out / "verdicts.jsonl")
    assert sum(v["judge"] == "sonnet" for v in verdicts) == len(rows)
    assert all(v["score"] == 0.7 for v in verdicts if v["judge"] == "jev")  # never re-judged


@pytest.mark.parametrize("scores,preset,expected", [
    ({"jev": 0.85}, "jev", (True, True)),
    ({"jev": 0.75}, "jev", (False, False)),
    ({"jev": 0.75, "sonnet": 0.65}, "jev+sonnet", (True, False)),  # in the band: Sonnet decides
    ({"jev": 0.75, "sonnet": 0.9}, "jev+sonnet", (True, True)),
    ({"jev": 0.95, "sonnet": 0.1}, "jev+sonnet", (True, True)),  # above the band: Jev's answer stands
    ({"jev": 0.3, "sonnet": 0.9}, "jev+sonnet", (False, False)),  # below the band: never escalated
    ({"jev": 0.75}, "jev+sonnet", (True, True)),  # no second opinion: Jev's answer stands
    ({}, "jev+sonnet", (False, False)),
])
def test_presets_report_and_fail_at_their_measured_thresholds(replay, scores, preset, expected) -> None:
    assert replay["reported"](scores, preset) == expected


def test_report_weights_labelled_and_judged_pairs_back_to_the_population(replay, history, tmp_path) -> None:
    out = sampled(replay, history, tmp_path)
    rows = json.loads((out / "sample.json").read_text())
    replay["append"](out / "labels.jsonl", [{"id": r["id"], "model": m, "answer": {"label": "CONSOLIDATE" if r["id"] % 2 else "SEPARATE"}}
                                            for r in rows for m in replay["LABELLERS"]])
    replay["judge"](out, {"jev": lambda: Fixed("jev", 0.85)})
    result = replay["report"]([out])[out.name]
    assert result["commits"] == 4 and result["labelled"] == len(rows) and result["unanimous"] == len(rows)
    aggressive = result["options"]["aggressive"]
    population = json.loads((out / "population.json").read_text())
    assert aggressive["pairs"] == pytest.approx(sum(population[s] for s in ("baseline", "k5", "floor", "behaviour")
                                                    if any(r["stratum"] == s for r in rows)), abs=0.2)
    jev = aggressive["jev"]
    assert jev["reported_true"] + jev["reported_false"] == pytest.approx(aggressive["pairs"], abs=0.2)  # 0.85 reports all
    assert jev["reported_true"] == pytest.approx(aggressive["positives"], abs=0.2)
    baseline = result["options"]["baseline"]
    assert result["options"]["rank1"]["pairs"] <= result["options"]["rank2"]["pairs"] <= baseline["pairs"]


def test_cli_dispatches_each_step(replay, history, tmp_path, monkeypatch, capsys) -> None:
    out = tmp_path / "out"
    script = str(SCRIPTS / "replay_presets.py")
    monkeypatch.setattr(sys, "argv", ["replay", "replay", "--root", str(history.root), "--ref", "HEAD", "--out", str(out)])
    runpy.run_path(script, run_name="__main__")
    monkeypatch.setattr(sys, "argv", ["replay", "sample", "--out", str(out)])
    runpy.run_path(script, run_name="__main__")
    assert (out / "sample.json").exists()
    monkeypatch.setenv("OPENROUTER_API_KEY", "key")
    monkeypatch.setenv("TYPESAFE_AI_API_KEY", "key")
    monkeypatch.setattr(sys, "argv", ["replay", "label", "--out", str(out), "--budget", "0"])
    runpy.run_path(script, run_name="__main__")
    assert json.loads(capsys.readouterr().out)["spent"] == 0
    monkeypatch.setattr(sys, "argv", ["replay", "judge", "--out", str(out)])
    with patch.object(httpx.Client, "post", side_effect=httpx.ConnectError("offline")):
        runpy.run_path(script, run_name="__main__")
    assert replay["read"](out / "verdicts.jsonl") == []  # every batch failed, so nothing is recorded
    monkeypatch.setattr(sys, "argv", ["replay", "report", str(out)])
    runpy.run_path(script, run_name="__main__")
    assert json.loads(capsys.readouterr().out)[out.name]["commits"] == 4


@pytest.mark.parametrize("text,expected", [
    ('{"label": "pattern"}', "PATTERN"),
    ('Thinking {not json} then {"note": 1} then {"label": "Consolidate", "concept": "x"}', "CONSOLIDATE"),
    ('{"label": "maybe"}', None),
    ("no answer", None),
])
def test_a_label_is_the_first_object_with_a_known_label(replay, text, expected) -> None:
    answer = replay["parse_label"](text)
    assert (answer or {}).get("label") == expected
