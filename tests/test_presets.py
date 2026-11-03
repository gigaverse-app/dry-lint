import pytest

from dry_lint.presets import AUTO_ORDER, LISTED, PRESETS, auto_preset, resolve
from dry_lint.settings import Escalation, PluginChoice, Settings

BOTH = {"TYPESAFE_AI_API_KEY": "k", "ANTHROPIC_API_KEY": "k"}


@pytest.mark.parametrize("environ, preset", [
    (BOTH, "jev+sonnet"),
    ({"TYPESAFE_AI_API_KEY": "k", "CLAUDE_CODE_OAUTH_TOKEN": "t"}, "jev+claude-code"),
    ({"TYPESAFE_AI_API_KEY": "k"}, "jev"),
    ({"ANTHROPIC_API_KEY": "k"}, "sonnet"),
    ({"CLAUDE_CODE_OAUTH_TOKEN": "t"}, "claude-code"),
    ({"TYPESAFE_AI_API_KEY": ""}, "none"),
    ({}, "none"),
])  # fmt: skip
def test_auto_picks_the_best_preset_the_credentials_allow(environ, preset) -> None:
    assert auto_preset(environ) == preset
    assert resolve(Settings(), environ).preset == preset


def test_every_preset_is_reachable_and_measured_ones_say_what_was_measured() -> None:
    assert set(LISTED) == set(PRESETS) and {p.name for p in PRESETS.values() if p.automatic} == set(AUTO_ORDER)
    assert all(p.numbers for p in PRESETS.values() if p.name != "none")


def test_a_preset_fills_judges_and_thresholds_that_were_not_set() -> None:
    settings = resolve(Settings(), BOTH)
    assert (settings.judge.use, settings.escalate.use, settings.escalate.options()) == ("jev", "anthropic", {"model": "claude-sonnet-5-5"})
    assert (settings.escalate.between, settings.drop_below, settings.report_at, settings.fail_at) == ((0.5, 0.91), 0.5, 0.6, 0.7)


def test_explicit_settings_win_over_the_preset() -> None:
    settings = resolve(Settings.model_validate({"fail_at": 0.9, "escalate": "none", "preset": "jev+sonnet"}), {})
    assert (settings.fail_at, settings.report_at, settings.escalate.use) == (0.9, 0.6, "none")


def test_a_named_preset_does_not_need_its_credentials_to_be_chosen() -> None:
    assert resolve(Settings(preset="jev+claude-code"), {}).escalate.use == "claude-code"


def test_your_own_judge_gets_no_preset_escalation_or_thresholds() -> None:
    own = resolve(Settings(judge=PluginChoice(use="command", command="llm")), BOTH)
    assert (own.preset, own.escalate, own.fail_at) == ("custom", None, 0.8)
    kept = resolve(Settings(judge=PluginChoice(use="command", command="llm"), escalate=Escalation(use="gemini")), BOTH)
    assert kept.escalate.use == "gemini"
    named = resolve(Settings(preset="jev+sonnet", judge=PluginChoice(use="jev", workers=2)), {})
    assert (named.judge.options(), named.escalate.use) == ({"workers": 2}, "anthropic")


def test_an_unknown_preset_names_the_known_ones() -> None:
    with pytest.raises(ValueError, match="Unknown preset 'fast'; available: jev\\+sonnet"):
        resolve(Settings(preset="fast"), {})


def test_a_codex_login_is_never_assumed_so_its_preset_must_be_named() -> None:
    assert auto_preset({"TYPESAFE_AI_API_KEY": "k"}) == "jev"
    named = resolve(Settings(preset="jev+codex"), {})
    assert (named.escalate.use, named.report_at, named.fail_at) == ("codex", 0.7, 0.7)
