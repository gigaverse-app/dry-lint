"""
`dry-lint bench`: measure a judge or a comparer on a gold set, so every plugin is compared on the same pairs.

The gold set is JSON lines (`gold.jsonl`), one labelled pair per line. Each line carries both functions' code as it
was when labelled, so the judge benchmark still runs after the repository has moved on. `weight` projects a
stratified sample back to its population (each stratum's size over its sample size), and defaults to 1.
Borderline pairs are kept in the file and left out of the numbers.
"""

import math
import random
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel, Field

from dry_lint.costs import Ledger
from dry_lint.detector import Detector
from dry_lint.judging import decide, judges_name
from dry_lint.models import Candidate, Function, Verdict
from dry_lint.plugins import Extractor, Judge
from dry_lint.settings import Budget, Settings

BANDS = (0.0, 0.1, 0.3, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01)
Row = TypeVar("Row")
Statistic = TypeVar("Statistic")


class GoldFunction(BaseModel):
    id: str = Field(description="Qualified name, path::Class.name.")
    code: str


class GoldPair(BaseModel):
    new: GoldFunction
    existing: GoldFunction
    label: Literal["duplicate", "separate", "borderline"]
    drifted: bool | None = None
    owner: str | None = None
    weight: float = 1.0
    stratum: str | None = Field(default=None, description="The sampling stratum, for confidence intervals.")


def load_gold(path: Path) -> list[GoldPair]:
    return [GoldPair.model_validate_json(line) for line in path.read_text().splitlines() if line.strip()]


def as_function(side: GoldFunction, extractor: Extractor) -> Function:
    """
    The gold code as a function. Code that does not parse (a sample truncated at labelling time, say) is kept as
    text: a judge reads the text, so the pair is still measured.
    """
    path, _, qualified = side.id.partition("::")
    owner, _, name = qualified.rpartition(".")
    found = extractor.functions(path, textwrap.dedent(side.code).strip() + "\n")
    if found:
        return found[0].model_copy(update={"name": name, "owner": owner or None})
    code = textwrap.dedent(side.code).strip()
    return Function(path=path, name=name, owner=owner or None, line=1, end_line=code.count("\n") + 1, code=code)


def auc(scored: list[tuple[float, bool, float]]) -> float:
    """Weighted probability that a duplicate outscores a separate pair; ties count half."""
    positives = [(s, w) for s, dup, w in scored if dup]
    negatives = [(s, w) for s, dup, w in scored if not dup]
    total = sum(wp * wn for _, wp in positives for _, wn in negatives)
    wins = sum(wp * wn * (1.0 if sp > sn else 0.5 if sp == sn else 0.0)
               for sp, wp in positives for sn, wn in negatives)
    return wins / total if total else float("nan")


def precision_recall(rows: list[tuple[str, bool, float, bool]]) -> tuple[float, float]:
    flagged = sum(w for _, _, w, r in rows if r)
    hits = sum(w for _, d, w, r in rows if r and d)
    duplicates = sum(w for _, d, w, _ in rows if d)
    return (hits / flagged if flagged else 0.0), (hits / duplicates if duplicates else 0.0)


def resampled(rows: list[Row], stratum: Callable[[Row], str], statistic: Callable[[list[Row]], Statistic],
              resamples: int = 1000, seed: int = 7) -> list[Statistic]:
    """
    `statistic` over a stratified bootstrap: each stratum is resampled with replacement and keeps its weights, so the
    spread shows how much a handful of heavily weighted pairs can move the numbers.
    """
    strata: dict[str, list[Row]] = {}
    for row in rows:
        strata.setdefault(stratum(row), []).append(row)
    rng = random.Random(seed)
    return [statistic([rng.choice(members) for members in strata.values() for _ in members]) for _ in range(resamples)]


def spread(values: list[float]) -> tuple[float, float]:
    """The 90% interval of bootstrap values."""
    ordered = sorted(values)
    return ordered[int(0.05 * (len(ordered) - 1))], ordered[int(0.95 * (len(ordered) - 1))]


