"""The concise offline profile is exactly the existing explicit route configuration."""

import pytest

from dry_lint.settings import Settings


def explicit(model, cache):
    return [
        {"use": "tfidf", "neighbours": 20, "min_similarity": 0.35, "min_similarity_small": 0.35},
        {"use": "operation-blocks", "neighbours": 1},
        {"use": "cpu-embedding", "neighbours": 1, "model_dir": model, "cache_dir": cache, "threads": 2},
        {"use": "cpu-tail-rrf", "neighbours": 1, "model_dir": model, "cache_dir": cache, "threads": 2},
    ]


def test_profile_load_normalization_and_roundtrip(tmp_path):
    (tmp_path / ".dry-lint.toml").write_text(
        '[discovery.cpu_recovery]\nmodel_dir = "offline-model"\ncache_dir = "vectors"\n'
    )
    actual = Settings.load(tmp_path)
    expected = Settings(discovery={"enabled": True, "comparers": explicit("offline-model", "vectors")})
    assert actual == expected
    assert Settings.model_validate(actual.model_dump()) == expected
    disabled = Settings(discovery={"enabled": False, "cpu_recovery": {"model_dir": "m", "cache_dir": "v"}})
    assert not disabled.discovery.enabled


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"model_dir": "m"},
        {"model_dir": "", "cache_dir": "v"},
        {"model_dir": "m", "cache_dir": "v", "threads": 3},
        {"model_dir": "m", "cache_dir": "v", "ranking": "new"},
    ],
)
def test_profile_rejects_incomplete_or_unmeasured_options(options):
    with pytest.raises(ValueError):
        Settings(discovery={"cpu_recovery": options})


def test_profile_rejects_conflicting_explicit_routes():
    with pytest.raises(ValueError, match="comparers"):
        Settings(discovery={"cpu_recovery": {"model_dir": "m", "cache_dir": "v"}, "comparers": ["tfidf"]})


def test_inherited_balanced_routes_are_defaults_not_profile_conflicts(monkeypatch):
    from dry_lint.presets import PRESETS, resolve
    from dry_lint.settings import Discovery

    inherited = Discovery(enabled=True, comparers=explicit("unused", "unused")[:2])
    monkeypatch.setitem(PRESETS, "balanced", PRESETS["balanced"].model_copy(update={"discovery": inherited}))
    profile = {"model_dir": "adopter-model", "cache_dir": "adopter-cache"}
    settings = Settings(preset="balanced", discovery={"cpu_recovery": profile})
    # Shorthand normalization occurs on user input, before preset inheritance.
    assert settings.discovery.model_fields_set == {"enabled", "comparers"}
    assert (
        resolve(settings, {}).discovery.comparers
        == Settings(discovery={"comparers": explicit("adopter-model", "adopter-cache")}).discovery.comparers
    )
    disabled = resolve(Settings(preset="balanced", discovery={"enabled": False, "cpu_recovery": profile}), {})
    assert not disabled.discovery.enabled
    assert resolve(Settings(preset="balanced", discovery={"comparers": []}), {}).discovery.comparers == []
    assert resolve(Settings(), {}).discovery.comparers == []
