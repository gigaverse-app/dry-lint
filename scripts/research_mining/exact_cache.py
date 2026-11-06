"""Disposable, trusted-local extraction cache. Never a verdict or source authority."""

import hashlib
import json
import os
import platform
import re
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path

import dry_lint
from dry_lint.extractors import PythonExtractor
from dry_lint.models import Function, validated_repository_path
from dry_lint.typescript import TypeScriptExtractor

SCHEMA = 1


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()


def implementation_digest(root: Path) -> str:
    return sha(canonical([(str(p.relative_to(root)), sha(p.read_bytes())) for p in sorted(root.rglob("*.py"))]))


def extraction_contract() -> dict:
    """Conservatively invalidate on code, extractor defaults, parser, ABI or runtime changes."""
    return {
        "schema": SCHEMA,
        "code": implementation_digest(Path(dry_lint.__file__).parent),
        "tool": implementation_digest(Path(__file__).parent),
        "runtime": [sys.version, sys.implementation.name, sys.implementation.cache_tag, platform.platform()],
        "packages": {
            name: version(name) for name in ("tree-sitter", "tree-sitter-typescript", "pydantic", "pydantic-core")
        },
        "extractors": [[ex.name, ex.version, ex().min_lines] for ex in (PythonExtractor, TypeScriptExtractor)],
    }


def extractor(path: str):
    validated_repository_path(path)
    if path.endswith(".py"):
        return PythonExtractor()
    if path.endswith((".ts", ".tsx", ".mts", ".cts")):
        return TypeScriptExtractor()
    raise ValueError("Unsupported source suffix")


def function_data(function: Function) -> dict:
    # Function.model_dump intentionally excludes these fields in production artifacts.
    # Extraction replay must preserve them, including None versus empty calls.
    return dict(function.model_dump(mode="json"), tokens=function.tokens, calls=function.calls)


def atomic_json(path: Path, value, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(canonical(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
            if exclusive:
                # Same-directory hard link publishes complete bytes without replacing any winner.
                os.link(temporary, path)
            else:
                os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


class ExactCache:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.contract = extraction_contract()
        self.hits = self.parses = self.corruptions = 0

    def extract(self, repository: str, revision: str, path: str, raw: bytes) -> list[Function]:
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("Full immutable SHA-1 commit required")
        ex = extractor(path)
        identity = dict(
            schema=SCHEMA,
            repository=repository,
            revision=revision,
            path=path,
            source_sha256=sha(raw),
            contract=self.contract,
        )
        target = self.directory / (sha(canonical(identity)) + ".json")
        try:
            obj = json.loads(target.read_bytes())
            if (
                canonical(obj["identity"]) != canonical(identity)
                or sha(canonical(obj["functions"])) != obj["functions_sha256"]
            ):
                raise ValueError("Cache identity/checksum mismatch")
            functions = [Function.model_validate(f) for f in obj["functions"]]
            if canonical([function_data(f) for f in functions]) != canonical(obj["functions"]):
                raise ValueError("Incomplete extraction payload")
            self.hits += 1
            return functions
        except FileNotFoundError:
            pass
        except (ValueError, KeyError, TypeError, OSError):
            # No unlink: it could delete a concurrent writer's freshly repaired entry.
            self.corruptions += 1
        source = raw.decode("utf-8")
        ex.validate_source(path, source)  # validate the ENTIRE file before extracting any node
        functions = ex.functions(path, source)
        for function in functions:
            function.hash = ex.structure_hash(function)
        self.parses += 1
        payload = [function_data(f) for f in functions]
        atomic_json(target, dict(identity=identity, functions=payload, functions_sha256=sha(canonical(payload))))
        return functions