def intervals(rows: list[tuple[str, bool, float, bool]], resamples: int = 1000,
              seed: int = 7) -> tuple[tuple[float, float], tuple[float, float]]:
    """90% intervals for precision and recall."""
    draws = resampled(rows, lambda row: row[0], precision_recall, resamples, seed) if rows else [(0.0, 0.0)]
    return spread([p for p, _ in draws]), spread([r for _, r in draws])


class Band(BaseModel):
    low: float
    high: float
    duplicates: float
    separate: float


class JudgeBench(BaseModel):
    judge: str
    pairs: int
    duplicates: int
    auc: float | None = Field(description="None when the pairs hold no duplicate, or nothing else.")
    precision: float = Field(description="At report_at.")
    recall: float = Field(description="At report_at.")
    precision_interval: tuple[float, float] = Field(description="90% interval, stratified bootstrap.")
    recall_interval: tuple[float, float] = Field(description="90% interval, stratified bootstrap.")
    recall_at_drop: float = Field(description="Share of duplicates at or above drop_below.")
    fail_at: float = Field(default=0.0, description="The threshold that fails a run, when above report_at.")
    fail_precision: float = 0.0
    fail_recall: float = 0.0
    fail_precision_interval: tuple[float, float] = (0.0, 0.0)
    fail_recall_interval: tuple[float, float] = (0.0, 0.0)
    usd_per_pair: float | None = Field(default=None, description="Estimated judging cost per pair; None if unknown.")
    subscription_calls: int = 0
    bands: list[Band]

    def as_text(self, settings: Settings) -> str:
        p_low, p_high = self.precision_interval
        r_low, r_high = self.recall_interval
        lines = [f"judge {self.judge}: {self.pairs} labelled pairs, {self.duplicates} duplicates",
                 "  AUC " + ("n/a" if self.auc is None else f"{self.auc:.2f}"),
                 f"  at report_at {settings.report_at}: precision {self.precision:.0%} ({p_low:.0%}-{p_high:.0%}), "
                 f"recall {self.recall:.0%} ({r_low:.0%}-{r_high:.0%}); 90% intervals",
                 *([f"  at fail_at {self.fail_at}: precision {self.fail_precision:.0%} "
                    f"({self.fail_precision_interval[0]:.0%}-{self.fail_precision_interval[1]:.0%}), recall "
                    f"{self.fail_recall:.0%} ({self.fail_recall_interval[0]:.0%}-{self.fail_recall_interval[1]:.0%})"]
                   if self.fail_at > settings.report_at else []),
                 "  cost: " + ("unknown" if self.usd_per_pair is None else f"est. ${self.usd_per_pair:.4f} per pair")
                 + (f", {self.subscription_calls} subscription calls" if self.subscription_calls else ""),
                 f"  at drop_below {settings.drop_below}: recall {self.recall_at_drop:.0%}",
                 "  score band    duplicates  separate"]
        lines += [f"  {b.low:.1f}-{min(b.high, 1.0):.1f}    {b.duplicates:10.1f}  {b.separate:8.1f}" for b in self.bands]
        return "\n".join(lines)


def bench_judge(gold: list[GoldPair], judge: Judge, settings: Settings, extractor: Extractor,
                escalation: Judge | None = None) -> JudgeBench:
    """The judging that runs in CI, measured: the judge, and the escalation judge on its band when one is set."""
    labelled = [g for g in gold if g.label != "borderline"]
    candidates = [Candidate(new=as_function(g.new, extractor), existing=as_function(g.existing, extractor), similarity=0.0)
                  for g in labelled]
    unlimited = settings.model_copy(update={"budget": Budget(usd=float("inf"), subscription_calls=10**9)})
    ledger = Ledger(unlimited)
    verdicts = [v for v in decide(candidates, judge, escalation, unlimited, ledger) if v is not None]
    return judge_bench(labelled, verdicts, settings, judges_name(judge, escalation), ledger)


