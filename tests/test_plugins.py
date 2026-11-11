import sys
import textwrap
from pathlib import Path

import pytest

from dry_lint.cli import main
from dry_lint.comparers import TfidfComparer
from dry_lint.dryer import DRYER_REQUIREMENT
from dry_lint.extractors import PythonExtractor
from dry_lint.judges.command import CommandJudge
from dry_lint.plugins import BUILT_IN, identity, load, plugin_class
from dry_lint.settings import PluginChoice
from dry_lint.store import DirectoryStore, S3Store

from conftest import Repo


def test_built_in_plugins_are_found_by_name() -> None:
    assert plugin_class("extractors", "python") is PythonExtractor
    assert plugin_class("comparers", "tfidf") is TfidfComparer
    assert plugin_class("judges", "command") is CommandJudge
    assert (plugin_class("stores", "dir"), plugin_class("stores", "s3")) == (DirectoryStore, S3Store)
    assert set(BUILT_IN) == {"extractors", "comparers", "judges", "stores"}


def test_load_passes_the_options_and_lets_settings_override_defaults() -> None:
    comparer = load("comparers", PluginChoice(use="tfidf", min_similarity=0.4), min_similarity=0.9, max_df=0.2)
    assert (comparer.min_similarity, comparer.max_df) == (0.4, 0.2)
    assert identity(comparer) == "tfidf:2"


@pytest.fixture
def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A real installed distribution that registers a comparer under the dry_lint.comparers entry point."""
    (tmp_path / "shingles.py").write_text(
        textwrap.dedent("""
        class ShingleComparer:
            name, version = "shingles", "3"

            def __init__(self, size=2):
                self.size = size
    """)
    )
    info = tmp_path / "shingles-0.1.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: shingles\nVersion: 0.1\n")
    (info / "entry_points.txt").write_text("[dry_lint.comparers]\nshingles = shingles:ShingleComparer\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    yield
    sys.modules.pop("shingles", None)


def test_installed_plugins_are_found_by_their_entry_point(installed) -> None:
    comparer = load("comparers", PluginChoice(use="shingles", size=4))
    assert (identity(comparer), comparer.size) == ("shingles:3", 4)


def test_an_unknown_plugin_names_what_is_available(installed) -> None:
    with pytest.raises(
        ValueError,
        match="Unknown comparer 'minhash'; available: cpu-embedding, cpu-tail-rrf, dryer, model-shape, operation-blocks, shingles, tfidf",
    ):
        plugin_class("comparers", "minhash")


def test_missing_dryer_explains_installation(repo: Repo, monkeypatch, capsys) -> None:
    # Dryer is optional and absent from the default environment; selecting it must say how to install it.
    monkeypatch.setitem(sys.modules, "dryer.extract", None)
    assert main(["scan", "--root", str(repo.root), "--detector", "dryer"]) == 2
    assert f"pip install '{DRYER_REQUIREMENT}'" in capsys.readouterr().err
