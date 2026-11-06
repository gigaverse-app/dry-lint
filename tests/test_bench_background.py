import gzip
import json
from pathlib import Path

import pytest

from dry_lint.bench_background import BenchBackground
from dry_lint.function_index import digest
from dry_lint.index import TfidfIndex
from dry_lint.models import Function
from dry_lint.settings import Settings

from conftest import Repo, run_main  # pyright: ignore[reportImplicitRelativeImport]  # pytest adds tests/ to sys.path.


def background() -> tuple[BenchBackground, list[list[str]]]:
    documents = [
        ["call:read", "w:snapshot", "w:snapshot", "w:common"],
        ["call:read", "w:snapshot", "w:common"],
        *[[f"w:other{i}", "w:common"] for i in range(8)],
    ]
    functions = [
        Function(path=f"{i}.py", name="run", line=1, end_line=1, code="def run(): pass", tokens=tokens)
        for i, tokens in enumerate(documents)
    ]
    return BenchBackground.capture(functions, "org/repo", "a" * 40, Settings()), documents


def test_frozen_background_replays_full_corpus_weights_and_competitor_ranks() -> None:
    frozen, documents = background()
    restored = BenchBackground.decode(frozen.encode())
    expected, actual = TfidfIndex(documents), restored.index()
    assert actual.idf == expected.idf
    assert "w:common" not in actual.idf
    for query in documents:
        assert actual.vector(query) == expected.vector(query)
        assert actual.similar(query) == expected.similar(query)
    assert restored.document_frequency["w:common"] == len(documents)
    assert restored.documents[0].counts["w:snapshot"] == 2
    assert frozen.encode() == frozen.encode()
    # Pair-only IDF would discard both terms shared by these two functions.
    assert TfidfIndex(documents[:2]).idf != actual.idf


@pytest.mark.parametrize("change", ["counts", "frequency", "schema", "digest"])
def test_changed_background_cannot_silently_redefine_a_golden(change: str) -> None:
    frozen, _ = background()
    payload = json.loads(gzip.decompress(frozen.encode()))
    if change == "counts":
        payload["documents"][0]["counts"]["w:snapshot"] = 0
    elif change == "frequency":
        payload["document_frequency"]["w:snapshot"] += 1
    elif change == "schema":
        payload["schema"] = 99
    else:
        payload["digest"] = "bad"
    if change != "digest":
        payload["digest"] = digest({k: v for k, v in payload.items() if k != "digest"})
    with pytest.raises(ValueError):
        BenchBackground.decode(gzip.compress(json.dumps(payload).encode()))


def test_capture_uses_pinned_repository_scope_instead_of_current_checkout(
    repo: Repo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo.write(".dry-lint.toml", 'exclude = ["tests/*"]')
    repo.write("tests/noise.py", "def noisy():\n    return noise.read()\n")
    repo.commit()
    revision = repo.git("rev-parse", "HEAD")
    repo.write(".dry-lint.toml", 'exclude = ["src/*"]')
    output = tmp_path / "background.json.gz"
    run_main(
        monkeypatch,
        "freeze_bench_background.py",
        "--root",
        str(repo.root),
        "--repository",
        "org/app",
        "--revision",
        revision,
        "--out",
        str(output),
    )
    frozen = BenchBackground.decode(output.read_bytes())
    assert frozen.scope["exclude"] == ["tests/*"]
    assert frozen.documents and all(d.id.startswith("src/") for d in frozen.documents)
    assert "call:read" not in frozen.document_frequency


@pytest.mark.parametrize("encoded", [b"invalid", gzip.compress(b"{}")[0:12]])
def test_broken_background_compression_reports_a_validation_error(encoded: bytes) -> None:
    with pytest.raises(ValueError, match="compressed"):
        BenchBackground.decode(encoded)
