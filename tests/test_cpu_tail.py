"""Real extractors and pinned local tokenizer; controlled unit vectors, no model calls."""

import hashlib
import os
from pathlib import Path

import numpy as np
import pytest
from test_cpu_embedding import Encoder, unit

from dry_lint import cpu_embedding
from dry_lint.cpu_tail import CompleteStatementComparer, CpuTailRankFusionComparer
from dry_lint.detector import Detector
from dry_lint.extractors import PythonExtractor
from dry_lint.models import pair_key
from dry_lint.plugins import load
from dry_lint.settings import PluginChoice, Settings
from dry_lint.typescript import TypeScriptExtractor


@pytest.fixture
def encoder(monkeypatch):
    tokens = pytest.importorskip("tokenizers")
    folder = os.environ.get("DRY_LINT_TEST_MINILM_DIR")
    if not folder:
        pytest.skip("Supply pinned offline tokenizer with DRY_LINT_TEST_MINILM_DIR; never downloaded")

    class TokenEncoder(Encoder):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.tokenizer = tokens.Tokenizer.from_file(str(Path(folder) / "tokenizer.json"))

    monkeypatch.setattr(cpu_embedding, "MiniLMEncoder", TokenEncoder)


def extracted(name="query", extension="py"):
    padding = " ".join(["padding"] * 300)
    if extension == "py":
        source = f'def {name}(items):\n    """{padding}"""\n'
        source += "    if items:\n" + "".join(f'        results{i} = transform(items, "unique{i}")\n' for i in range(6))
        source += "    return items\n"
        extractor = PythonExtractor()
    else:
        source = f"function {name}(items) {{\n    // {padding}\n"
        source += "    if (items) {\n" + "".join(
            f'        const result{i} = transform(items, "unique{i}");\n' for i in range(6)
        )
        source += "    }\n    return items;\n}\n"
        extractor = TypeScriptExtractor()
    return extractor.functions(name + "." + extension, source)[0]


@pytest.mark.parametrize("extension", ["py", "ts", "tsx"])
def test_native_views_complete_containment_and_identity_limit(encoder, extension):
    c = CompleteStatementComparer("offline")
    f = extracted(extension=extension)
    views, status = c.recipe.views(f)
    assert status == "ok" and len(views) == 1
    v = views[0]
    assert v["text"] == f.name + "\n" + "\n".join(f.code.splitlines()[v["relative_line"] - 1 : v["relative_end_line"]])
    assert 48 <= v["operation_wordpieces"] <= 180 and v["input_wordpieces"] <= 256
    assert v["absolute_line"] == f.line + v["relative_line"] - 1
    assert v["input_sha256"] == hashlib.sha256(v["text"].encode()).hexdigest()
    assert c.recipe.views(f.model_copy(update={"name": "identity " * 300}))[0] == []
    short = PythonExtractor().functions("short.py", "def short(x):\n    return x + 1\n")[0]
    assert c.recipe.views(short) == ([], "untruncated")
    broken = f.model_copy(update={"code": "def broken(\n" + "padding " * 300, "path": "bad.py"})
    assert c.recipe.views(broken) == ([], "python-parse-unavailable")


def test_operation_scores_exclude_prefix_prefix_and_accept_all_three_directions(encoder):
    c = CompleteStatementComparer("offline")
    q, peer = extracted(), extracted("peer")
    short = PythonExtractor().functions("short.py", "def short(x):\n    return x + 1\n")[0]
    qtail, ptail = [c.recipe.views(f)[0][0]["text"] for f in (q, peer)]
    c.encoder.values = {q.code: unit(0), qtail: unit(1), peer.code: unit(0), ptail: unit(2), short.code: unit(0)}
    c.index([q, peer, short])
    assert c.neighbours(q, 9, lambda _: True) == []
    assert c.similarity(q, short) == 0  # Identical prefixes alone do not qualify.
    for left, right in [(qtail, peer.code), (q.code, ptail), (qtail, ptail)]:
        c._bodies.clear()
        c.encoder.values = {q.code: unit(0), qtail: unit(1), peer.code: unit(2), ptail: unit(3), short.code: unit(4)}
        c.encoder.values[right] = c.encoder.values[left]
        c.index([q, peer, short])
        assert c.neighbours(q, 1, lambda _: True) == [(peer, 1.0)]
        assert c.similarity(q, peer) == 1


