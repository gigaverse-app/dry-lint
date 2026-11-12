"""Repository metadata can move without changing scope, decisions or Git snapshot semantics."""

import pytest

from dry_lint.cli import main, read_feedback
from dry_lint.detector import Detector, changed_functions
from dry_lint.feedback import Decision, Feedback
from dry_lint.function_index import export_index, source_settings
from dry_lint.model_review import profile
from dry_lint.models import evidence
from dry_lint.settings import Settings

from conftest import EXISTING, run_cli

CONFIG = 'fail_at = 0.91\nexclude = ["src/filler.py"]\n'
IGNORE = """schema: 1
distinct:
  - symbol: src/widgets/caption.py::preview_caption_text
    from:
      - src/text.py::shorten_text
      - src/third.py::third_text
    reason: >
      Independent display contracts
"""


@pytest.mark.parametrize("path", [".dry-lint.toml", ".dry-lint/config.toml"])
def test_configuration_layout_preserves_local_staged_and_index_scope(repo, path):
    repo.write("pyproject.toml", '[tool.dry-lint]\ninclude = ["missing/*"]\n')
    repo.write(path, CONFIG)
    repo.commit()
    expected = Settings(fail_at=0.91, exclude=["src/filler.py"])
    assert Settings.load(repo.root) == expected
    assert Settings.load(repo.root, staged=True) == expected
    index = export_index(repo.root, "org/app", Settings())
    assert {f.path for f in index.functions} == {"src/text.py", "src/widgets/caption.py"}
    assert index.scope == {"include": ["*"], "exclude": ["src/filler.py"]}


def test_moving_configuration_preserves_staged_settings_and_rejects_ambiguous_worktree(repo):
    repo.write(".dry-lint.toml", CONFIG)
    repo.commit()
    (repo.root / ".dry-lint").mkdir()
    repo.git("mv", ".dry-lint.toml", ".dry-lint/config.toml")
    repo.write(".dry-lint.toml", "fail_at = 0.1\n")  # not staged
    assert Settings.load(repo.root, staged=True).fail_at == 0.91
    with pytest.raises(ValueError, match="both|multiple"):
        Settings.load(repo.root)
    with pytest.raises(ValueError, match="both|multiple"):
        source_settings({".dry-lint.toml": CONFIG.encode(), ".dry-lint/config.toml": CONFIG.encode()})


def test_only_repository_root_configuration_is_loaded(repo):
    repo.write(".dry-lint/config.toml", CONFIG)
    repo.write("src/.dry-lint/config.toml", 'include = ["missing/*"]\n')
    repo.write("src/.dry-lint/ignore.yaml", "invalid yaml: [")
    assert Settings.load(repo.root).fail_at == 0.91
    assert Settings.load(repo.root).include == ["*"]


@pytest.mark.parametrize(
    "path",
    [
        ".dry-lint-ignore.toml",
        ".dry-lint-ignore.yaml",
        ".dry-lint-ignore.yml",
        ".dry-lint/ignore.toml",
        ".dry-lint/ignore.yml",
    ],
)
def test_root_ignore_alias_is_rejected_with_the_supported_destination(repo, path):
    repo.write(path, IGNORE)
    with pytest.raises(ValueError, match=r"\.dry-lint/ignore\.yaml"):
        Settings.load(repo.root)


def test_distinctions_are_symmetric_exact_pairs_and_do_not_form_a_family(repo):
    repo.write("src/third.py", EXISTING.replace("shorten_text", "third_text"))
    repo.write(".dry-lint/ignore.yaml", IGNORE)
    repo.commit()
    detector = Detector.for_repository(repo.root, Settings.load(repo.root))
    owner = detector.find("preview_caption_text")
    first, second = detector.find("shorten_text"), detector.find("third_text")
    for target in (first, second):
        for a, b in ((owner, target), (target, owner)):
            assert "Independent display contracts" in detector.pair(a, b, 1).filtered
    assert detector.pair(first, second, 1).filtered is None
    assert detector.pair(owner, detector.find("register_widget"), 1).filtered is None


def test_model_declarations_use_the_same_reviewed_pair_rules(repo):
    repo.write(
        "src/options.ts",
        """
        interface Pane { pane: string; label: string; icon: string; }
        interface Badge { role: string; label: string; icon: string; }
    """,
    )
    repo.write(
        ".dry-lint/ignore.yaml",
        """schema: 1
distinct:
  - symbol: src/options.ts::Pane
    from: [src/options.ts::Badge]
    reason: Destinations and role badges evolve independently
    """,
    )
    repo.commit()
    settings = Settings.load(repo.root)
    assert Settings.model_validate_json(settings.model_dump_json()) == settings
    detector = Detector.for_repository(repo.root, profile(settings))
    candidate = detector.pair(detector.find("Pane"), detector.find("Badge"), 1)
    assert candidate.new.declaration and candidate.existing.declaration
    assert "Destinations and role badges evolve independently" in candidate.filtered


