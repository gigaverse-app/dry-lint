"""Opt-in benchmark records ("goldens") from pull requests that settled a reported pair.

A merged pull request's ledger says how each pair it reported ended:

- **no longer reported**: excluded. A revert, rename, budget change or retrieval change can all cause absence;
  it provides no positive duplication label. Older disappearance-based labels must not train a judge.
- **dismissed**: a rule settled it after it was reported, typically a person's
  ``# dry-lint: distinct-from`` with a reason.

With ``share-goldens: "true"``, the default-branch fold writes those outcomes as pointers: repository,
pinned revision, paths, names, line spans, the judge's verdict and how the label was learned. No code
is written, and nothing is sent anywhere: the records stay an Actions artifact in the adopter's own
repository. ``scripts/collect_goldens.py`` reads them only from public repositories registered by pull
request in ``docs/goldens/adopters.toml``, and fetches the code at the pinned revision. Collected goldens
are staged panels with weak labels, kept apart from the benchmark's population estimates.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from dry_lint import __version__
from dry_lint.evidence import SourceReference
from dry_lint.ledger import PullLedger
from dry_lint.models import Verdict

ARTIFACT = "dry-lint-goldens"

# How each settled state becomes a label, and what the label rests on.
OUTCOMES: dict[str, tuple[Literal["duplicate", "separate"], str]] = {
    "dismissed": ("separate", "dismissed after it was reported (a rule, typically a person's distinct-from)"),
}


class Golden(BaseModel):
    """One settled pair, as a pointer into a public repository at a pinned revision."""

    key: str
    repository: str
    pull_request: int
    label: Literal["duplicate", "separate"]
    label_source: str
    new: SourceReference
    existing: SourceReference
    similarity: float
    verdict: Verdict | None = None
    dry_lint: str = __version__


def settled(repository: str, number: int, ledger: PullLedger) -> list[Golden]:
    """The function pairs ``number`` settled before it merged and that carry source coordinates.

    Model pairs, pairs settled by the pre-commit hook (self-reported in a commit trailer), accepted-backlog
    cleanups and pairs still open at merge are left out: none of them is an outcome on reported evidence.
    """
    found = []
    for key, pair in ledger.pairs.items():
        if pair.kind != "function" or pair.before_commit or key in ledger.backlog or pair.evidence is None:
            continue
        if pair.state not in OUTCOMES:
            continue
        label, source = OUTCOMES[pair.state]
        found.append(
            Golden(
                key=key,
                repository=repository,
                pull_request=number,
                label=label,
                label_source=source,
                new=pair.evidence.a,
                existing=pair.evidence.b,
                similarity=pair.evidence.similarity,
                verdict=pair.evidence.verdict,
            )
        )
    return found


def append(path: Path, goldens: list[Golden]) -> int:
    """Add ``goldens`` to the JSON lines file at ``path``; returns how many were written."""
    if not goldens:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.writelines(golden.model_dump_json() + "\n" for golden in goldens)
    return len(goldens)
