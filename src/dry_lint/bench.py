"""
`dry-lint bench`: measure a judge or a comparer on a gold set, so every plugin is compared on the same pairs.

The gold set is JSON lines (`gold.jsonl`), one labelled pair per line. Each line carries both functions' code as it
was when labelled, so the judge benchmark still runs after the repository has moved on. `weight` projects a
stratified sample back to its population (each stratum's size over its sample size), and defaults to 1.
Borderline pairs are kept in the file and left out of the numbers.
"""

import textwrap
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from dry_lint.detector import Detector
from dry_lint.models import Candidate, Function
from dry_lint.plugins import Extractor, Judge, identity
from dry_lint.settings import Settings

BANDS = (0.0, 0.1, 0.3, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01)


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


def load_gold(path: Path) -> list[GoldPair]:
    return [GoldPair.model_validate_json(line) for line in path.read_text().splitlines() if line.strip()]


def as_function(side: GoldFunction, extractor: Extractor) -> Function:
    path, _, qualified = side.id.partition("::")
    found = extractor.functions(path, textwrap.dedent(side.code).strip() + "\n")
    if not found:
        raise ValueError(f"The gold code for {side.id} has no function the {extractor.name} extractor can read")
    owner, _, name = qualified.rpartition(".")
    return found[0].model_copy(update={"name": name, "owner": owner or None})


def auc(scored: list[tuple[float, bool, float]]) -> float:
    """Weighted probability that a duplicate outscores a separate pair; ties count half."""
    positives = [(s, w) for s, dup, w in scored if dup]
    negatives = [(s, w) for s, dup, w in scored if not dup]
    total = sum(wp * wn for _, wp in positives for _, wn in negatives)
    wins = sum(wp * wn * (1.0 if sp > sn else 0.5 if sp == sn else 0.0)
               for sp, wp in positives for sn, wn in negatives)
    return wins / total if total else float("nan")


class Band(BaseModel):
    low: float
    high: float
    duplicates: float
    separate: float


class JudgeBench(BaseModel):
    judge: str
    pairs: int
    duplicates: int
    auc: float
    precision: float = Field(description="At report_at.")
    recall: float = Field(description="At report_at.")
    recall_at_drop: float = Field(description="Share of duplicates at or above drop_below.")
    bands: list[Band]

    def as_text(self, settings: Settings) -> str:
        lines = [f"judge {self.judge}: {self.pairs} labelled pairs, {self.duplicates} duplicates",
                 f"  AUC {self.auc:.2f}",
                 f"  at report_at {settings.report_at}: precision {self.precision:.0%}, recall {self.recall:.0%}",
                 f"  at drop_below {settings.drop_below}: recall {self.recall_at_drop:.0%}",
                 "  score band    duplicates  separate"]
        lines += [f"  {b.low:.1f}-{min(b.high, 1.0):.1f}    {b.duplicates:10.1f}  {b.separate:8.1f}" for b in self.bands]
        return "\n".join(lines)


def bench_judge(gold: list[GoldPair], judge: Judge, settings: Settings, extractor: Extractor) -> JudgeBench:
    labelled = [g for g in gold if g.label != "borderline"]
    candidates = [Candidate(new=as_function(g.new, extractor), existing=as_function(g.existing, extractor), similarity=0.0)
                  for g in labelled]
    verdicts = judge.judge(candidates, settings) if candidates else []
    scored = [(v.score, g.label == "duplicate", g.weight) for g, v in zip(labelled, verdicts)]

    def weight(condition) -> float:
        return sum(w for score, duplicate, w in scored if condition(score, duplicate))

    duplicates = weight(lambda score, duplicate: duplicate)
    flagged = weight(lambda score, duplicate: score >= settings.report_at)
    hits = weight(lambda score, duplicate: duplicate and score >= settings.report_at)
    kept = weight(lambda score, duplicate: duplicate and score >= settings.drop_below)
    bands = [Band(low=low, high=high,
                  duplicates=weight(lambda s, d, lo=low, hi=high: d and lo <= s < hi),
                  separate=weight(lambda s, d, lo=low, hi=high: not d and lo <= s < hi))
             for low, high in zip(BANDS, BANDS[1:])]  # fmt: skip
    return JudgeBench(judge=identity(judge), pairs=len(labelled), duplicates=sum(1 for g in labelled if g.label == "duplicate"),
                      auc=auc(scored), precision=hits / flagged if flagged else 0.0,
                      recall=hits / duplicates if duplicates else 0.0, recall_at_drop=kept / duplicates if duplicates else 0.0,
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
