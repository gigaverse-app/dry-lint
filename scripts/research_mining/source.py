"""Read immutable source from caller-supplied local Git repositories; never execute it."""

import re
import subprocess
from pathlib import Path

from dry_lint.models import Candidate, validated_repository_path

from .exact_cache import ExactCache, sha


def git(root: Path, *args: str) -> bytes:
    try:
        return subprocess.check_output(
            ["git", "--no-replace-objects", "-C", str(root), *args],
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as error:
        raise ValueError("Pinned Git source unavailable") from error


def validate_sources(packet: dict, candidate: Candidate, root: Path, cache: ExactCache) -> list[dict]:
    source_proofs = packet.get("source_proofs")
    if not isinstance(source_proofs, list) or any(not isinstance(proof, dict) for proof in source_proofs):
        raise ValueError("source_proofs must be a list of objects")
    revision = packet["revision"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Full immutable SHA-1 commit required")
    if git(root, "rev-parse", revision + "^{commit}").decode().strip() != revision:
        raise ValueError("Pin must identify the exact commit")
    checks = []
    for side in ("new", "existing"):
        endpoint = getattr(candidate, side)
        path = validated_repository_path(endpoint.path)
        if endpoint.origin is not None:
            raise ValueError("Cross-repository endpoints require a separate source contract")
        proofs = [p for p in source_proofs if p.get("source_id") == endpoint.qualname]
        if len(proofs) != 1:
            raise ValueError("Missing or ambiguous full-file source proof")
        raw = git(root, "cat-file", "blob", revision + ":" + path)
        if proofs[0].get("file_sha256") != sha(raw):
            raise ValueError("Pinned full-file digest mismatch")
        functions = cache.extract(packet["repository"], revision, path, raw)
        matches = [f for f in functions if f.qualname == endpoint.qualname]
        if len(matches) != 1:
            raise ValueError("Missing or ambiguous native endpoint")
        native = matches[0]
        if (native.code, native.line, native.end_line) != (endpoint.code, endpoint.line, endpoint.end_line):
            raise ValueError("Endpoint body/coordinates mismatch")
        if endpoint.hash and endpoint.hash != native.hash:
            raise ValueError("Endpoint structure hash mismatch")
        if endpoint.analysis is not None and endpoint.analysis != native.analysis:
            raise ValueError("Endpoint language analysis mismatch")
        if endpoint.bases != native.bases or endpoint.declaration != native.declaration:
            raise ValueError("Endpoint declaration/bases mismatch")
        checks.append(dict(side=side, path=path, source_id=endpoint.qualname, file_sha256=sha(raw)))
    return checks


def lexical_hints(candidate: Candidate) -> list[dict]:
    """Exact stripped-line runs inside verified endpoints, for navigation only."""
    from difflib import SequenceMatcher

    endpoints = [candidate.new, candidate.existing]
    lines = [
        [
            (i, line.strip())
            for i, line in enumerate(f.code.splitlines())
            if line.strip() and not line.lstrip().startswith(("#", "//", "*"))
        ]
        for f in endpoints
    ]
    matcher = SequenceMatcher(None, [s for _, s in lines[0]], [s for _, s in lines[1]], autojunk=False)
    hints = []
    for a, b, size in matcher.get_matching_blocks():
        if size < 3:
            continue
        spans = []
        for side, endpoint, sequence, offset in zip(("new", "existing"), endpoints, lines, (a, b), strict=True):
            first, last = sequence[offset][0], sequence[offset + size - 1][0]
            spans.append(dict(side=side, start_line=endpoint.line + first, end_line=endpoint.line + last))
        hints.append(dict(kind="lexical_navigation_only", spans=spans, semantic_operation_verified=False))
    return hints
