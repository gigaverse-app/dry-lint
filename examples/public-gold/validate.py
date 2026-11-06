"""Offline regression validator for this data-only package; no target execution."""

import argparse
import copy
import gzip
import hashlib
import json
import pathlib
import shutil
import tempfile

from dry_lint.bench import load_gold
from dry_lint.bench_background import BenchBackground
from dry_lint.function_index import extraction_contract, tree_blobs
from dry_lint.functions import extractor_for
from dry_lint.plugins import load
from dry_lint.settings import Settings

ROOT = pathlib.Path(__file__).resolve().parent
EXTRACTORS = [load("extractors", c) for c in Settings().extractors]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def jl(p):
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def relative(root, v):
    p = pathlib.PurePosixPath(v)
    assert not p.is_absolute() and ".." not in p.parts, v
    target = (root / v).resolve()
    assert target.is_relative_to(root.resolve()) and target.is_file(), v
    return target


def refs(root, x):
    if isinstance(x, dict):
        for k, v in x.items():
            if k in {
                "source_file",
                "provenance_file",
                "review_file",
                "background_manifest",
                "source_inventory",
            } and isinstance(v, str):
                relative(root, v)
            refs(root, v)
    elif isinstance(x, list):
        for v in x:
            refs(root, v)


def side_check(root, s, bgs=None):
    raw = json.loads(gzip.decompress(relative(root, s["source_file"]).read_bytes()))["source"].encode()
    assert sha(raw) == s["file_sha256"]
    text = raw.decode()
    code = "".join(text.splitlines(keepends=True)[s["start_line"] - 1 : s["end_line"]])
    assert code == s["code"]
    assert sha(code.encode()) == s["snippet_sha256"]
    assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == s["git_blob_sha1"]
    ex = s.get("extraction")
    if ex:
        fs = extractor_for(s["path"], EXTRACTORS).functions(s["path"], text)
        f = next(
            f
            for f in fs
            if f.qualname == ex["source_id"] and f.line == ex["start_line"] and f.end_line == ex["end_line"]
        )
        assert sha(f.code.encode()) == ex["source_sha256"]
        assert f.line <= s["start_line"] <= s["end_line"] <= f.end_line
        mismatch = (s["start_line"], s["end_line"]) != (f.line, f.end_line)
        assert ex["scope_mismatch"] == mismatch
        if mismatch:
            assert (
                ex["relationship"] == "reviewed operation within enclosing extracted function"
                and s["snippet_sha256"] != ex["source_sha256"]
            )
        if bgs:
            b = bgs[(s["repository"], s["revision"])]
            d = next(d for d in b.documents if d.id == ex["source_id"] and d.source_sha256 == ex["source_sha256"])
            assert d.counts is not None
    return raw


def row_check(root, row, bgs=None):
    refs(root, row)
    assert row["schema"] == 1 and row["whole_function_label"] is None and row["granularity"] == "operation"
    for k in ["new", "existing"]:
        side_check(root, row[k], bgs)
    for context in row.get("context", []):
        side_check(root, context)
    lic = row["license"]
    raw = json.loads(gzip.decompress(relative(root, lic["source_file"]).read_bytes()))["source"].encode()
    assert raw.decode() == lic["text"]
    assert sha(raw) == lic["sha256"]
    assert lic["revision"] == row["new"]["revision"] == row["existing"]["revision"]
    assert sha(relative(root, row["review_file"]).read_bytes()) == row["review_file_sha256"]
    if "review_update" in row:
        assert (
            sha(relative(root, row["review_update"]["provenance_file"]).read_bytes())
            == row["review_update"]["provenance_sha256"]
        )
    if row.get("active_panel_eligible"):
        assert row["label"] in ["duplicate", "separate"]
        assert row["new"]["extraction"]["source_id"] != row["existing"]["extraction"]["source_id"]
        if row["label"] == "duplicate":
            assert row.get("review_update", {}).get("active_duplicate_eligible", True)
        pins = row["pins"]
        expect = (pins.get("before") or pins.get("first_parent")) if row["phase"] == "before" else pins["merge"]
        assert row["new"]["revision"] == expect


