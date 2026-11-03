"""
What judging costs, and the budget that bounds it.

Every judge with a known model is estimated at its list price, from its prompt length and a measured answer length,
and counted against `budget.usd`. That includes subscription judges: a call through a Claude subscription uses the
same model as the API, so its list price is what it takes out of the subscription. Subscriptions are rate-limited
too, so they are also counted against `budget.subscription_calls`. A judge whose price is unknown is not budgeted
and its cost is reported as unknown, never as zero. When the budget runs out, the riskiest pairs have already been
judged: callers order them first.

The budget is for a pull request, across all its pushes: what earlier runs on the same pull request spent comes
from the verdict store (`VerdictStore.spent`), and a run without a pull request has the whole budget to itself.
"""

from pydantic import BaseModel, Field

from dry_lint.judges.command import prompt
from dry_lint.models import Candidate
from dry_lint.plugins import Judge, identity
from dry_lint.settings import Settings

# USD per million input and output tokens; checked November 2026 (Anthropic and OpenRouter price lists).
PRICES: dict[str, tuple[float, float]] = {
    "jev": (0.04, 0.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "gemini-3.1-pro-preview": (2.0, 12.0),
    "gemini-2.5-pro": (1.25, 10.0),
}
CHARS_PER_TOKEN = 2.8  # measured: the DRY prompt over gigaverse-ai pairs, Claude Sonnet 5.5's tokenizer
ANSWER_TOKENS = 150  # measured: Sonnet 5.5's answers (thinking included) were 126 tokens on average, p90 150
ANSWERS: dict[str, int] = {"claude-opus-5-5": 220}  # measured: Opus 5.5's were 217 on average, p90 390


def price(judge: Judge, settings: Settings) -> tuple[float, float] | None:
    table = {**PRICES, **settings.prices}
    return table.get(getattr(judge, "model", "") or "") or table.get(judge.name)


def estimate(judge: Judge, candidates: list[Candidate], settings: Settings) -> float | None:
    """Estimated USD at list price for asking `judge` about `candidates`, subscriptions included; None if unknown."""
    rates = price(judge, settings)
    if rates is None:
        return None
    policy = getattr(judge, "prompt_policy", "concept")  # Optional plugin contract for the rendered prompt.
    tokens = sum(len(prompt(c, policy=policy)) for c in candidates) / CHARS_PER_TOKEN
    answer = ANSWERS.get(getattr(judge, "model", "") or "", ANSWER_TOKENS)
    return (tokens * rates[0] + len(candidates) * answer * rates[1]) / 1_000_000


class Spend(BaseModel):
    judge: str
    calls: int = 0
    skipped: int = Field(default=0, description="Pairs this judge was not asked about because the budget ran out.")
    usd: float | None = Field(default=0.0, description="Estimated at list price, also for a subscription; None when "
                                                       "the judge's price is unknown.")
    subscription: bool = False


class Ledger:
    """One run's spending, on top of what earlier runs on the same pull request `spent`: how many of the pairs each
    judge may still be asked about."""

    def __init__(self, settings: Settings, spent: float = 0.0) -> None:
        self.settings, self.spent = settings, spent
        self.spend: dict[str, Spend] = {}

    @property
    def usd(self) -> float:
        """This run's estimated spending."""
        return sum(s.usd or 0.0 for s in self.spend.values())

    def affordable(self, judge: Judge, candidates: list[Candidate]) -> int:
        """How many of `candidates`, in order, the budget still allows `judge` to be asked about."""
        if getattr(judge, "subscription", False):
            used = sum(s.calls for s in self.spend.values() if s.subscription)
            candidates = candidates[:max(0, self.settings.budget.subscription_calls - used)]
        total, room = 0.0, self.settings.budget.usd - self.spent - self.usd
        for n, candidate in enumerate(candidates):
            cost = estimate(judge, [candidate], self.settings)
            if cost is None:
                return len(candidates)  # unpriced: cannot be budgeted, and is reported as unknown
            if total + cost > room:
                return n
            total += cost
        return len(candidates)

    def charge(self, judge: Judge, asked: list[Candidate], skipped: int) -> None:
        name = identity(judge)
        spend = self.spend.setdefault(name, Spend(judge=name, subscription=getattr(judge, "subscription", False)))
        cost = estimate(judge, asked, self.settings)
        spend.calls += len(asked)
        spend.skipped += skipped
        spend.usd = None if cost is None or spend.usd is None else spend.usd + cost
