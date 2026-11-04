"""
The verdict store: one record per pair a judge has decided, so the same question is not asked twice.

It is a cache of machine answers, not a reviewed file: keep it outside the repository. Losing it only means
re-judging. Each record is its own object, named by the pair's key, so concurrent judge jobs never conflict and a
run reads only the records of the pairs it has. A record is reused when the answer cannot have changed:

- both structure hashes match (comments, formatting and renames do not change them); or
- the verdict was "separate", the comparer permits similarity reuse (`similarity_reusable`; no built-in one does,
  since their scores do not see literals), the similarity comes from the same comparer version, and the pair is
  not more than `reopen_margin` closer than when it was judged.

A duplicate verdict reopens on any logic change, because that change may be the fix, or more drift. A verdict
from a different judge is never reused; one from an older version of the same judge is, until a backlog run with
`--refresh` asks again.

Beside the records, the store keeps what judging has cost each pull request so far (`spent-*` objects), so a
budget covers all of a pull request's pushes.
"""

import hashlib
import os
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

from pydantic import BaseModel, Field

from dry_lint.models import Candidate, Run, Verdict, Versioned
from dry_lint.plugins import StoreBackend


class Record(Versioned):
    """A verdict, with the state of the pair when it was judged: the store's file format."""

    key: str
    pair: tuple[str, str] = Field(description="Both qualified names, sorted.")
    hashes: tuple[str, str] = Field(description="Their structure hashes, in the same order.")
    comparer: str = Field(description="The comparer and version that measured `similarity`.")
    similarity: float
    similarity_reusable: bool = False
    context_hash: str = ""
    verdict: Verdict
    judged_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    source: Run | None = Field(default=None, description="The run that asked, for tracing a verdict back.")


class Spent(BaseModel):
    """What judging has cost one pull request so far, across its runs."""

    repository: str
    pull_request: int
    usd: float = 0.0
    runs: int = 0


SPENT_PREFIX = "spent-"


def spent_key(run: Run) -> str:
    return f"{SPENT_PREFIX}{hashlib.sha256(f'{run.repository}#{run.pull_request}'.encode()).hexdigest()[:16]}"


class Lookup(NamedTuple):
    verdict: Verdict | None
    why: str


