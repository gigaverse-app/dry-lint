import gzip
import json

import pytest

from dry_lint.cli import main
from dry_lint.detector import Detector
from dry_lint.function_index import FunctionIndex, build_index, digest, export_index, extraction_contract
from dry_lint.settings import Settings

from conftest import EXISTING, TWIN, Repo, filler_module


def test_index_roundtrip_preserves_workspace_detection_without_peer_checkouts(tmp_path):
    roots = {}
    for name, source in (("web", EXISTING), ("mobile", TWIN), ("common", filler_module())):
        repo = Repo(tmp_path / name)
        repo.write("src/text.py", source)
        repo.write("src/text.ts", "export function trim(value: string) {\n return value.trim();\n}\n")
        repo.commit()
        roots[f"org/{name}"] = repo.root
    settings = Settings()
    expected = Detector.for_workspace(roots, settings)
    indexes = []
    for name in ("org/mobile", "org/common"):
        snapshot = export_index(roots[name], name, settings)
        data = snapshot.encode()
        assert data == snapshot.encode()
        indexes.append(FunctionIndex.decode(data, name, snapshot.commit, extraction_contract(settings)))
    actual = Detector.for_workspace({"org/web": roots["org/web"]}, settings, indexes=indexes)
    assert actual.functions == expected.functions
    assert actual.scan() == expected.scan()
    assert actual.candidates(actual.functions) == expected.candidates(expected.functions)
    output = tmp_path / "mobile.json.gz"
    assert main(["index", "--root", str(roots["org/mobile"]), "--repository", "org/mobile", "--out", str(output)]) == 0
    assert output.read_bytes() == indexes[0].encode()
    assert (
        main(
            [
                "scan",
                "--root",
                str(roots["org/web"]),
                "--repo",
                f"org/web={roots['org/web']}",
                "--repo-index",
                f"org/mobile@{indexes[0].commit}={output}",
                "--judge",
                "none",
            ]
        )
        == 0
    )


def test_source_commit_scope_and_deletions_invalidate_index(repo):
    first = export_index(repo.root, "org/app", Settings())
    repo.git("mv", "src/text.py", "src/renamed.py")
    repo.write(".dry-lint.toml", 'exclude = ["src/renamed.py"]')
    repo.commit()
    second = export_index(repo.root, "org/app", Settings())
    assert second.commit != first.commit
    assert second.scope != first.scope
    assert all(f.path not in {"src/text.py", "src/renamed.py"} for f in second.functions)
    with pytest.raises(ValueError, match="commit"):
        FunctionIndex.decode(first.encode(), "org/app", second.commit, first.contract)


@pytest.mark.parametrize(
    "field,value",
    [("schema", 99), ("repository", "org/other"), ("commit", "b" * 40), ("contract", "bad"), ("digest", "bad")],
)
def test_incompatible_or_corrupt_index_is_rejected(repo, field, value):
    snapshot = export_index(repo.root, "org/app", Settings())
    data = json.loads(gzip.decompress(snapshot.encode()))
    data[field] = value
    if field != "digest":
        data["digest"] = digest({k: v for k, v in data.items() if k != "digest"})
    with pytest.raises(ValueError):
        FunctionIndex.decode(gzip.compress(json.dumps(data).encode()), "org/app", snapshot.commit, snapshot.contract)


def test_judge_policy_does_not_invalidate_extraction_but_extractor_options_do():
    original = Settings()
    policy = Settings(judge="none", fail_at=0.99, patterns=[{"members": "*", "reason": "reviewed"}])
    assert extraction_contract(original) == extraction_contract(policy)
    assert extraction_contract(original) != extraction_contract(
        Settings(extractors=[{"use": "python", "min_lines": 4}])
    )


def test_repeated_callback_names_in_distinct_scopes_roundtrip(repo):
    repo.write(
        "src/callbacks.ts",
        """
{
  const invoke = () => {
    return service.first();
  };
}
{
  const invoke = () => {
    return service.second();
  };
}
""",
    )
    repo.commit()
    index = export_index(repo.root, "org/app", Settings())
    assert len([f for f in index.functions if f.name == "invoke"]) == 2
    assert FunctionIndex.decode(index.encode(), index.repository, index.commit, index.contract) == index


@pytest.mark.parametrize("problem", ["missing-digest", "invalid-commit", "unsafe-path", "bad-origin", "duplicate"])
def test_index_rejects_invalid_source_identity(repo, problem):
    index = export_index(repo.root, "org/app", Settings())
    if problem == "missing-digest":
        with pytest.raises(ValueError, match="digest"):
            FunctionIndex.decode(gzip.compress(b"{}"), index.repository, index.commit, index.contract)
        return
    if problem == "invalid-commit":
        index.commit = "main"
    elif problem == "unsafe-path":
        index.functions[0].path = "../outside.py"
    elif problem == "bad-origin":
        index.functions[0].origin.head = "old"
    else:
        index.functions.append(index.functions[0])
    with pytest.raises(ValueError):
        FunctionIndex.decode(index.encode(), index.repository, index.commit, index.contract)


def test_index_size_limit_is_checked_before_json_parsing(repo, monkeypatch):
    index = export_index(repo.root, "org/app", Settings())
    monkeypatch.setattr("dry_lint.function_index.MAX_INDEX_BYTES", 5)
    with pytest.raises(ValueError, match="size limit"):
        FunctionIndex.decode(index.encode(), index.repository, index.commit, index.contract)


@pytest.mark.parametrize("data", [b"invalid", gzip.compress(b"{}")[0:12]])
def test_broken_compression_reports_an_invalid_index(data):
    with pytest.raises(ValueError, match="compressed"):
        FunctionIndex.decode(data, "org/app", "a" * 40, "contract")


def test_empty_corpus_is_valid_and_committed_scope_wins_over_untracked_settings(repo):
    repo.write("pyproject.toml", '[tool.dry-lint]\ninclude = ["absent/*"]')
    repo.commit()
    repo.write(".dry-lint.toml", 'include = ["*"]')
    index = export_index(repo.root, "org/app", Settings())
    assert not index.functions
    assert FunctionIndex.decode(index.encode(), index.repository, index.commit, index.contract) == index


@pytest.mark.parametrize(
    "repository,commit,path",
    [("../bad", "a" * 40, "a.py"), ("org/app", "main", "a.py"), ("org/app", "a" * 40, "../a.py")],
)
def test_build_rejects_ambiguous_source(repository, commit, path):
    with pytest.raises(ValueError):
        build_index({path: b""}, repository, commit, Settings())


def test_dirty_tracked_sources_cannot_be_published(repo):
    repo.write("src/text.py", TWIN)
    with pytest.raises(ValueError, match="Commit tracked"):
        export_index(repo.root, "org/app", Settings())


def test_detector_rejects_duplicate_repositories_and_incompatible_extraction(repo):
    index = export_index(repo.root, "org/app", Settings())
    with pytest.raises(ValueError, match="Duplicate repository"):
        Detector.for_workspace({"org/app": repo.root}, Settings(), indexes=[index])
    index.contract = "old"
    with pytest.raises(ValueError, match="contract mismatch"):
        Detector.for_workspace({"org/other": repo.root}, Settings(), indexes=[index])
    assert main(["scan", "--root", str(repo.root), "--repo-index", "invalid"]) == 2
