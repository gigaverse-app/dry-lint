"""Portable extraction snapshots. Candidate ranking and judging remain consumer-side decisions."""

import gzip
import hashlib
import io
import json
import re
import subprocess
import sys
import tomllib
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from dry_lint.functions import extractor_for, selected_path
from dry_lint.git import git
from dry_lint.models import Function, Run, repository_path
from dry_lint.plugins import identity, load
from dry_lint.settings import Settings

INDEX_SCHEMA = 2
MAX_INDEX_BYTES = 256 * 1024 * 1024
REPOSITORY = re.compile(r"[\w-][\w.-]*/[\w-][\w.-]*", re.ASCII)
COMMIT = re.compile(r"[0-9a-f]{40}")


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def encode_snapshot(payload: dict[str, Any], *, sort_keys: bool = True) -> bytes:
    """Shared envelope for extraction indexes and sparse benchmark backgrounds."""
    return gzip.compress(
        json.dumps({**payload, "digest": digest(payload)}, sort_keys=sort_keys, separators=(",", ":")).encode(), mtime=0
    )


def decode_snapshot(data: bytes, label: str) -> dict[str, Any]:
    """Bound decompression and verify integrity before the caller validates its schema."""
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
            raw = compressed.read(MAX_INDEX_BYTES + 1)
    except (OSError, EOFError) as error:
        raise ValueError(f"Invalid compressed {label}") from error
    if len(raw) > MAX_INDEX_BYTES:
        raise ValueError(f"{label.capitalize()} exceeds decompressed size limit")
    payload = json.loads(raw)
    if not isinstance(payload, dict) or "digest" not in payload:
        raise ValueError(f"Missing {label} digest")
    checksum = payload.pop("digest")
    if checksum != digest(payload):
        raise ValueError(f"{label.capitalize()} content digest mismatch")
    return payload


def repository_name(value: str) -> str:
    if not REPOSITORY.fullmatch(value):
        raise ValueError(f"Invalid repository name: {value!r}; use OWNER/NAME")
    return value


def extraction_contract(settings: Settings) -> str:
    modules = ("function_index", "functions", "extractors", "typescript", "source_context", "models", "model_shapes")
    implementation = {
        name: Path(import_module(f"dry_lint.{name}").__file__).read_text(encoding="utf-8") for name in modules
    }
    plugins = [load("extractors", choice) for choice in settings.extractors]
    return digest(
        {
            "schema": INDEX_SCHEMA,
            "implementation": implementation,
            "default_scope": {"include": Settings().include, "exclude": Settings().exclude},
            "python": list(sys.version_info[:2]),
            "platform": sys.platform,
            "parsers": {name: version(name) for name in ("tree-sitter", "tree-sitter-typescript")},
            "extractors": [
                {"choice": choice.model_dump(), "identity": identity(plugin), "files": plugin.files}
                for choice, plugin in zip(settings.extractors, plugins, strict=True)
            ],
        }
    )


class IndexedFunction(Function):
    tokens: list[str] = Field(default_factory=list)
    calls: list[str] | None = None


class FunctionIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["dry-lint/function-index"] = "dry-lint/function-index"
    schema_version: Literal[1, 2] = Field(default=INDEX_SCHEMA, alias="schema")
    repository: str
    commit: str
    contract: str
    scope: dict[str, list[str]]
    functions: list[IndexedFunction]

    @property
    def artifact_name(self) -> str:
        return f"dry-lint-index-v{self.schema_version}-{self.contract}-{self.commit}"

    def encode(self) -> bytes:
        return encode_snapshot(self.model_dump(mode="json", by_alias=True))

    @classmethod
    def decode(cls, data: bytes, repository: str, commit: str, contract: str) -> "FunctionIndex":
        index = cls.model_validate(decode_snapshot(data, "function index"))
        for field, expected in (
            ("repository", repository_name(repository)),
            ("commit", commit),
            ("contract", contract),
        ):
            if getattr(index, field) != expected:
                raise ValueError(f"Function index {field} mismatch for {repository}")
        if not COMMIT.fullmatch(index.commit):
            raise ValueError("Function index requires an exact source commit")
        seen = set()
        for function in index.functions:
            if (
                not repository_path(function.path)
                or function.line < 1
                or function.end_line < function.line
                or function.origin != Run(repository=repository, head=commit)
            ):
                raise ValueError("Invalid function source identity")
            identity = (function.qualname, function.line, function.end_line)
            if identity in seen:
                raise ValueError(f"Duplicate indexed function: {function.qualname}")
            seen.add(identity)
        return index

    def extracted(self) -> list[Function]:
        return [Function.model_validate(f.model_dump()) for f in self.functions]


def source_settings(sources: dict[str, bytes]) -> Settings:
    if ".dry-lint.toml" in sources:
        return Settings.model_validate(tomllib.loads(sources[".dry-lint.toml"].decode("utf-8")))
    if "pyproject.toml" in sources:
        data = tomllib.loads(sources["pyproject.toml"].decode("utf-8"))
        return Settings.model_validate(data.get("tool", {}).get("dry-lint", {}))
    return Settings()


def build_index(sources: dict[str, bytes], repository: str, commit: str, settings: Settings) -> FunctionIndex:
    repository_name(repository)
    if not COMMIT.fullmatch(commit):
        raise ValueError("Function index requires an exact source commit")
    source = source_settings(sources)
    extractors = [load("extractors", choice) for choice in settings.extractors]
    functions = []
    for path, data in sorted(sources.items()):
        if not repository_path(path):
            raise ValueError(f"Unsafe source path: {path!r}")
        extractor = extractor_for(path, extractors)
        if not extractor or not selected_path(path, source.include, source.exclude):
            continue
        text = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        for function in extractor.functions(path, text):
            functions.append(IndexedFunction(**function.model_dump(), tokens=function.tokens, calls=function.calls))
            functions[-1].origin = Run(repository=repository, head=commit)
    return FunctionIndex(
        repository=repository,
        commit=commit,
        contract=extraction_contract(settings),
        scope={"include": source.include, "exclude": source.exclude},
        functions=functions,
    )


def tree_blobs(root: Path, revision: str, settings: Settings) -> dict[str, bytes]:
    """Read supported source blobs without checking out or executing the tree, including an index tree."""
    listing = git(root, "ls-tree", "-rz", "--full-tree", revision)
    entries = [entry.split("\t", 1) for entry in listing.split("\0") if entry]
    extractors = [load("extractors", choice) for choice in settings.extractors]
    blobs = [
        (meta.split()[2], path)
        for meta, path in entries
        if meta.startswith("100") and (path in (".dry-lint.toml", "pyproject.toml") or extractor_for(path, extractors))
    ]
    request = "".join(f"{sha}\n" for sha, _ in blobs).encode()
    result = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch"], input=request, capture_output=True, check=True
    )
    stream, sources = io.BytesIO(result.stdout), {}
    for _, path in blobs:
        size = int(stream.readline().split()[2])
        sources[path] = stream.read(size)
        stream.read(1)
    return sources


def export_index(root: Path, repository: str, settings: Settings) -> FunctionIndex:
    if git(root, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("Commit tracked changes before publishing a function index")
    commit = git(root, "rev-parse", "HEAD")
    return build_index(tree_blobs(root, commit, settings), repository, commit, settings)
