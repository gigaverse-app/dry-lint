"""Replay recent commits to measure retrieval presets at pull request time. Outputs contain code: keep them private.

    uv run python scripts/replay_presets.py replay --root WORKTREE --ref origin/main --commits 150 --out DIR
    uv run python scripts/replay_presets.py sample --out DIR [--gold labelled.jsonl ...]
    uv run python scripts/replay_presets.py label --out DIR --budget 40     # three vendors' models, majority vote
    uv run python scripts/replay_presets.py judge --out DIR                 # Jev and Claude Sonnet 5.5, every sampled pair
    uv run python scripts/replay_presets.py report DIR [DIR ...]

Each first-parent commit is replayed against its parent with the repository's own settings, as `dry-lint check`
would run on that pull request. For every changed function the trial records the production candidates (three
neighbours above the TF-IDF floors) and what wider retrieval would add: neighbours four and five, a lower floor, and
one slot from the behaviour-only channel. Production rules settle pairs exactly as in `check`.
"""

import argparse
import fnmatch
import json
import os
import random
import re
import time
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from channel_trial import Floored, behaviour_only, calibrated_floor, experimental, nearest, share_with_neighbour

from dry_lint.bench import load_gold
from dry_lint.comparers import TfidfComparer
from dry_lint.detector import Detector, changed_lines, touched, why_skipped
from dry_lint.functions import extractor_for, repository_functions
from dry_lint.git import git
from dry_lint.judges.http import HttpJudge
from dry_lint.judges.jev import JevJudge
from dry_lint.models import Candidate, Function, pair_key
from dry_lint.plugins import Judge, load
from dry_lint.settings import Settings

WIDE = 5  # neighbours the wide retrieval keeps
LOW_FLOOR, LOW_FLOOR_SMALL = 0.4, 0.2  # the wide retrieval's floors, against production's 0.5 and 0.3
SOURCES = ("baseline", "k5", "floor", "behaviour")  # sampling priority: a pair belongs to the first that proposes it
SAMPLE = {"baseline": 40, "k5": 20, "floor": 20, "behaviour": 20}
LABELLERS = ("anthropic/claude-opus-5.5", "openai/gpt-5.5", "google/gemini-3.1-pro-preview")
OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"
GUIDELINE = """You label pairs of functions from one codebase for a benchmark of duplicated concepts (DRY).

The test: does reconciling the two reveal ONE real concept with legitimate variations (it should have one
implementation, parameterized where they differ), or TWO different concepts that happen to share structure or APIs?

- CONSOLIDATE: one concept. Includes identical copies, renamed copies, independent re-implementations of the same
  concept, and variants whose differences should be parameters, even when the details differ or have drifted.
- SEPARATE: two different concepts that coincidentally look alike; or one calls the other; or the client and server
  ends of one endpoint; or an interface or stub and its implementation.
- PATTERN: deliberate instances of one template (one router, handler, command, fixture per resource) where a shared
  helper would not clearly be simpler.

Answer with one JSON object and nothing else:
{"label": "CONSOLIDATE" | "SEPARATE" | "PATTERN", "concept": "at most six words",
 "variation": "identical" | "parameterizable" | "drifted" | "n/a", "owner": "A" | "B" | "new shared helper" | "n/a"}
"""


def sources(row: dict) -> set[str]:
    """Which retrieval options propose this pair for this changed function."""
    found = set()
    rank, similarity, floor = row.get("rank"), row.get("similarity", 0.0), row.get("floor", 1.0)
    if rank is not None and rank <= 3 and similarity >= floor:
        found.add("baseline")
    if rank is not None and rank <= WIDE and similarity >= floor:
        found.add("k5")
    if rank is not None and rank <= 3:
        found.add("floor")  # every recorded neighbour is above the low floor
    if row.get("behaviour"):
        found.add("behaviour")
    return found


def stratum(options: set[str]) -> str:
    return next(source for source in SOURCES if source in options)


