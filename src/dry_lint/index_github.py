"""Fetch trusted, immutable peer indexes; rebuild unavailable snapshots from verified Git blobs."""

import base64
import hashlib
import io
import tarfile
import zipfile
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from dry_lint.function_index import (
    MAX_INDEX_BYTES,
    FunctionIndex,
    build_index,
    extraction_contract,
    repository_name,
    source_path,
)
from dry_lint.functions import extractor_for
from dry_lint.plugins import load
from dry_lint.settings import Settings

PUBLISHER = ".github/workflows/dry-lint-index.yml"


@dataclass
class FetchedIndex:
    index: FunctionIndex
    source: str
    transferred: int

    def receipt(self) -> str:
        index = self.index
        return (f"| `{index.repository}` | `{index.commit}` | {len(index.functions):,} | "
                f"{self.source} | {self.transferred:,} |")


class IndexClient:
    def __init__(self, token: str, api: str = "https://api.github.com", transport: httpx.BaseTransport | None = None):
        self.client = httpx.Client(base_url=api.rstrip("/") + "/", headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}, transport=transport, timeout=120, follow_redirects=True)
        self.transferred = 0

    def close(self) -> None:
        self.client.close()

    def download(self, path: str) -> bytes:
        buffer = io.BytesIO()
        with self.client.stream("GET", path) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                self.transferred += len(chunk)
                if buffer.tell() + len(chunk) > MAX_INDEX_BYTES:
                    raise ValueError("Index download exceeds size limit")
                buffer.write(chunk)
        return buffer.getvalue()

    def json(self, path: str) -> dict:
        import json
        return json.loads(self.download(path))

    def fetch(self, repository: str, ref: str, settings: Settings) -> FetchedIndex:
        repository_name(repository)
        if not ref or any(c in ref for c in "\r\n"):
            raise ValueError("A peer index requires a trusted ref")
        start = self.transferred
        prefix = f"repos/{repository}"
        commit = self.json(f"{prefix}/commits/{quote(ref, safe='')}")
        sha, tree = commit["sha"], commit["commit"]["tree"]["sha"]
        contract = extraction_contract(settings)
        name = FunctionIndex(repository=repository, commit=sha, contract=contract, scope={}, functions=[]).artifact_name
        index = self.artifact(prefix, repository, ref, sha, contract, name)
        source = "published artifact"
        if index is None:
            source = "source archive fallback (no compatible trusted artifact)"
            index = self.rebuild(prefix, repository, sha, tree, settings)
        return FetchedIndex(index, source, self.transferred - start)

    def artifact(self, prefix: str, repository: str, ref: str, sha: str, contract: str, name: str) -> FunctionIndex | None:
        page = 1
        while True:
            try:
                listing = self.json(f"{prefix}/actions/artifacts?name={name}&per_page=100&page={page}")
            except httpx.HTTPStatusError as error:
                if error.response.status_code in (403, 404):
                    return None
                raise
            for artifact in listing["artifacts"]:
                run = artifact.get("workflow_run") or {}
                if (artifact["expired"] or artifact["name"] != name or run.get("head_sha") != sha
                        or not run.get("repository_id") or run.get("repository_id") != run.get("head_repository_id")):
                    continue
                provenance = self.json(f"{prefix}/actions/runs/{int(run['id'])}")
                if (provenance.get("path") != PUBLISHER or provenance.get("head_sha") != sha
                        or provenance.get("head_branch") != ref or provenance.get("event") not in {"push", "schedule", "workflow_dispatch"}
                        or provenance.get("status") != "completed" or provenance.get("conclusion") != "success"
                        or (provenance.get("head_repository") or {}).get("full_name") != repository):
                    continue
                try:
                    raw = self.download(f"{prefix}/actions/artifacts/{int(artifact['id'])}/zip")
                    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                        info = archive.getinfo("functions.json.gz")
                        if info.file_size > MAX_INDEX_BYTES or len(archive.namelist()) != 1:
                            raise ValueError("Invalid function index artifact contents")
                        data = archive.read(info)
                    return FunctionIndex.decode(data, repository, sha, contract)
                except (ValueError, OSError, EOFError, KeyError, zipfile.BadZipFile):
                    continue
                except httpx.HTTPStatusError as error:
                    if error.response.status_code not in (404, 410):
                        raise
            if page * 100 >= listing["total_count"]:
                return None
            page += 1

    def rebuild(self, prefix: str, repository: str, sha: str, tree: str, settings: Settings) -> FunctionIndex:
        listing = self.json(f"{prefix}/git/trees/{tree}?recursive=1")
        if listing.get("truncated"):
            raise ValueError(f"Cannot rebuild {repository}: GitHub returned an incomplete source tree")
        extractors = [load("extractors", choice) for choice in settings.extractors]
        expected = {entry["path"]: entry["sha"] for entry in listing["tree"]
                    if entry["type"] == "blob" and entry["mode"] in {"100644", "100755"}
                    and (entry["path"] in {".dry-lint.toml", "pyproject.toml"} or extractor_for(entry["path"], extractors))}
        if not all(source_path(path) for path in expected):
            raise ValueError("Unsafe source tree path")
        sources = {}
        with tarfile.open(fileobj=io.BytesIO(self.download(f"{prefix}/tarball/{sha}")), mode="r:gz") as archive:
            total = 0
            for member in archive:
                path = member.name.partition("/")[2]
                if path not in expected or not member.isfile():
                    continue
                total += member.size
                if total > MAX_INDEX_BYTES:
                    raise ValueError("Source archive exceeds extraction size limit")
                data = archive.extractfile(member).read()
                if blob_hash(data) == expected[path]:
                    sources[path] = data
        # export-ignore/export-subst and LFS archive settings must not change the committed source corpus.
        for path, blob in expected.items():
            if path not in sources:
                response = self.json(f"{prefix}/git/blobs/{blob}")
                if response.get("encoding") != "base64":
                    raise ValueError("Expected a base64 Git blob")
                data = base64.b64decode(response["content"])
                if blob_hash(data) != blob:
                    raise ValueError("Source blob digest mismatch")
                sources[path] = data
        return build_index(sources, repository, sha, settings)


def blob_hash(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