def test_floor_stable_ties_ambiguity_and_filters_before_cap(encoder):
    c = CpuTailRankFusionComparer("offline")
    q = extracted()
    peers = [extracted("peer" + str(i)) for i in range(25)]
    # All equal valid vectors => equal tail ranks; block ranking cannot change the final top1 bound.
    c.index([q, *peers])
    assert c.neighbours(q, 10, lambda f: f is peers[-1]) == [(peers[-1], 1 / 61)]
    assert c.tail.neighbours(q, 2, lambda _: True) == [(peers[0], 1.0), (peers[1], 1.0)]
    assert c.neighbours(q, 0, lambda _: True) == []
    assert len(c.neighbours(q, 100, lambda _: True)) == 1
    assert c.similarity(q, peers[0]) <= 2 / 61
    assert c.similarity(q, peers[-1]) == 0
    c.index([q, peers[0], peers[0], peers[1].model_copy(update={"line": 0}), peers[2]])
    assert [f for f, _ in c.neighbours(q, 3, lambda _: True)] == [peers[2]]
    assert c.neighbours(peers[0], 1, lambda _: True) == []
    c.index([])
    assert c.neighbours(q, 1, lambda _: True) == []


def test_source_edit_corruption_and_failed_reindex_preserve_old_results(encoder, tmp_path):
    c = CpuTailRankFusionComparer("offline", cache_dir=str(tmp_path))
    q, peer = extracted(), extracted("peer")
    c.index([q, peer])
    original = c.neighbours(q, 1, lambda _: True)
    changed = extracted("changed")
    c.tail.encoder.values[changed.code] = np.zeros(384, np.float32)
    with pytest.raises(ValueError, match="Invalid CPU embedding matrix"):
        c.index([changed])
    assert c.neighbours(q, 1, lambda _: True) == original
    assert c.blocks.functions == [q, peer]
    changed = q.model_copy(update={"code": "def query(x):\n    return x + 17\n"})
    c.tail.encoder.values[changed.code] = unit(3)
    assert c.tail.neighbours(changed, 1, lambda _: True) == []
    fresh = CpuTailRankFusionComparer("offline", cache_dir=str(tmp_path))
    fresh.index([q, peer])
    assert fresh.tail.cache_hits == 4 and fresh.tail.cache_misses == 0
    entry = fresh.tail.cache_dir / (hashlib.sha256(q.code.encode()).hexdigest() + ".npz")
    entry.write_bytes(b"corrupt")
    repaired = CpuTailRankFusionComparer("offline", cache_dir=str(tmp_path))
    repaired.index([q, peer])
    assert repaired.tail.cache_misses == 1
    assert repaired.neighbours(q, 1, lambda _: True) == original
    assert c.version == fresh.version
    assert CpuTailRankFusionComparer("offline", threads=1).version != c.version


def test_detector_native_hashes_rounding_self_samefile_seen_and_filtered(encoder):
    c = load("comparers", PluginChoice(use="cpu-tail-rrf", model_dir="offline"))
    q, same, seen, filtered, peer = [extracted(name) for name in ("query", "same", "seen", "filtered", "peer")]
    same = same.model_copy(update={"path": q.path})
    filtered = filtered.model_copy(update={"code": filtered.code + "\n# dry-lint: ignore"})
    d = Detector(
        [q, same, seen, filtered, peer],
        Settings(neighbours=20),
        c,
        [PythonExtractor()],
        discovery_keys={pair_key(q.qualname, seen.qualname)},
    )
    neighbours = d.neighbours(q)
    assert neighbours == [(peer, 1 / 61)]
    candidate = d.pair(q, *neighbours[0])
    assert candidate.similarity == 0.016 and not candidate.similarity_reusable
    assert candidate.new.code == q.code and candidate.existing.code == peer.code
    assert candidate.new.hash == PythonExtractor().structure_hash(q)
    assert candidate.existing.hash == PythonExtractor().structure_hash(peer)


