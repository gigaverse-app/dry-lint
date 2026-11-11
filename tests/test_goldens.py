"""share-goldens: which settled pairs become benchmark pointers, and which never do."""

from pathlib import Path

from dry_lint.evidence import PairEvidence, SourceReference
from dry_lint.goldens import Golden, append, settled
from dry_lint.ledger import Backlog, Pair, PullLedger

REVISION = "a" * 40


def side(name: str) -> SourceReference:
    return SourceReference(
        repository="acme/shop", revision=REVISION, path=f"src/{name}.py", name=name, line=3, end_line=9
    )


def pair(state: str, **overrides) -> Pair:
    fields = {
        "new": "clip",
        "existing": "shorten",
        "found": 1,
        "state": state,
        "settled": 2,
        "evidence": PairEvidence(a=side("clip"), b=side("shorten"), similarity=0.6),
    }
    return Pair(**{**fields, **overrides})


def test_only_dismissed_pairs_become_labels_and_absence_is_excluded() -> None:
    ledger = PullLedger(pairs={"k": pair("kept-out"), "d": pair("dismissed")})
    found = {golden.key: golden for golden in settled("acme/shop", 7, ledger)}
    assert set(found) == {"d"} and found["d"].label == "separate"
    assert found["d"].label_source.startswith("dismissed after it was reported")
    assert found["d"].new.path == "src/clip.py" and found["d"].existing.name == "shorten"


def test_unsettled_unsourced_and_self_reported_pairs_are_left_out() -> None:
    ledger = PullLedger(
        pairs={
            "open": pair("open"),
            "no-evidence": pair("kept-out", evidence=None),
            "hook": pair("kept-out", before_commit=True),
            "model": pair("kept-out", kind="model"),
            "backlog": pair("kept-out"),
        },
        backlog={"backlog": Backlog(new="clip", existing="shorten", kind="function", how="removed", settled=2)},
    )
    assert settled("acme/shop", 7, ledger) == []


def test_append_writes_json_lines_and_skips_empty_batches(tmp_path: Path) -> None:
    path = tmp_path / "out" / "goldens.jsonl"
    assert append(path, []) == 0 and not path.exists()
    goldens = settled("acme/shop", 7, PullLedger(pairs={"k": pair("dismissed")}))
    assert append(path, goldens) == 1 and append(path, goldens) == 1
    assert [Golden.model_validate_json(line).key for line in path.read_text().splitlines()] == ["k", "k"]
