"""scripts/collect_goldens.py: registered public repositories only, code fetched at the pinned revision."""

import importlib.util
import io
import zipfile
from pathlib import Path

import httpx

from dry_lint.bench import load_gold
from dry_lint.evidence import SourceReference
from dry_lint.goldens import Golden

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("collect_goldens", ROOT / "scripts" / "collect_goldens.py")
collect = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collect)

REVISION = "a" * 40
SOURCE = (
    "class Cut:\n    def clip(self, text):\n        return text[:10]\n\n\ndef shorten(text):\n    return text[:10]\n"
)


def golden(repository: str = "acme/shop", pull_request: int = 3, label: str = "duplicate") -> Golden:
    def side(name: str, line: int, end: int, owner: str | None = None) -> SourceReference:
        return SourceReference(
            repository=repository, revision=REVISION, path="src/cut.py", name=name, owner=owner, line=line, end_line=end
        )

    return Golden(
        key="k",
        repository=repository,
        pull_request=pull_request,
        label=label,
        label_source="kept out before merge (inferred)",
        new=side("clip", 2, 3, "Cut"),
        existing=side("shorten", 6, 7),
        similarity=0.7,
    )


def archive(*goldens: Golden) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("goldens.jsonl", "".join(g.model_dump_json() + "\n" for g in goldens))
    return buffer.getvalue()


def github(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/repos/acme/shop/actions/artifacts":
        artifacts = [
            {"name": "dry-lint-goldens-1-1", "expired": False, "archive_download_url": "https://api.github.com/zip/1"},
            {"name": "dry-lint-goldens-2-1", "expired": True, "archive_download_url": "https://api.github.com/zip/2"},
            {"name": "dry-lint-candidates", "expired": False, "archive_download_url": "https://api.github.com/zip/3"},
        ]
        return httpx.Response(200, json={"artifacts": artifacts})
    if path == "/zip/1":
        # A later pull request's label wins, and a record about another repository is ignored.
        return httpx.Response(200, content=archive(golden(), golden(pull_request=5, label="separate"), golden("x/y")))
    if path == f"/acme/shop/{REVISION}/src/cut.py":
        return httpx.Response(200, text=SOURCE)
    return httpx.Response(404)


def test_artifacts_keep_this_repositorys_latest_label_per_pair() -> None:
    with httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(github)) as client:
        [found] = collect.artifacts(client, "acme/shop")
    assert (found.repository, found.pull_request, found.label) == ("acme/shop", 5, "separate")


def test_the_panel_holds_exact_excerpts_and_loads_as_gold(tmp_path: Path) -> None:
    with httpx.Client(transport=httpx.MockTransport(github)) as raw:
        text, written = collect.panel("acme/shop", "Apache-2.0", [golden()], raw)
    assert written == 1
    path = tmp_path / "panel.toml"
    path.write_text(text, encoding="utf-8")
    [pair] = load_gold(path)
    assert pair.label == "duplicate"
    assert pair.new.id == "src/cut.py::Cut.clip" and pair.new.code == "def clip(self, text):\n    return text[:10]\n"
    assert pair.existing.code == "def shorten(text):\n    return text[:10]\n"
    assert f"/blob/{REVISION}/src/cut.py#L2-L3" in text and "Apache-2.0" in text


def test_a_revision_that_cannot_be_read_contributes_nothing() -> None:
    missing = golden()
    missing.new.path = "src/gone.py"
    with httpx.Client(transport=httpx.MockTransport(github)) as raw:
        assert collect.panel("acme/shop", "Apache-2.0", [missing], raw)[1] == 0