def judge_bench(labelled: list[GoldPair], verdicts: list[Verdict], settings: Settings, judge: str,
                ledger: Ledger | None = None) -> JudgeBench:
    """The numbers for verdicts already given on labelled pairs, in the same order; `ledger` holds what they cost."""
    scored = [(v.score, g.label == "duplicate", g.weight) for g, v in zip(labelled, verdicts)]

    def flags(threshold: float) -> list[bool]:
        """Reported exactly as a report decides it: a duplicate label at or above the threshold."""
        return [v.label != "separate" and v.score >= settings.bar(threshold, v.second_opinion is not None)
                for v in verdicts]

    reported = flags(settings.report_at)

    def weight(condition) -> float:
        return sum(w for score, duplicate, w in scored if condition(score, duplicate))

    duplicates = weight(lambda score, duplicate: duplicate)
    flagged = sum(w for (_, _, w), r in zip(scored, reported) if r)
    hits = sum(w for (_, d, w), r in zip(scored, reported) if r and d)
    kept = weight(lambda score, duplicate: duplicate and score >= settings.drop_below)
    rows = [(g.stratum or str(g.weight), g.label == "duplicate", g.weight, r) for g, r in zip(labelled, reported)]
    precision_interval, recall_interval = intervals(rows)
    fail_at = max(settings.report_at, settings.fail_at)
    fail_rows = [(s, d, w, f) for (s, d, w, _), f in zip(rows, flags(fail_at))]
    fail_precision, fail_recall = precision_recall(fail_rows)
    fail_precision_interval, fail_recall_interval = intervals(fail_rows)
    spend = list(ledger.spend.values()) if ledger else []
    usd = None if not ledger or any(s.usd is None for s in spend) else ledger.usd
    bands = [Band(low=low, high=high,
                  duplicates=weight(lambda s, d, lo=low, hi=high: d and lo <= s < hi),
                  separate=weight(lambda s, d, lo=low, hi=high: not d and lo <= s < hi))
             for low, high in zip(BANDS, BANDS[1:])]  # fmt: skip
    return JudgeBench(judge=judge, pairs=len(labelled), duplicates=sum(1 for g in labelled if g.label == "duplicate"),
                      auc=None if math.isnan(area := auc(scored)) else area, precision=hits / flagged if flagged else 0.0,
                      precision_interval=precision_interval, recall_interval=recall_interval,
                      recall=hits / duplicates if duplicates else 0.0, recall_at_drop=kept / duplicates if duplicates else 0.0,
                      fail_at=fail_at, fail_precision=fail_precision, fail_recall=fail_recall,
                      fail_precision_interval=fail_precision_interval, fail_recall_interval=fail_recall_interval,
                      usd_per_pair=usd / len(labelled) if usd is not None and labelled else None,
                      subscription_calls=sum(s.calls for s in spend if s.subscription),
                      bands=[b for b in bands if b.duplicates or b.separate])


class ComparerBench(BaseModel):
    comparer: str
    neighbours: int
    duplicates: int = Field(description="Gold duplicates whose two functions both exist in the repository.")
    missing: int = Field(description="Gold duplicates with a side no longer in the repository.")
    recall: float = Field(description="Weighted share of duplicates whose partner is among the proposed neighbours.")

    def as_text(self) -> str:
        return (f"comparer {self.comparer}: {self.duplicates} gold duplicates in the repository ({self.missing} gone)\n"
                f"  partner among the top {self.neighbours} proposed: {self.recall:.0%}")


def bench_comparer(gold: list[GoldPair], detector: Detector) -> ComparerBench:
    """Whether the comparer proposes each gold duplicate, on the repository as it is now."""
    by_name = {f.qualname: f for f in detector.functions}
    present = [g for g in gold if g.label == "duplicate" and g.new.id in by_name and g.existing.id in by_name]
    found = 0.0
    for g in present:
        proposed = {other.qualname for other, _ in detector.neighbours(by_name[g.new.id])}
        found += g.weight if g.existing.id in proposed else 0.0
    total = sum(g.weight for g in present)
    return ComparerBench(comparer=detector.comparer_id, neighbours=detector.settings.neighbours, duplicates=len(present),
                         missing=sum(1 for g in gold if g.label == "duplicate") - len(present),
                         recall=found / total if total else 0.0)