def append(path: Path, rows: list[dict]) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.writelines(json.dumps(row) + "\n" for row in rows)


def read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line] if path.exists() else []


def replay(root: Path, ref: str, commits: int, out: Path, exclude: list[str] = (), behaviour_floor: float | None = None) -> dict:
    """Candidates per changed function for the last `commits` first-parent commits; resumable."""
    out.mkdir(parents=True, exist_ok=True)
    if git(root, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError(f"{root} has tracked changes; replay checks out each commit")
    done = {row["commit"] for row in read(out / "commits.jsonl")}
    meta_path = out / "replay.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {"ref": git(root, "rev-parse", ref), "exclude": list(exclude)}
    history = git(root, "rev-list", "--first-parent", f"--max-count={commits}", meta["ref"]).split()
    for commit in history:
        if commit in done:
            continue
        start = time.perf_counter()
        git(root, "checkout", "-q", "--detach", commit)
        parents = git(root, "rev-list", "--parents", "-n", "1", commit).split()[1:]
        record = {"commit": commit, "changed": 0, "candidates": 0, "settled": 0}
        settings = Settings.load(root)
        settings = settings.model_copy(update={"exclude": [*settings.exclude, *meta["exclude"]]})
        extractors = [load("extractors", choice) for choice in settings.extractors]
        lines = changed_lines(root, base=parents[0]) if parents else {}
        lines = {path: changed for path, changed in lines.items() if analysed(path, settings, extractors)}
        rows: list[dict] = []
        if lines and settings.comparer.use == "tfidf":
            functions = repository_functions(root, settings.include, settings.exclude, extractors)
            changed = touched(functions, lines)
            record["changed"] = len(changed)
            if changed:
                if "behaviour_floor" not in meta:
                    meta["behaviour_floor"] = behaviour_floor if behaviour_floor is not None else calibrate(
                        functions, settings, extractors)
                    meta_path.write_text(json.dumps(meta, indent=2))
                rows = candidates(functions, changed, settings, extractors, meta["behaviour_floor"], record)
                for row in rows:
                    row["commit"] = commit
        append(out / "replay.jsonl", rows)
        append(out / "commits.jsonl", [{**record, "seconds": round(time.perf_counter() - start, 2)}])
    meta_path.write_text(json.dumps(meta, indent=2))
    return meta


def analysed(path: str, settings: Settings, extractors: list) -> bool:
    """Whether `check` would read this file: included, not excluded, and some extractor's language."""
    return (any(fnmatch.fnmatch(path, glob) for glob in settings.include)
            and not any(fnmatch.fnmatch(path, glob) for glob in settings.exclude)
            and extractor_for(path, extractors) is not None)


def production(settings: Settings) -> TfidfComparer:
    return TfidfComparer(**settings.comparer.options())


def calibrate(functions: list[Function], settings: Settings, extractors: list) -> float:
    """The behaviour channel's floor: as many functions keep a neighbour as with production TF-IDF (label-free)."""
    tfidf = Detector(functions, settings.model_copy(update={"neighbours": 1}), production(settings), extractors)
    behaviour = Detector([f.model_copy(update={"tokens": behaviour_only(f.tokens)}) for f in functions],
                         settings.model_copy(update={"neighbours": 1}), Floored(TfidfComparer(0.0, 0.0)), extractors)
    return calibrated_floor(nearest(behaviour), share_with_neighbour(nearest(tfidf)))


def candidates(functions: list[Function], changed: list[Function], settings: Settings, extractors: list,
               behaviour_floor: float, record: dict) -> list[dict]:
    floors = production(settings)
    options = settings.comparer.options()
    wide = Detector(functions, settings.model_copy(update={"neighbours": WIDE}),
                    TfidfComparer(**{**options, "min_similarity": LOW_FLOOR, "min_similarity_small": LOW_FLOOR_SMALL}),
                    extractors)
    behaviour = Detector([f.model_copy(update={"tokens": behaviour_only(f.tokens)}) for f in functions],
                         settings.model_copy(update={"neighbours": 1}),
                         Floored(experimental(TfidfComparer(0.0, 0.0), "behaviour"), behaviour_floor), extractors)
    by_name = {f.qualname: f for f in behaviour.functions}
    found: dict[tuple[str, str], dict] = {}
    for function in changed:
        proposals = [(other, similarity, rank, False) for rank, (other, similarity) in enumerate(wide.neighbours(function), 1)]
        proposals += [(other, similarity, None, True) for other, similarity in behaviour.neighbours(by_name[function.qualname])]
        for other, similarity, rank, from_behaviour in proposals:
            existing = wide.functions[wide.position[other.qualname]]
            if why_skipped(function, existing, settings) is not None:
                record["settled"] += 1
                continue
            row = found.setdefault((function.qualname, existing.qualname), {
                "new": function.model_dump(), "existing": existing.model_dump(), "floor": floors.floor(function)})
            if from_behaviour:
                row["behaviour"], row["behaviour_similarity"] = True, round(similarity, 4)
            else:
                row["rank"], row["similarity"] = rank, round(similarity, 4)
    record["candidates"] = len(found)
    return list(found.values())


def sample(out: Path, gold_paths: list[Path] = (), seed: int = 20261107, sizes: dict[str, int] = SAMPLE) -> list[dict]:
    """A stratified sample of distinct pairs, weighted back to the replayed population; none already labelled."""
    labelled = {pair_key(p.new.id, p.existing.id) for path in gold_paths for p in load_gold(path)}
    pairs: dict[str, dict] = {}
    for row in read(out / "replay.jsonl"):
        key = pair_key(Function.model_validate(row["new"]).qualname, Function.model_validate(row["existing"]).qualname)
        entry = pairs.setdefault(key, {"key": key, "row": row, "sources": set(), "commits": set(), "rank_min": None})
        proposed = sources(row)
        entry["sources"] |= proposed
        entry["commits"].add(row["commit"])
        if "baseline" in proposed:
            entry["rank_min"] = min(row["rank"], entry["rank_min"] or row["rank"])
    strata: dict[str, list[dict]] = defaultdict(list)
    for entry in pairs.values():
        if entry["sources"]:
            strata[stratum(entry["sources"])].append(entry)
    rng = random.Random(seed)
    chosen = []
    for name in SOURCES:
        pool = sorted((e for e in strata[name] if e["key"] not in labelled), key=lambda e: e["key"])
        picked = rng.sample(pool, min(sizes.get(name, 0), len(pool)))
        weight = len(strata[name]) / len(picked) if picked else 0.0
        chosen += [{"key": e["key"], "stratum": name, "weight": weight, "sources": sorted(e["sources"]), "rank_min": e["rank_min"],
                    "occurrences": len(e["commits"]), "new": e["row"]["new"], "existing": e["row"]["existing"]}
                   for e in picked]
    rng.shuffle(chosen)
    for number, row in enumerate(chosen, 1):
        row["id"] = number
    (out / "sample.json").write_text(json.dumps(chosen, indent=2), encoding="utf-8")
    (out / "population.json").write_text(json.dumps(
        {name: len(strata[name]) for name in SOURCES} | {"pairs": len(pairs)}, indent=2), encoding="utf-8")
    return chosen


def qualified(side: dict) -> str:
    return f"{side['owner'] + '.' if side.get('owner') else ''}{side['name']}"


def label_prompt(row: dict) -> str:
    sides = [f"Function {letter}: {side['path']}::{qualified(side)}\n```\n{side['code']}\n```"
             for letter, side in (("A", row["new"]), ("B", row["existing"]))]
    return GUIDELINE + "\n" + "\n\n".join(sides)


def parse_label(text: str) -> dict | None:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            answer, _ = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(answer, dict) and str(answer.get("label", "")).upper() in {"CONSOLIDATE", "SEPARATE", "PATTERN"}:
            return {**answer, "label": answer["label"].upper()}
    return None


def label(out: Path, api_key: str, budget: float, models: tuple[str, ...] = LABELLERS, workers: int = 6,
          transport: httpx.BaseTransport | None = None) -> dict:
    """Every sampled pair from every labeller, blind to source and score; resumable, stops at `budget` USD."""
    rows = json.loads((out / "sample.json").read_text())
    path = out / "labels.jsonl"
    done = {(r["id"], r["model"]) for r in read(path) if r.get("answer")}
    spent = sum(r.get("cost", 0.0) for r in read(path))
    todo = [(row, model) for row in rows for model in models if (row["id"], model) not in done]

    def ask(client: httpx.Client, row: dict, model: str) -> dict:
        body = {"model": model, "messages": [{"role": "user", "content": label_prompt(row)}], "max_tokens": 6000,
                "usage": {"include": True}}
        for _ in range(3):
            try:
                response = client.post(OPENROUTER, json=body, headers={"Authorization": f"Bearer {api_key}"})
                response.raise_for_status()
                data = response.json()
                text = data["choices"][0]["message"].get("content") or ""
                answer = parse_label(text)
                cost = float(data.get("usage", {}).get("cost", 0.0))
                if answer:
                    return {"id": row["id"], "model": model, "answer": answer, "cost": cost}
            except (httpx.HTTPError, KeyError, IndexError, ValueError):
                continue
        return {"id": row["id"], "model": model, "answer": None, "cost": 0.0}

    with httpx.Client(timeout=300, transport=transport) as client, ThreadPoolExecutor(workers) as pool:
        for start in range(0, len(todo), workers):
            if spent >= budget:
                break
            batch = list(pool.map(lambda job: ask(client, *job), todo[start:start + workers]))
            spent += sum(r["cost"] for r in batch)
            append(path, batch)
    answered = {(r["id"], r["model"]) for r in read(path) if r.get("answer")}
    return {"spent": round(spent, 4), "unanswered": len(rows) * len(models) - len(answered)}


def consensus(out: Path, models: tuple[str, ...] = LABELLERS) -> dict[int, dict]:
    """The majority over labellers that answered; a pair with no majority stays unresolved and is left out."""
    answers: dict[int, dict[str, str]] = defaultdict(dict)
    for row in read(out / "labels.jsonl"):
        if row.get("answer") and row["model"] in models:
            answers[row["id"]][row["model"]] = row["answer"]["label"]
    decided = {}
    for pair, given in answers.items():
        votes = [label == "CONSOLIDATE" for label in given.values()]
        if votes.count(True) * 2 > len(votes):
            decided[pair] = {"positive": True, "unanimous": all(votes), "votes": given}
        elif votes.count(False) * 2 > len(votes):
            decided[pair] = {"positive": False, "unanimous": not any(votes), "votes": given}
    return decided


class OpenRouterJudge(HttpJudge):
    """The product's DRY prompt to a model behind OpenRouter: Claude Sonnet 5.5 here, as in the `sonnet` presets."""

    name = "openrouter"
    key_variable = "OPENROUTER_API_KEY"
    default_model = "anthropic/claude-sonnet-5.5"

    def request(self, text: str) -> tuple[str, dict, dict]:
        return OPENROUTER, {"Authorization": f"Bearer {self.api_key}"}, {
            "model": self.model, "messages": [{"role": "user", "content": text}], "max_tokens": 8000}

    def answer(self, body: dict) -> str:
        return body["choices"][0]["message"].get("content") or ""


def candidate(row: dict) -> Candidate:
    return Candidate(new=Function.model_validate(row["new"]), existing=Function.model_validate(row["existing"]), similarity=0.0)


def judge(out: Path, judges: dict[str, Callable[[], Judge]]) -> None:
    """Every sampled pair through each judge, in small batches so one failure loses little; resumable."""
    rows = json.loads((out / "sample.json").read_text())
    path = out / "verdicts.jsonl"
    done = {(r["id"], r["judge"]) for r in read(path)}
    for name, factory in judges.items():
        instance = factory()
        todo = [row for row in rows if (row["id"], name) not in done]
        for start in range(0, len(todo), 8):
            batch = todo[start:start + 8]
            try:
                verdicts = instance.judge([candidate(row) for row in batch], Settings())
            except (httpx.HTTPError, ValueError):
                continue
            append(path, [{"id": row["id"], "judge": name, "label": v.label, "score": v.score,
                           "behaves_differently": v.behaves_differently} for row, v in zip(batch, verdicts)])


def reported(verdicts: dict[str, dict], preset: str) -> tuple[bool, bool]:
    """
    (reported, fails) under a judging preset (presets.py thresholds), as the report decides: a verdict counts when
    its label is not "separate" and its score reaches the threshold. Sonnet answers for Jev scores in [0.5, 0.91).
    """
    jev, sonnet = verdicts.get("jev"), verdicts.get("sonnet")
    chosen = jev
    if preset == "jev+sonnet" and jev is not None and 0.5 <= jev["score"] < 0.91 and sonnet is not None:
        chosen = sonnet
    report_at, fail_at = (0.8, 0.8) if preset == "jev" else (0.6, 0.7)
    counts = chosen is not None and chosen.get("label", "duplicate") != "separate"
    return counts and chosen["score"] >= report_at, counts and chosen["score"] >= fail_at


OPTIONS = ("baseline", "k5", "floor", "behaviour", "aggressive", "rank1", "rank2")
PRESETS = ("jev", "jev+sonnet")


def proposes(row: dict, option: str) -> bool:
    """Production's pairs, the pairs a wider option adds to them, all of them, or production's best one or two."""
    found = set(row["sources"])
    if option == "aggressive":
        return bool(found)
    if option in ("rank1", "rank2"):
        return "baseline" in found and row["rank_min"] <= int(option[-1])
    return option in found if option == "baseline" else (option in found and "baseline" not in found)


def totals(rows: list[dict], labels: dict[int, dict], scores: dict[int, dict[str, dict]], option: str) -> dict[str, float]:
    """Weighted totals over labelled rows: pairs, real duplicates, and what each preset reports or fails on."""
    found: dict[str, float] = defaultdict(float)
    for row in rows:
        if not proposes(row, option):
            continue
        positive = labels[row["id"]]["positive"]
        kind = "true" if positive else "false"
        found["pairs"] += row["weight"]
        found["positives"] += row["weight"] * positive
        for preset in PRESETS:
            if "jev" in scores[row["id"]]:
                shown, fails = reported(scores[row["id"]], preset)
                found[f"{preset} reported_{kind}"] += row["weight"] * shown
                found[f"{preset} failing_{kind}"] += row["weight"] * fails
    return found


def resamples(rows: list[dict], rng: random.Random, rounds: int) -> list[list[dict]]:
    """Stratified bootstrap: each stratum's labelled rows drawn again with replacement, keeping their weights."""
    strata: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        strata[row["stratum"]].append(row)
    return [[rng.choice(group) for group in strata.values() for _ in group] for _ in range(rounds)]


def summarise(point: dict[str, float], draws: list[dict[str, float]]) -> dict[str, list[float]]:
    """Each total as [estimate, 5th percentile, 95th percentile], plus each preset's reported precision."""
    def ratio(values: dict[str, float], preset: str) -> float:
        shown = values.get(f"{preset} reported_true", 0.0) + values.get(f"{preset} reported_false", 0.0)
        return values.get(f"{preset} reported_true", 0.0) / shown if shown else float("nan")

    names = sorted({name for values in [point, *draws] for name in values})
    series = {name: (point.get(name, 0.0), [values.get(name, 0.0) for values in draws]) for name in names}
    series |= {f"{preset} precision": (ratio(point, preset), [ratio(values, preset) for values in draws]) for preset in PRESETS}
    summary = {}
    for name, (estimate, values) in series.items():
        ordered = sorted(v for v in values if v == v)
        low, high = (ordered[int(0.05 * len(ordered))], ordered[int(0.95 * len(ordered)) - 1]) if ordered else (estimate,) * 2
        summary[name] = [round(estimate, 3), round(low, 3), round(high, 3)]
    return summary


def report(outs: list[Path], rounds: int = 1000, seed: int = 20261107) -> dict:
    """Weighted estimates with 90% intervals per repository and pooled: real duplicates, findings and cost per option."""
    results, pooled_points, pooled_draws = {}, defaultdict(lambda: defaultdict(float)), defaultdict(list)
    for out in outs:
        commits = read(out / "commits.jsonl")
        population = json.loads((out / "population.json").read_text())
        labels = consensus(out)
        rows = [row for row in json.loads((out / "sample.json").read_text()) if row["id"] in labels]
        scores: dict[int, dict[str, dict]] = defaultdict(dict)
        for verdict in read(out / "verdicts.jsonl"):
            scores[verdict["id"]][verdict["judge"]] = verdict
        draws = resamples(rows, random.Random(seed), rounds)
        options = {}
        for option in OPTIONS:
            point = totals(rows, labels, scores, option)
            drawn = [totals(draw, labels, scores, option) for draw in draws]
            options[option] = {"labelled": sum(proposes(r, option) for r in rows),
                               "positive_labels": sum(proposes(r, option) and labels[r["id"]]["positive"] for r in rows),
                               **summarise(point, drawn)}
            for name, value in point.items():
                pooled_points[option][name] += value
            if not pooled_draws[option]:
                pooled_draws[option] = [defaultdict(float) for _ in range(rounds)]
            for into, values in zip(pooled_draws[option], drawn):
                for name, value in values.items():
                    into[name] += value
        results[out.name] = {"commits": len(commits), "with_changes": sum(1 for c in commits if c["changed"]),
                             "changed_functions": sum(c["changed"] for c in commits),
                             "settled_by_rule": sum(c["settled"] for c in commits), "population": population,
                             "labelled": len(labels), "unanimous": sum(label["unanimous"] for label in labels.values()),
                             "options": options}
    results["all"] = {"commits": sum(r["commits"] for r in results.values()),
                      "options": {option: summarise(pooled_points[option], pooled_draws[option]) for option in OPTIONS}}
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("replay")
    run.add_argument("--root", type=Path, required=True)
    run.add_argument("--ref", default="origin/HEAD")
    run.add_argument("--commits", type=int, default=150)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--exclude", action="append", default=[])
    draw = commands.add_parser("sample")
    draw.add_argument("--out", type=Path, required=True)
    draw.add_argument("--gold", type=Path, action="append", default=[])
    labelling = commands.add_parser("label")
    labelling.add_argument("--out", type=Path, required=True)
    labelling.add_argument("--budget", type=float, required=True)
    judging = commands.add_parser("judge")
    judging.add_argument("--out", type=Path, required=True)
    summary = commands.add_parser("report")
    summary.add_argument("outs", type=Path, nargs="+")
    args = parser.parse_args()
    if args.command == "replay":
        replay(args.root.resolve(), args.ref, args.commits, args.out, args.exclude)
    elif args.command == "sample":
        sample(args.out, args.gold)
    elif args.command == "label":
        print(json.dumps(label(args.out, os.environ["OPENROUTER_API_KEY"], args.budget)))
    elif args.command == "judge":
        judge(args.out, {"jev": JevJudge, "sonnet": OpenRouterJudge})
    else:
        print(json.dumps(report(args.outs), indent=2))


if __name__ == "__main__":
    main()