@pytest.mark.parametrize("count,accepted", [(47, False), (48, True), (180, True), (181, False)])
def test_statement_wordpiece_boundaries(encoder, count, accepted):
    recipe = CompleteStatementComparer("offline").recipe
    statement = next(
        s for n in range(200) if recipe.token_count(s := '    output = transform("' + "word " * n + '")') == count
    )
    source = 'def boundary():\n    """' + "padding " * 300 + '"""\n' + statement + "\n"
    f = PythonExtractor().functions("boundary.py", source)[0]
    views, _ = recipe.views(f)
    assert bool(views) is accepted
    if views:
        assert views[0]["operation_wordpieces"] == count


def test_max_two_size_ties_prefix_cutoff_and_clone_isolation(encoder):
    c = CompleteStatementComparer("offline")
    recipe = c.recipe
    statements = ['    output = transform("' + "word " * 55 + '")\n'] * 3
    source = 'def boundary():\n    """' + "padding " * 300 + '"""\n' + "".join(statements)
    f = PythonExtractor().functions("boundary.py", source)[0]
    views, _ = recipe.views(f)
    assert [v["relative_line"] for v in views] == [3, 4]
    # A complete operation wholly inside the existing prefix is not an extra view.
    early = "def early():\n" + statements[0] + '    """' + "padding " * 300 + '"""\n'
    assert recipe.views(PythonExtractor().functions("early.py", early)[0])[0] == []
    c.encoder.tokenizer.enable_truncation(max_length=16)
    assert recipe.views(f)[0] == views


def test_tail_floor_is_inclusive(encoder):
    c = CompleteStatementComparer("offline")
    q, at, below = extracted(), extracted("at"), extracted("below")
    for f, cosine in [(at, 0.8), (below, 0.799)]:
        vector = np.asarray([cosine, (1 - cosine**2) ** 0.5] + [0.0] * 382, dtype=np.float32)
        c.encoder.values[f.code] = vector
        c.encoder.values[c.recipe.views(f)[0][0]["text"]] = vector
    c.index([q, at, below])
    found = c.neighbours(q, 10, lambda _: True)
    assert [f for f, _ in found] == [at]
    assert found[0][1] == pytest.approx(0.8)


def test_real_block_tail_rrf_tie_uses_original_source_order(encoder):
    from test_operation_blocks import OPERATION, background, job

    c = CpuTailRankFusionComparer("offline")
    body = '    """' + "padding " * 300 + '"""\n    if payload:\n'
    body += "".join("    " + line + "\n" for line in OPERATION.splitlines())
    q = job("query.py", "query", body)
    block = job("block.py", "block")
    tail = job("tail.py", "tail", "    return unrelated(payload)\n")
    view = c.tail.recipe.views(q)[0][0]["text"]
    c.tail.encoder.values = {q.code: unit(0), view: unit(1), block.code: unit(2), tail.code: unit(1)}
    for peers in ([tail, block], [block, tail]):
        c.index([q, *peers, *background()])
        assert c.neighbours(q, 20, lambda f, peers=peers: f in peers) == [(peers[0], 1 / 61)]
        assert c.neighbours(q, 20, lambda f, peers=peers: f is peers[1]) == [(peers[1], 1 / 61)]
    # Both routes contribute independently when the same peer qualifies in both.
    c.tail._bodies.clear()
    c.tail.encoder.values[block.code] = unit(1)
    c.index([q, block, *background()])
    assert c.neighbours(q, 20, lambda _: True) == [(block, 2 / 61)]
