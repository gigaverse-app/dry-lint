"""An installed language unknown to core participates in every integration through its capabilities."""

import sys
import textwrap

import pytest
from test_comparison import AFTER, REPO, VIEWER, SourceGitHub, client

from dry_lint.cli import main
from dry_lint.comparison import Comparisons
from dry_lint.evidence import SourceReference
from dry_lint.extractor_capabilities import capabilities, comment_style, extractor_class_for
from dry_lint.function_index import FunctionIndex, build_index, extraction_contract
from dry_lint.model_review import enabled, profile
from dry_lint.models import Candidate, CandidatesFile, Run
from dry_lint.plugins import load
from dry_lint.report import Finding
from dry_lint.settings import PluginChoice, Settings

from conftest import Repo


@pytest.fixture
def installed_language(tmp_path, monkeypatch):
    # This intentionally uses Python syntax in a test-only extension. It proves plugin integration, not Go parsing.
    (tmp_path / "quartz_language.py").write_text(
        textwrap.dedent("""
        from dataclasses import replace
        from dry_lint.extractor_capabilities import ExtractorCapabilities
        from dry_lint.extractors import PythonExtractor
        from dry_lint.model_shapes import PythonModelExtractor
        from quartz_base import Base

        class Quartz(Base):
            name = "quartz"
            files = ("*.quartz",)
            capabilities = ExtractorCapabilities(
                language_name="Quartz", comment_prefix=";", model_extractor="quartz-records",
                index_modules=("quartz_support",), index_distributions=("quartz-parser",),
            )

        class Records(PythonModelExtractor):
            name = "quartz-records"
            files = Quartz.files
            capabilities = replace(Quartz.capabilities, is_model=True, model_extractor=None)

            def functions(self, path, source):
                records = super().functions(path, source)
                for record in records:
                    record.declaration.kind = "quartz-record"
                return records
    """)
    )
    (tmp_path / "quartz_support.py").write_text("CONTRACT = 1\n")
    (tmp_path / "quartz_base.py").write_text(
        textwrap.dedent("""
        from dry_lint.extractors import PythonExtractor
        from dry_lint.extractor_capabilities import ExtractorCapabilities

        class Base(PythonExtractor):
            capabilities = ExtractorCapabilities(index_modules=("quartz_base_support",))
    """)
    )
    (tmp_path / "quartz_base_support.py").write_text("CONTRACT = 1\n")
    info = tmp_path / "quartz_parser-0.1.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: quartz-parser\nVersion: 0.1\n")
    (info / "entry_points.txt").write_text(
        "[dry_lint.extractors]\nquartz = quartz_language:Quartz\nquartz-records = quartz_language:Records\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    yield tmp_path
    for module in ("quartz_language", "quartz_support", "quartz_base", "quartz_base_support"):
        sys.modules.pop(module, None)


def test_installed_language_selects_its_model_pass_without_name_conventions(installed_language):
    settings = Settings(extractors=["quartz"])
    assert [choice.use for choice in profile(settings).extractors] == [
        "python-models",
        "typescript-models",
        "quartz-records",
    ]
    assert not enabled(Settings(extractors=["quartz-records"]), None)


def test_index_tracks_active_plugin_sources_and_parser_versions(installed_language):
    settings = Settings(extractors=["quartz"])
    initial = extraction_contract(settings)
    defaults = extraction_contract(Settings())
    (installed_language / "quartz_base_support.py").write_text("CONTRACT = 2\n")
    inherited = extraction_contract(settings)
    assert inherited != initial
    (installed_language / "quartz_support.py").write_text("CONTRACT = 2\n")
    changed = extraction_contract(settings)
    assert changed != inherited
    metadata = installed_language / "quartz_parser-0.1.dist-info/METADATA"
    metadata.write_text(metadata.read_text().replace("Version: 0.1", "Version: 0.2"))
    parser_changed = extraction_contract(settings)
    assert parser_changed != changed
    assert extraction_contract(Settings()) == defaults
    implementation = installed_language / "quartz_language.py"
    implementation.write_text(implementation.read_text() + "\n# Changed implementation\n")
    assert extraction_contract(settings) != parser_changed


def test_plugin_model_kinds_roundtrip_without_a_core_language_enum(installed_language):
    source = b"from dataclasses import dataclass\n@dataclass\nclass Record:\n    id: str\n    amount: int\n"
    settings = Settings(extractors=["quartz-records"])
    index = build_index({"a.quartz": source}, "org/app", "a" * 40, settings)
    restored = FunctionIndex.decode(index.encode(), index.repository, index.commit, index.contract)
    assert restored.functions[0].declaration.kind == "quartz-record"


def test_installed_language_supplies_suppression_syntax(installed_language):
    from dry_lint.detector import why_skipped

    extractor = load("extractors", PluginChoice(use="quartz"))
    a = extractor.functions("a.quartz", "def work(x):\n    return x + 1\n")[0]
    b = a.model_copy(update={"path": "b.quartz"})
    finding = Finding(candidate=Candidate(new=a, existing=b, similarity=1))
    assert finding.suppression() == "; dry-lint: distinct-from b.quartz::work"
    a.code += "\n; dry-lint: distinct-from b.quartz::work\n"
    assert why_skipped(a, b, Settings()) == "inline distinct-from"
    a.code = "; dry-lint: ignore\n" + a.code
    assert why_skipped(a, b, Settings()) == "inline ignore"


def test_viewer_resolves_installed_function_and_model_from_one_read(installed_language):
    source = "from dataclasses import dataclass\n@dataclass\nclass Record:\n    id: str\n    amount: int\n\ndef work(x):\n    return x + 1\n"
    fake = SourceGitHub()
    fake.sources["a.quartz"] = (200, source)
    viewer = Comparisons(client(fake), REPO, AFTER, VIEWER)
    run = Run(repository=REPO, head="a" * 40)
    for name in ("quartz", "quartz-records"):
        function = load("extractors", PluginChoice(use=name)).functions("a.quartz", source)[0]
        known, found = viewer.current(SourceReference.of(function, run))
        assert known and found is not None and found.name == function.name
    assert len(fake.reads) == 1


def test_metadata_does_not_construct_optional_parsers_and_viewer_failure_is_unknown(monkeypatch):
    monkeypatch.setitem(sys.modules, "tree_sitter_luau", None)
    assert comment_style("a.lua").comment_prefix == "--"
    assert [choice.use for choice in profile(Settings()).extractors] == ["python-models", "typescript-models"]
    fake = SourceGitHub()
    viewer = Comparisons(client(fake), REPO, AFTER, VIEWER)
    reference = SourceReference(repository=REPO, revision="a" * 40, path="a.lua", name="work", line=1, end_line=2)
    assert viewer.current(reference) == (False, None)
    assert fake.reads == []


def test_unavailable_unrelated_plugins_and_legacy_metadata_do_not_break_lookup(installed_language):
    info = installed_language / "quartz_parser-0.1.dist-info/entry_points.txt"
    info.write_text(info.read_text() + "python = missing:BadOverride\nunavailable = missing:Extractor\n")
    assert extractor_class_for("a.py").name == "python"
    assert extractor_class_for("a.unknown") is None
    assert comment_style("a.unknown").comment_prefix == "#"

    class Legacy:
        name = "old-models"

    assert capabilities(Legacy).is_model
    assert capabilities(Legacy).model_extractor is None


def test_explicit_model_options_are_preserved_without_duplicate_companions(installed_language):
    settings = Settings(extractors=["quartz", {"use": "quartz-records", "min_lines": 4}, "quartz"])
    choices = [choice for choice in profile(settings).extractors if choice.use == "quartz-records"]
    assert len(choices) == 1 and choices[0].options() == {"min_lines": 4}


def test_cli_runs_the_installed_languages_automatic_model_pass(installed_language, tmp_path):
    repo = Repo(tmp_path / "consumer")
    repo.write(".dry-lint/config.toml", 'extractors = ["quartz"]\npreset = "none"\n')
    repo.write(
        "models.quartz",
        "from dataclasses import dataclass\n@dataclass\nclass Record:\n    id: str\n    amount: int\n"
        "\n@dataclass\nclass Copy:\n    id: str\n    amount: int\n",
    )
    repo.commit()
    output = tmp_path / "candidates.json"
    assert main(["detect", "--all", "--root", str(repo.root), "--out", str(output)]) == 0
    result = CandidatesFile.model_validate_json(output.read_text())
    assert result.models == 2
    assert len(result.model_candidates) == 1
    assert result.model_candidates[0].new.declaration.kind == "quartz-record"
