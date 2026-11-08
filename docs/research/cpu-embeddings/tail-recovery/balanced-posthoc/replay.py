"""Replay public exact evidence; private004 remains an explicitly held numeric row."""

import argparse
import gzip
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path

HOME = Path(__file__).resolve().parent


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--balanced-package", type=Path, default=HOME.parent.parent / "balanced")
    args = parser.parse_args()
    for name, sha in json.loads((HOME / "balanced-dependency.json").read_text()).items():
        assert digest(args.balanced_package / name) == sha, "Frozen balanced dependency changed: " + name
    manifest = HOME / "MANIFEST.json"
    if manifest.exists():
        for name, sha in json.loads(manifest.read_text())["files"].items():
            assert digest(HOME / name) == sha, name
    spec = importlib.util.spec_from_file_location("balanced_reuse", args.balanced_package / "reproduce.py")
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)
    # These proven functions use HOME only to locate the native SQLite archive.
    b.HOME = HOME
    data = json.loads(gzip.decompress((HOME / "recordings.json.gz").read_bytes()))
    assert len(data["entries"]) == 2 and len(data["requests"]) == 4 and len(data["native"]) == 2
    with tempfile.TemporaryDirectory(prefix="cpu-balanced-public-") as tmp:
        b.replay_native(data, Path(tmp))
    entries = {e["id"]: e for e in data["entries"]}
    summary = json.loads((HOME / "summary.json").read_text())
    numeric = {r["id"]: r for r in summary["rows"]}
    assert "CPUI2-004" not in entries
    cfg = b.Settings.model_validate(data["settings"])
    for e in entries.values():
        for side in ["new", "existing"]:
            f = e["packet"]["candidate"][side]
            blob = data["source_files"][f["path"]].encode()
            proof = next(
                p
                for p in e["binding"]["source_files"]
                if p["path"] == f["path"] and p["body_sha256"] == b.sha(f["code"].encode())
            )
            # Class members use qualified source IDs; match path/body when name is short.
            assert b.sha(blob) == proof["file_sha256"]
            assert "\n".join(blob.decode().splitlines()[f["line"] - 1 : f["end_line"]]) == f["code"]
            assert b.sha(f["code"].encode()) == proof["body_sha256"]
    source_reviews = json.loads((HOME / "accepted-source-public.json").read_text())
    assert {r["case_id"] for r in source_reviews} == set(entries)
    for joined in source_reviews:
        e = entries[joined["case_id"]]
        decision = joined["decision"]
        assert decision["coordinator_scope_accepted"] and decision["accepted_gold"] is False
        assert (decision["repository"], decision["revision"]) == (e["packet"]["repository"], e["packet"]["revision"])
        source = {p["source_id"]: p for p in decision["endpoints"]}
        c = b.Candidate.model_validate(e["packet"]["candidate"])
        assert set(source) == {c.new.qualname, c.existing.qualname}
        for f in (c.new, c.existing):
            proof = next(p for p in e["binding"]["source_files"] if p["source_id"] == f.qualname)
            actual = source[f.qualname]
            assert (actual["path"], actual["line"], actual["end_line"]) == (f.path, f.line, f.end_line)
            assert actual["body_sha256"] == proof["body_sha256"] == b.sha(f.code.encode())
            assert actual["file_sha256"] == proof["file_sha256"]
        row = numeric[e["id"]]
        assert (row["source_label"], row["source_utility"]) == (decision["label"], decision["utility"])
        assert row["bounded_useful_report"] == (
            row["answers"]["claude"]["reported"]
            and decision["label"] == "duplicate"
            and decision["utility"] == "bounded"
        )
    assert summary["net_bounded_useful_reports"] == sum(
        r["bounded_useful_report"] for r in numeric.values() if r["role"] == "candidate"
    )
    for r in data["requests"]:
        e = entries[r["case_id"]]
        verdict = b.verify_request(r, e, data["observations"][r["request_key"]])
        c = b.Candidate.model_validate(e["packet"]["candidate"])
        row = numeric[e["id"]]["answers"][r["identity"]["kind"]]
        assert (row["label"], row["score"], row["reported"]) == (
            verdict.label,
            verdict.score,
            b.reported(c, verdict, cfg),
        )
    print(
        json.dumps(
            dict(
                public_native_campaigns_recomputed=2,
                public_exact_questions_recomputed=4,
                public_source_files_verified=len(data["source_files"]),
                public_source_decisions_verified=2,
                private004_source_recomputed=False,
                net_bounded_useful_reports_numeric=summary["net_bounded_useful_reports"],
                gained_reports_numeric=summary["gained_reports"],
                lost_reports_numeric=summary["lost_reports"],
                source_known_gains=summary["source_known_gains"],
                source_unknown_gains=summary["source_unknown_gains"],
                new_physical_usd=summary["new_physical_usd"],
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