def validate(root, git_root=None):
    manifest = json.loads((root / "backgrounds/manifest.json").read_text())
    refs(root, manifest)
    bgs = {}
    counts = []
    settings = Settings().model_copy(update={"include": ["*"], "exclude": ["*/migrations/*"]})
    for entry in manifest["backgrounds"]:
        data = relative(root, entry["path"]).read_bytes()
        assert sha(data) == entry["sha256"]
        b = BenchBackground.decode(data)
        assert (b.repository, b.revision) == (entry["repository"], entry["revision"])
        assert len(b.documents) == entry["functions"]
        assert len(b.document_frequency) == entry["tokens"]
        assert b.scope == entry["scope"] == {"include": ["*"], "exclude": ["*/migrations/*"]}
        assert b.extraction_contract == entry["extraction_contract"] == extraction_contract(settings)
        bgs[(b.repository, b.revision)] = b
        inv = relative(root, entry["source_inventory"])
        assert sha(inv.read_bytes()) == entry["source_inventory_sha256"]
        inventory = json.loads(inv.read_text())
        assert (inventory["repository"], inventory["revision"]) == (b.repository, b.revision)
        assert len(inventory["files"]) == entry["source_files"]
        assert sum(f["bytes"] for f in inventory["files"]) == entry["source_bytes"]
        if git_root is not None:
            folder = {
                "pingdotgg/t3code": "t3code",
                "anomalyco/opencode": "opencode",
                "OpenHands/software-agent-sdk": "software-agent-sdk",
            }[b.repository]
            repo = git_root / (folder + ".git")
            sources = tree_blobs(repo, b.revision, settings)
            assert sorted(sources) == [f["path"] for f in inventory["files"]]
            for f in inventory["files"]:
                raw = sources[f["path"]]
                assert len(raw) == f["bytes"] and sha(raw) == f["sha256"]
                assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == f["git_blob_sha1"]
        for gold in entry["gold_sources"]:
            assert any(d.id == gold["source_id"] and d.source_sha256 == gold["source_sha256"] for d in b.documents)
        counts.append(
            {
                "repository": b.repository,
                "revision": b.revision,
                "functions": len(b.documents),
                "compressed_bytes": len(data),
            }
        )
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix == ".gz":
            raw = gzip.decompress(path.read_bytes())
            if path.parent.name == "sources":
                payload = json.loads(raw)
                assert sha(payload["source"].encode()) == payload["sha256"] == path.name.split(".")[0]
        elif path.suffix in [".json", ".jsonl"]:
            assert "/home/researcher" not in path.read_text() and ".lab-results" not in path.read_text()
            objects = jl(path) if path.suffix == ".jsonl" else [json.loads(path.read_text())]
            for obj in objects:
                refs(root, obj)
    for filename in ["accepted-public-gold.jsonl", "contrast-controls.jsonl", "source-related.jsonl", "unknown.jsonl"]:
        for row in jl(root / filename):
            row_check(root, row, bgs)
    active = jl(root / "accepted-public-gold.jsonl")
    native = load_gold(root / "accepted-public-gold.jsonl")
    assert len(native) == len(active) == 4
    for r, n in zip(active, native, strict=True):
        assert n.new.code == r["new"]["code"] and n.existing.code == r["existing"]["code"] and n.label == r["label"]
    assert {r["family_id"] for r in active} == {"t3code-clipboard-feedback", "G04-03"}
    assert sorted(r["label"] for r in active) == ["duplicate", "duplicate", "separate", "separate"]
    assert len(jl(root / "source-related.jsonl")) == 4 and len(jl(root / "unknown.jsonl")) == 3
    for line in (root / "SHA256SUMS").read_text().splitlines():
        digest, path = line.split("  ", 1)
        assert sha(relative(root, path).read_bytes()) == digest, path
    return counts


def regressions(root):
    a = jl(root / "accepted-public-gold.jsonl")
    base = a[2]
    checks = 0
    mutations = [
        lambda x: x["new"].update(source_file="missing.json.gz"),
        lambda x: x["review_update"].update(provenance_file="missing-review.json"),
        lambda x: x["license"].update(revision=x["pins"]["merge"]),
        lambda x: x["new"]["extraction"].update(scope_mismatch=False),
        lambda x: x.update(whole_function_label="duplicate"),
    ]
    for change in mutations:
        bad = copy.deepcopy(base)
        change(bad)
        try:
            row_check(root, bad)
        except (AssertionError, StopIteration, FileNotFoundError):
            checks += 1
        else:
            raise AssertionError("Mutation was not rejected")
    return checks


if __name__ == "__main__":
    if not __debug__:
        raise SystemExit("Run validation without Python -O; its invariant checks use assertions.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=pathlib.Path, default=ROOT, help="Portable package directory")
    parser.add_argument(
        "--audit-git-root",
        type=pathlib.Path,
        help="Optional directory containing pinned t3code.git, opencode.git and software-agent-sdk.git",
    )
    parser.add_argument("--report", type=pathlib.Path, help="Optional output report; defaults to stdout only")
    args = parser.parse_args()
    root = args.root
    counts = validate(root, git_root=args.audit_git_root)
    n = regressions(root)
    with tempfile.TemporaryDirectory(prefix="public-gold-relocation-") as tmp:
        relocated = pathlib.Path(tmp) / "data"
        shutil.copytree(root, relocated)
        assert len(validate(relocated)) == 6
    result = {
        "status": "pass",
        "active_rows": 4,
        "active_families": 2,
        "contrast_rows": 1,
        "related_rows": 4,
        "unknown_rows": 3,
        "backgrounds": counts,
        "negative_regressions_rejected": n,
        "portable_relocation": "pass",
        "source_and_license_ranges_hashes_gzip_native_load_gold": "pass",
        "full_inventory_vs_pinned_git": "pass"
        if args.audit_git_root
        else "not requested; portable validation needs no Git source acquisition",
        "no_target_execution": True,
    }
    if args.report:
        args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
