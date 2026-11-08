"""Executable behavioral and source invariants, offline and confined to this extension."""

from common import HERE, Path, dump, folders, hashlib, json, load, read, sha
from dry_lint.operation_blocks import OperationBlocksComparer
from helper_fallback_v1 import HelperFallback, helper_block

from dry_lint.extractors import PythonExtractor

CLEANUP = '''def commit_staged(path):
    """Release the staging handle even when publication fails."""
    token = acquire_staging(path)
    try:
        publish_staging(token)
    finally:
        release_staging(token)
    return receipt_for(path)
'''
OPERATION = """def deliver(owner, payload):
    packet = owner.decode_packet(payload)
    packet.validate_packet(owner.schema)
    packet.attach_receipt(owner.receipt)
    return owner.encode_packet(packet)
"""


def function(path, code):
    return PythonExtractor().functions(path, code)[0]


def fit(*fs):
    noise = [function(f"noise{i}.py", f"def noise{i}(arg):\n    return unique_{i}(argument_{i})\n") for i in range(400)]
    original = OperationBlocksComparer()
    original.index([*fs, *noise])
    return original, HelperFallback(original)


def main():
    checks = []
    a = function("a.py", CLEANUP)
    b = function("b.py", CLEANUP.replace("commit_staged", "commit_copy"))
    before = [f.model_dump() for f in (a, b)]
    old, new = fit(a, b)
    assert old.neighbours(a, 1, lambda f: True) == []
    found = new.neighbours(a, 1, lambda f: True)
    assert found[0][0] is b and found[0][1] > 0.99
    assert before == [f.model_dump() for f in (a, b)] and "finally:" in b.code and '"""Release' in b.code
    checks.append("fallback gains complete cleanup helper while preserving full native evidence")
    assert new.neighbours(a, 1, lambda f: False) == [] and new.neighbours(a, 0, lambda f: True) == []
    assert new.neighbours(a, 1, lambda f: f is a) == []
    checks.append("allowed, zero limit and self exclusion")
    c = function("c.py", OPERATION)
    d = function("d.py", OPERATION.replace("deliver", "copy"))
    old, new = fit(c, d, a, b)
    expected = old.neighbours(c, 3, lambda f: True)
    assert expected and new.neighbours(c, 3, lambda f: True) == expected
    checks.append("original winners and score order take precedence")
    variant = CLEANUP.replace("finally:", "except OSError:").replace(
        "    return receipt_for(path)", "        raise\n    return receipt_for(path)"
    )
    e = function("e.py", variant)
    _, new = fit(a, e)
    assert new.neighbours(a, 1, lambda f: True)[0][0] is e and "except OSError:" in e.code and "raise" in e.code
    checks.append("retrieval retains distinct exception and cleanup contracts")
    nested = function(
        "nested.py",
        "def outer(path):\n    def inner():\n        publish_staging(path)\n    token=acquire_staging(path)\n    release_staging(token)\n    return receipt_for(path)\n",
    )
    long = function(
        "long.py",
        "def long(path):\n"
        + "".join(f"    value{i}=acquire_staging(path)\n" for i in range(81))
        + "    return receipt_for(path)\n",
    )
    assert helper_block(nested) is None and helper_block(long) is None
    assert all(len(bs) <= 13 for bs in new._parents) and all(len(ids) <= 64 for ids in new._postings.values())
    checks.append("nested and oversized helpers excluded without truncation; bounds preserved")
    frozen = json.loads((HERE / "frozen-source-manifest.json").read_text())
    for r in frozen["files"]:
        assert sha((HERE / "frozen-pr109" / r["path"]).read_bytes()) == r["sha256"]
    for r in frozen["recipes"]:
        assert sha(Path(r["output"]).read_bytes()) == r["sha256"]
    checked_files = set()
    count = 0
    for p in folders():
        folder = p.parent
        m, bg, fs, native = load(folder)
        proofs = read(folder / "source-proof.jsonl")
        assert len(fs) == len(bg.documents) and all(native)
        for f, d, proof in zip(fs, bg.documents, proofs, strict=True):
            assert (
                f.qualname == d.id == proof["id"] and sha(f.code.encode()) == d.source_sha256 == proof["source_sha256"]
            )
            assert f.line == proof["line"] and f.end_line == proof["end_line"]
            assert f.tokens == d.tokens()
            sp = proof["source_file"]
            if sp not in checked_files:
                raw = Path(sp).read_bytes()
                assert sha(raw) == proof["file_sha256"]
                assert (
                    hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == proof["git_blob_sha1"]
                )
                checked_files.add(sp)
            count += 1
    checks.append("all full native bodies, file objects, spans, frozen sparse token order verified")
    dump(
        HERE / "checks.json",
        {
            "status": "passed",
            "checks": checks,
            "background_function_occurrences": count,
            "unique_source_files": len(checked_files),
            "provider_calls": 0,
        },
    )
    print("PASS", len(checks), "invariants;", count, "function occurrences;", len(checked_files), "source files")


if __name__ == "__main__":
    main()