@pytest.mark.parametrize(
    "invalid",
    [
        IGNORE.replace("schema: 1", "schema: 99"),
        IGNORE.replace("Independent display contracts", "  "),
        IGNORE.replace("src/widgets/caption.py::preview_caption_text", "preview_caption_text"),
        IGNORE + "\nunknown_setting: true\n",
        IGNORE + "\ndistinct: []\n",  # A merge must not silently erase the earlier decisions.
        IGNORE.replace("    from:", "    symbol: src/other.py::Other\n    from:"),
        "schema: 1\ndistinct: [\n",
        "schema: 1\ndistinct: !!python/object:builtins.list {}\n",
        "schema: 1\n---\nschema: 1\n",
        "",
    ],
)
def test_malformed_ignores_fail_instead_of_silently_discarding_decisions(repo, invalid):
    repo.write(".dry-lint/ignore.yaml", invalid)
    with pytest.raises(ValueError):
        Settings.load(repo.root)


def test_staged_ignore_requires_staging_and_survives_split_detection(repo, tmp_path, blocking_twin_judge):
    repo.git("reset", "--soft", "main")
    args = ("--staged", "--judge", "command", "--judge-command", blocking_twin_judge, "--no-models")
    assert run_cli(repo, tmp_path, *args) == 1
    repo.write(".dry-lint/ignore.yaml", IGNORE)
    assert run_cli(repo, tmp_path, *args) == 1
    repo.git("add", ".dry-lint/ignore.yaml")
    assert run_cli(repo, tmp_path, *args) == 0
    report = tmp_path / "candidates.json"
    assert main(["detect", "--root", str(repo.root), "--staged", "--out", str(report), "--no-models"]) == 0
    from dry_lint.models import CandidatesFile

    candidates = CandidatesFile.model_validate_json(report.read_bytes()).candidates
    assert any(c.filtered and "Independent display contracts" in c.filtered for c in candidates)


@pytest.mark.parametrize("staged", [False, True])
@pytest.mark.parametrize("previous", [IGNORE, "schema: 99\n", "schema: 1\ndistinct: [\n"])
def test_removing_an_ignore_rechecks_its_endpoints_without_source_edits(
    repo, tmp_path, blocking_twin_judge, staged, previous
):
    repo.write(".dry-lint/ignore.yaml", previous)
    repo.commit()
    base = repo.git("rev-parse", "HEAD")
    repo.git("rm", ".dry-lint/ignore.yaml")
    if not staged:
        repo.commit()
    args = ("--staged",) if staged else ("--base", base)
    assert run_cli(repo, tmp_path, *args, "--judge", "command", "--judge-command", blocking_twin_judge) == 1


def test_moving_only_configuration_preserves_pair_evidence(repo):
    repo.write(
        ".dry-lint.toml",
        '[[policies]]\nname="ownership"\nreason="Separate owners"\n'
        'left={names=["preview_caption_text"]}\nright={names=["shorten_text"]}\n',
    )
    repo.commit()

    def candidate():
        detector = Detector.for_repository(repo.root, Settings.load(repo.root))
        return detector.pair(detector.find("preview_caption_text"), detector.find("shorten_text"), 1)

    before = candidate()
    (repo.root / ".dry-lint").mkdir()
    repo.git("mv", ".dry-lint.toml", ".dry-lint/config.toml")
    assert candidate() == before
    assert evidence(candidate()) == evidence(before)


def test_removing_a_workspace_ignore_selects_only_the_primary_repository_endpoint(repo):
    repo.write(
        ".dry-lint/ignore.yaml",
        """schema: 1
distinct:
  - symbol: org/app/src/widgets/caption.py::preview_caption_text
    from: [org/peer/src/text.py::shorten_text]
    reason: Independent ownership
    """,
    )
    repo.commit()
    base = repo.git("rev-parse", "HEAD")
    repo.git("rm", ".dry-lint/ignore.yaml")
    repo.commit()
    changed = changed_functions(repo.root, Settings(), base, repository="org/app")
    assert [f.qualname for f in changed] == ["src/widgets/caption.py::preview_caption_text"]


@pytest.mark.parametrize("path", [".dry-lint-feedback.json", ".dry-lint/feedback.json"])
def test_feedback_migration_preserves_exact_evidence_and_snapshot_reads(repo, path):
    detector = Detector.for_repository(repo.root, Settings())
    pair = detector.pair(detector.find("preview_caption_text"), detector.find("shorten_text"), 1)
    decisions = Feedback(
        decisions=[
            Decision(
                pair=pair.key,
                evidence=evidence(pair),
                action="dismiss",
                reason="Independent display contracts",
                reviewer="test-agent",
                revision=repo.git("rev-parse", "HEAD"),
            )
        ]
    )
    decisions.write(repo.root / path)
    assert read_feedback(repo.root).apply([pair])[0].filtered
    assert not read_feedback(repo.root, staged=True).decisions
    repo.commit()
    for kwargs in ({}, {"staged": True}, {"committed": True}):
        assert read_feedback(repo.root, **kwargs) == decisions
    other = ".dry-lint/feedback.json" if path == ".dry-lint-feedback.json" else ".dry-lint-feedback.json"
    decisions.write(repo.root / other)
    with pytest.raises(ValueError, match="both|multiple"):
        read_feedback(repo.root)
    assert read_feedback(repo.root, committed=True) == decisions
