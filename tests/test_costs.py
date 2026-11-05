import pytest

from dry_lint.costs import ANSWER_TOKENS, ANSWERS, CHARS_PER_TOKEN, Ledger, Spend, combined, estimate, price
from dry_lint.judges.command import prompt
from dry_lint.models import Candidate
from dry_lint.settings import Budget, Settings

from conftest import function

PAIR = Candidate(
    new=function("a.py", "def f(x):\n    return x + 1\n"),
    existing=function("b.py", "def g(y):\n    return y + 1\n"),
    similarity=0.7,
)


class Priced:
    name, version, model = "anthropic", "v", "claude-sonnet-5-5"


class Subscribed:
    name, version, subscription = "claude-code", "v", True


class SubscribedSonnet(Subscribed):
    model = "claude-sonnet-5-5"


class Opus:
    name, version, model = "anthropic", "v", "claude-opus-5-5"


class Unpriced:
    name, version = "command:my-llm", "1"


def test_a_priced_judge_costs_its_prompt_and_a_measured_answer() -> None:
    expected = (len(prompt(PAIR)) / CHARS_PER_TOKEN * 2.0 + ANSWER_TOKENS * 10.0) / 1_000_000
    assert estimate(Priced(), [PAIR, PAIR], Settings()) == pytest.approx(2 * expected)
    assert price(Priced(), Settings()) == (2.0, 10.0)


def test_a_subscription_costs_its_models_list_price_and_unknown_prices_stay_unknown() -> None:
    assert estimate(SubscribedSonnet(), [PAIR], Settings()) == pytest.approx(estimate(Priced(), [PAIR], Settings()))
    assert estimate(Subscribed(), [PAIR], Settings()) is None
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


def test_an_opus_answer_is_priced_at_its_measured_length() -> None:
    expected = (len(prompt(PAIR)) / CHARS_PER_TOKEN * 4.0 + ANSWERS["claude-opus-5-5"] * 20.0) / 1_000_000
    assert estimate(Opus(), [PAIR], Settings()) == pytest.approx(expected)


def test_what_earlier_runs_spent_comes_off_the_budget() -> None:
    one = estimate(Priced(), [PAIR], Settings())
    settings = Settings(budget=Budget(usd=one * 3.5))
    assert Ledger(settings).affordable(Priced(), [PAIR] * 5) == 3
    assert Ledger(settings, spent=one * 2).affordable(Priced(), [PAIR] * 5) == 1
    assert Ledger(settings, spent=one * 4).affordable(Priced(), [PAIR] * 5) == 0


def test_a_subscription_is_bounded_by_both_its_calls_and_its_list_price() -> None:
    one = estimate(SubscribedSonnet(), [PAIR], Settings())
    assert (
        Ledger(Settings(budget=Budget(usd=one * 10, subscription_calls=2))).affordable(SubscribedSonnet(), [PAIR] * 5)
        == 2
    )
    assert (
        Ledger(Settings(budget=Budget(usd=one * 1.5, subscription_calls=20))).affordable(SubscribedSonnet(), [PAIR] * 5)
        == 1
    )


def test_combined_spending_adds_up_per_judge_and_keeps_unknown_costs_unknown() -> None:
    spends = [
        Spend(judge="a", calls=2, skipped=1, usd=0.5),
        Spend(judge="b", calls=1, usd=None),
        Spend(judge="a", calls=3, failed=1, usd=0.25, error="login expired"),
        Spend(judge="b", calls=4, usd=1.0),
    ]
    total = {s.judge: s for s in combined(spends)}
    assert (total["a"].calls, total["a"].skipped, total["a"].failed, total["a"].usd) == (5, 1, 1, 0.75)
    assert total["a"].error == "login expired"
    assert total["b"].calls == 5 and total["b"].usd is None


def test_refill_counts_only_funded_subscription_calls_and_keeps_prior_spend() -> None:
    large = PAIR.model_copy(deep=True)
    large.new.code += "\n    x += 1" * 10000
    judge = SubscribedSonnet()
    one = estimate(judge, [PAIR], Settings())
    settings = Settings(budget=Budget(usd=one * 3.5, subscription_calls=2))
    ledger = Ledger(settings, spent=one)
    ledger.charge(judge, [PAIR], skipped=0)
    candidates = [large, PAIR, PAIR]
    assert ledger.affordable(judge, candidates) == 0  # the legacy prefix contract remains available
    assert ledger.select(judge, candidates) == [1]
    ledger.charge(judge, [PAIR], skipped=2)
    assert ledger.select(judge, candidates) == []
    assert ledger.usd + ledger.spent == pytest.approx(3 * one)


def test_refill_preserves_the_funded_prefix_when_only_the_remaining_budget_is_too_small() -> None:
    large = PAIR.model_copy(deep=True)
    large.new.code += "\n    x += 1" * 500
    judge = Priced()
    one = estimate(judge, [PAIR], Settings())
    expensive = estimate(judge, [large], Settings())
    settings = Settings(budget=Budget(usd=expensive + one / 2))
    assert expensive < settings.budget.usd < expensive + one
    assert 2 * one < settings.budget.usd
    ledger = Ledger(settings)
    assert ledger.affordable(judge, [PAIR, large, PAIR]) == 1
    assert ledger.select(judge, [PAIR, large, PAIR]) == [0, 2]
