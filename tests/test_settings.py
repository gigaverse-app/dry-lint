from pathlib import Path

from dry_lint.settings import Pattern, Settings


def test_defaults_are_the_measured_thresholds(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    assert (settings.drop_below, settings.report_at, settings.drift_at) == (0.6, 0.8, 0.8)
    assert (settings.min_similarity, settings.min_similarity_small, settings.neighbours) == (0.5, 0.3, 3)


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
