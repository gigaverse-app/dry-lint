from pathlib import Path

from dry_lint.settings import Escalation, Pattern, PluginChoice, Settings


def test_defaults_are_the_measured_thresholds_and_the_built_in_plugins(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    assert (settings.drop_below, settings.report_at, settings.drift_at, settings.neighbours) == (0.6, 0.8, 0.8, 3)
    assert settings.fail_at == settings.report_at  # every reported duplicate fails until fail_at is raised
    assert [c.use for c in settings.extractors] == ["python"]
    assert (settings.comparer.use, settings.judge.use, settings.store.use, settings.escalate) == ("tfidf", "auto", "dir", None)


def test_settings_come_from_the_pyproject_tool_table(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\n\n[tool.dry-lint]\nreport_at = 0.9\nexclude = ["legacy/*"]\n\n'
        '[[tool.dry-lint.patterns]]\nmembers = "*/api/*::create_router"\nreason = "one router per resource"\n'
    )
    settings = Settings.load(tmp_path)
    assert settings.report_at == 0.9 and settings.exclude == ["legacy/*"]
    assert settings.patterns == [Pattern(members="*/api/*::create_router", reason="one router per resource")]


def test_a_pyproject_without_the_table_means_defaults(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    assert Settings.load(tmp_path) == Settings()


def test_a_dedicated_file_wins_over_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.dry-lint]\nreport_at = 0.9\n")
    (tmp_path / ".dry-lint.toml").write_text("report_at = 0.7\n")
    assert Settings.load(tmp_path).report_at == 0.7


def test_a_plugin_slot_takes_a_name_or_a_table_whose_other_keys_are_its_options(tmp_path: Path) -> None:
    (tmp_path / ".dry-lint.toml").write_text(
        'extractors = ["python", { use = "tree-sitter", languages = ["ts"] }]\n'
        'comparer = { use = "tfidf", min_similarity = 0.4 }\n'
        'judge = "jev"\n'
        'escalate = { use = "command", command = "claude -p", between = [0.5, 0.85] }\n'
        'store = { use = "s3", uri = "s3://bucket/repo" }\n'
    )
    settings = Settings.load(tmp_path)
    assert [c.use for c in settings.extractors] == ["python", "tree-sitter"]
    assert settings.extractors[1].options() == {"languages": ["ts"]}
    assert settings.comparer == PluginChoice(use="tfidf", min_similarity=0.4)
    assert settings.comparer.options() == {"min_similarity": 0.4}
    assert (settings.judge.use, settings.judge.options()) == ("jev", {})
    assert settings.escalate.between == (0.5, 0.85) and settings.escalate.options() == {"command": "claude -p"}
    assert settings.store.options() == {"uri": "s3://bucket/repo"}


def test_an_escalation_named_by_a_string_uses_the_default_band() -> None:
    assert Settings.model_validate({"escalate": "command"}).escalate == Escalation(use="command", between=(0.6, 0.8))
