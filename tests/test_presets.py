import pytest

from dry_lint.presets import AUTO_ORDER, LISTED, PRESETS, auto_preset, resolve
from dry_lint.settings import Escalation, PluginChoice, Settings

BOTH = {"TYPESAFE_AI_API_KEY": "k", "ANTHROPIC_API_KEY": "k"}


def test_agent_feedback_is_explicit_and_keeps_its_own_model_prompt_and_thresholds() -> None:
    settings = resolve(Settings(preset="agent-haiku"), BOTH)
    assert settings.judge.options() == {
        "model": "claude-haiku-5-5",
        "prompt_policy": "shared-operations",
        "max_tokens": 2048,
    }
    assert settings.escalate is None
    assert settings.report_at == settings.fail_at == 0.5
    assert "agent-haiku" not in AUTO_ORDER


@pytest.mark.parametrize("environ, preset", [
    (BOTH, "jev+opus"),
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
    assert (settings.judge.use, settings.escalate.use, settings.escalate.options()) == (
        "jev",
        "anthropic",
        {"model": "claude-opus-5-5"},
    )
    assert (settings.escalate.between, settings.drop_below, settings.report_at, settings.fail_at) == (
        (0.5, 0.91),
        0.5,
        0.55,
        0.55,
    )


def test_every_jev_first_preset_holds_unescalated_answers_to_jevs_own_bar_for_the_same_reader() -> None:
    for preset in PRESETS.values():
        if preset.judge.use == "jev" and preset.escalate is not None:
            alone = PRESETS["agent" if preset.name.startswith("agent") else "jev"]
            assert preset.escalate.first_at == alone.fail_at == alone.report_at


def test_agent_presets_trade_precision_for_recall_and_are_only_chosen_by_name() -> None:
    # A coding agent checks every finding itself, so its presets report below the bar a person's merge is held to.
    for name in ("agent", "agent+haiku"):
        agent = PRESETS[name]
        assert agent.judge.use == "jev" and not agent.automatic
        assert agent.report_at == agent.fail_at < PRESETS["jev"].report_at
    haiku = resolve(Settings(preset="agent+haiku"), {})
    assert (haiku.escalate.use, haiku.escalate.options(), haiku.escalate.between) == (
        "anthropic",
        {"model": "claude-haiku-5-5"},
        (0.5, 0.91),
    )


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
    with pytest.raises(ValueError, match="Unknown preset 'fast'; available: jev\\+opus"):
        resolve(Settings(preset="fast"), {})


def test_a_codex_login_is_never_assumed_so_its_preset_must_be_named() -> None:
    assert auto_preset({"TYPESAFE_AI_API_KEY": "k"}) == "jev"
    named = resolve(Settings(preset="jev+codex"), {})
    assert (named.escalate.use, named.report_at, named.fail_at) == ("codex", 0.7, 0.7)


def test_balanced_adds_bounded_blocks_after_implicit_tfidf() -> None:
    settings = resolve(Settings(preset="balanced"), {})
    choices = settings.discovery.comparers
    assert [(c.use, c.neighbours) for c in choices] == [("tfidf", 20), ("operation-blocks", 1)]
    assert choices[0].options()["min_similarity"] == choices[0].options()["min_similarity_small"] == 0.35
    assert settings.budget.usd == 0.04 and settings.report_at == settings.fail_at == 0.5
    assert resolve(settings, {}).model_dump() == settings.model_dump()


@pytest.mark.parametrize("comparers", [[], [{"use": "custom", "neighbours": 7, "option": "kept"}]])
def test_balanced_preserves_explicit_comparer_lists_including_empty_opt_out(comparers) -> None:
    settings = resolve(Settings(preset="balanced", discovery={"comparers": comparers}), {})
    assert settings.discovery.enabled
    assert [c.model_dump(exclude_none=True) for c in settings.discovery.comparers] == comparers


def test_balanced_preserves_disabled_discovery_and_custom_baseline() -> None:
    disabled = resolve(Settings(preset="balanced", discovery={"enabled": False}), {})
    assert not disabled.discovery.enabled and not disabled.discovery.comparers
    custom = resolve(Settings(preset="balanced", comparer="custom"), {})
    assert custom.comparer.use == "custom" and not custom.discovery.comparers


def test_balanced_explicit_depth_and_floors_still_go_to_tfidf() -> None:
    settings = resolve(
        Settings(
            preset="balanced",
            comparer={"use": "tfidf", "max_df": 0.2, "min_similarity": 0.8, "min_similarity_small": 0.7},
            discovery={"depth": 12, "min_similarity": 0.45},
        ),
        {},
    )
    tfidf, blocks = settings.discovery.comparers
    assert tfidf.neighbours == 12
    assert tfidf.options()["max_df"] == 0.2
    assert tfidf.options()["min_similarity"] == tfidf.options()["min_similarity_small"] == 0.45
    assert blocks.use == "operation-blocks" and blocks.neighbours == 1


@pytest.mark.parametrize("environment", [{}, {"ANTHROPIC_API_KEY": "presence"}, BOTH])
def test_legacy_auto_does_not_enable_block_exploration(environment) -> None:
    settings = resolve(Settings(), environment)
    assert not settings.discovery.enabled and not settings.discovery.comparers


def test_balanced_resolved_block_choice_cannot_mutate_preset_or_future_resolve() -> None:
    first = resolve(Settings(preset="balanced"), {})
    original = PRESETS["balanced"].discovery_append[0].neighbours
    try:
        first.discovery.comparers[-1].neighbours = 7
        assert PRESETS["balanced"].discovery_append[0].neighbours == original == 1
        assert resolve(Settings(preset="balanced"), {}).discovery.comparers[-1].neighbours == 1
    finally:
        PRESETS["balanced"].discovery_append[0].neighbours = original
