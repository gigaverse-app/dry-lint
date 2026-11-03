import pytest

from dry_lint.costs import ANSWER_TOKENS, CHARS_PER_TOKEN, Ledger, estimate, price
from dry_lint.judges.command import prompt
from dry_lint.models import Candidate
from dry_lint.settings import Budget, Settings

from conftest import function

PAIR = Candidate(new=function("a.py", "def f(x):\n    return x + 1\n"), existing=function("b.py", "def g(y):\n    return y + 1\n"),
                 similarity=0.7)


class Priced:
    name, version, model = "anthropic", "v", "claude-sonnet-5-5"


class Subscribed:
    name, version, subscription = "claude-code", "v", True


class Unpriced:
    name, version = "command:my-llm", "1"


def test_a_priced_judge_costs_its_prompt_and_a_measured_answer() -> None:
    expected = (len(prompt(PAIR)) / CHARS_PER_TOKEN * 2.0 + ANSWER_TOKENS * 10.0) / 1_000_000
    assert estimate(Priced(), [PAIR, PAIR], Settings()) == pytest.approx(2 * expected)
    assert price(Priced(), Settings()) == (2.0, 10.0)


def test_subscriptions_cost_nothing_per_call_and_unknown_prices_stay_unknown() -> None:
    assert estimate(Subscribed(), [PAIR], Settings()) == 0.0
    assert estimate(Unpriced(), [PAIR], Settings()) is None
    assert estimate(Unpriced(), [PAIR], Settings(prices={"command:my-llm": (1.0, 1.0)})) > 0


def test_the_budget_allows_pairs_until_the_next_would_exceed_it() -> None:
    one = estimate(Priced(), [PAIR], Settings())
    ledger = Ledger(Settings(budget=Budget(usd=one * 2.5)))
    assert ledger.affordable(Priced(), [PAIR] * 5) == 2
    ledger.charge(Priced(), [PAIR, PAIR], skipped=3)
    assert ledger.affordable(Priced(), [PAIR] * 5) == 0
    [spend] = ledger.spend.values()
    assert (spend.judge, spend.calls, spend.skipped, spend.usd) == ("anthropic:v", 2, 3, pytest.approx(2 * one))
    assert ledger.usd == pytest.approx(2 * one)


def test_subscriptions_are_bounded_by_calls_and_unpriced_judges_are_not_bounded() -> None:
    ledger = Ledger(Settings(budget=Budget(usd=0.0, subscription_calls=3)))
    assert ledger.affordable(Subscribed(), [PAIR] * 5) == 3
    ledger.charge(Subscribed(), [PAIR] * 3, skipped=2)
    assert ledger.affordable(Subscribed(), [PAIR]) == 0 and ledger.usd == 0
    assert ledger.affordable(Unpriced(), [PAIR] * 4) == 4
    ledger.charge(Unpriced(), [PAIR], skipped=0)
    ledger.charge(Unpriced(), [PAIR], skipped=0)
    assert ledger.spend["command:my-llm:1"].usd is None and ledger.spend["command:my-llm:1"].calls == 2