class DirectoryStore:
    """Records as `<key>.json` files in a folder."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def get(self, key: str) -> bytes | None:
        target = self.path / f"{key}.json"
        return target.read_bytes() if target.exists() else None

    def put(self, key: str, data: bytes) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=self.path, suffix=".tmp")
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        os.replace(temporary, self.path / f"{key}.json")

    def keys(self) -> Iterator[str]:
        return iter(sorted(p.stem for p in self.path.glob("*.json"))) if self.path.exists() else iter(())


class S3Store:
    """Records as `<prefix><key>.json` objects in a bucket. Needs boto3: `pip install dry-lint[s3]`."""

    def __init__(self, uri: str, client: Any = None) -> None:
        if not uri.startswith("s3://"):
            raise ValueError(f"The s3 store needs an s3:// uri, not {uri!r}")
        self.bucket, _, prefix = uri.removeprefix("s3://").partition("/")
        self.prefix = prefix if not prefix or prefix.endswith("/") else prefix + "/"
        if client is None:
            import boto3  # optional: only this backend needs it

            client = boto3.client("s3")
        self.client = client

    def get(self, key: str) -> bytes | None:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=f"{self.prefix}{key}.json")["Body"].read()
        except self.client.exceptions.NoSuchKey:
            return None

    def put(self, key: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=f"{self.prefix}{key}.json", Body=data,
                               ContentType="application/json")

    def keys(self) -> Iterator[str]:
        for page in self.client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=self.prefix):
            for item in page.get("Contents", []):
                name = item["Key"].removeprefix(self.prefix)
                if name.endswith(".json") and "/" not in name:
                    yield name.removesuffix(".json")


class VerdictStore:
    def __init__(self, backend: StoreBackend) -> None:
        self.backend = backend

    def record(self, key: str) -> Record | None:
        data = self.backend.get(key)
        return Record.model_validate_json(data) if data is not None else None

    def records(self) -> Iterator[Record]:
        for key in self.backend.keys():
            if key.startswith(SPENT_PREFIX):
                continue
            record = self.record(key)
            if record is not None:
                yield record

    def spent(self, run: Run | None) -> float:
        """What earlier runs on this run's pull request spent on judging; 0 outside a pull request."""
        if run is None or run.pull_request is None:
            return 0.0
        data = self.backend.get(spent_key(run))
        return Spent.model_validate_json(data).usd if data is not None else 0.0

    def add_spent(self, run: Run | None, usd: float) -> None:
        if run is None or run.pull_request is None or usd <= 0:
            return
        data = self.backend.get(spent_key(run))
        spent = (Spent.model_validate_json(data) if data is not None
                 else Spent(repository=run.repository, pull_request=run.pull_request))
        spent = spent.model_copy(update={"usd": spent.usd + usd, "runs": spent.runs + 1})
        self.backend.put(spent_key(run), spent.model_dump_json().encode())

    def lookup(self, candidate: Candidate, judge: str, reopen_margin: float, version: str | None = None,
               escalation: str | None = None, band: tuple[float, float] = (0.0, 0.0)) -> Lookup:
        """
        The stored verdict if it still holds for the pair as it is now, and why it does or does not. With a second
        judge (`escalation`, its identity, re-judging first scores in `band`), a verdict holds only if this judging
        would have given it: a second opinion from that same judge, or a first answer it would not have re-judged.
        """
        record = self.record(candidate.key)
        if record is None:
            return Lookup(None, "never judged")
        verdict = record.verdict
        if record.context_hash != candidate.context_hash:
            return Lookup(None, "source context or consolidation policy changed")
        if verdict.judge != judge:
            return Lookup(None, f"judged by {verdict.judge}, not {judge}")
        if version is not None and verdict.judge_version != version:
            return Lookup(None, f"judged by {judge} {verdict.judge_version}, not {version}")
        if verdict.second_opinion is not None and verdict.second_opinion != escalation:
            return Lookup(None, f"second opinion from {verdict.second_opinion}, not {escalation or 'no second judge'}")
        if verdict.second_opinion is None and escalation and band[0] <= verdict.score < band[1]:
            return Lookup(None, f"{escalation} re-judges first scores in [{band[0]:g}, {band[1]:g}), and never saw this one")
        then = dict(zip(record.pair, record.hashes))
        now = {candidate.new.qualname: candidate.new.hash, candidate.existing.qualname: candidate.existing.hash}
        if then == now:
            return Lookup(verdict, "neither function's logic changed")
        if verdict.label != "separate":
            return Lookup(None, f"judged {verdict.label}, and the logic changed since")
        if record.comparer != candidate.comparer:
            return Lookup(None, f"the logic changed, and the similarity then came from {record.comparer}")
        # A lossy structural metric cannot establish that changed code still implements separate concepts.
        if not (record.similarity_reusable and candidate.similarity_reusable):
            return Lookup(None, "the logic changed, and the comparer requires exact-hash reuse")
        if candidate.similarity > record.similarity + reopen_margin:
            return Lookup(None, f"judged separate at similarity {record.similarity:.2f}; now {candidate.similarity:.2f}")
        return Lookup(verdict, "judged separate, and the pair is no closer")

    def remember(self, candidate: Candidate, verdict: Verdict, source: Run | None = None) -> Record:
        sides = sorted([(candidate.new.qualname, candidate.new.hash), (candidate.existing.qualname, candidate.existing.hash)])
        record = Record(key=candidate.key, pair=(sides[0][0], sides[1][0]), hashes=(sides[0][1], sides[1][1]),
                        comparer=candidate.comparer, similarity=candidate.similarity, verdict=verdict, source=source,
                        similarity_reusable=candidate.similarity_reusable, context_hash=candidate.context_hash)
        self.backend.put(record.key, record.model_dump_json().encode())
        return record
