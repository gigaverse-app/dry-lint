"""Real offline configured detection, source invalidation and resource ownership."""

import gc
import hashlib
import os
import weakref
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import numpy as np
import pytest
from test_cpu_tail import extracted

from dry_lint import cpu_embedding as cpu
from dry_lint import detector as detection
from dry_lint.comparer_resources import ComparerResources
from dry_lint.comparers import TfidfComparer
from dry_lint.cpu_tail import CpuTailRankFusionComparer
from dry_lint.extractors import PythonExtractor
from dry_lint.operation_blocks import OperationBlocksComparer
from dry_lint.plugins import load
from dry_lint.settings import PluginChoice, Settings


@pytest.fixture
def model():
    folder = os.environ.get("DRY_LINT_TEST_MINILM_DIR")
    if not folder:
        pytest.skip("Supply pinned local artifacts; no download")
    return folder


def choice(model, cache, use="cpu-embedding", **options):
    return PluginChoice(use=use, model_dir=model, cache_dir=str(cache), **options)


def test_shared_encoder_validated_vectors_and_private_tokenizer(model, tmp_path):
    resources = ComparerResources()
    prefix = resources.load(choice(model, tmp_path))
    q, peer = extracted(), extracted("peer")
    resources.index(prefix, [q, peer])
    tail = resources.load(choice(model, tmp_path, "cpu-tail-rrf"))
    resources.index(tail, [q, peer])
    assert tail.tail.encoder is prefix.encoder
    assert tail.tail.memory_hits >= 2 and tail.tail.cache_hits == 0
    assert tail.tail.cache_misses > 0
    assert np.array_equal(prefix.vectors, tail.tail.vectors)
    # Statement parsing must not turn off encoder truncation/padding.
    assert len(prefix.encoder.tokenizer.encode(q.code).ids) == 256
    assert tail.tail.recipe.token_count(q.code) > 256
    before = prefix.neighbours(q, 1, lambda _: True)
    tail.tail.neighbours(peer, 1, lambda _: True)
    assert prefix.neighbours(q, 1, lambda _: True) == before
    other = resources.load(choice(model, tmp_path, threads=1))
    assert other.encoder is not prefix.encoder
    assert other._bodies is not prefix._bodies
    different_cache = resources.load(choice(model, tmp_path / "other"))
    assert different_cache._bodies is not prefix._bodies
    uncached = resources.load(PluginChoice(use="cpu-embedding", model_dir=model))
    assert uncached._bodies is not prefix._bodies


def test_each_constructor_revalidates_supplied_artifacts_even_on_hit(tmp_path, monkeypatch):
    # A tiny artifact stands at the external model boundary; real file digest
    # validation still executes on every resource hit.
    from test_cpu_embedding import Encoder

    artifact = tmp_path / "weights"
    artifact.write_bytes(b"valid")
    monkeypatch.setattr(cpu, "ARTIFACTS", {"weights": hashlib.sha256(b"valid").hexdigest()})
    monkeypatch.setattr(cpu, "MiniLMEncoder", Encoder)
    resources = ComparerResources()
    config = choice(str(tmp_path), tmp_path / "cache")
    resources.load(config)
    artifact.write_bytes(b"changed")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        resources.load(config)
    artifact.unlink()
    with pytest.raises(ValueError, match="Supply the pinned"):
        resources.load(config)


def test_shared_blocks_reindex_edit_failure_and_query_isolation(monkeypatch):
    from test_operation_blocks import background, job

    fs = [job("a.py", "a"), job("b.py", "b"), *background()]
    resources = ComparerResources()
    first, second = OperationBlocksComparer(), OperationBlocksComparer()
    resources.index(first, fs)
    resources.index(second, fs)
    assert first._parents is second._parents
    assert first._full_vectors is not second._full_vectors
    expected = first.neighbours(fs[0], 1, lambda _: True)
    query = fs[0].model_copy(update={"code": "def a(payload):\n    return None\n"})
    second.neighbours(query, 1, lambda _: True)
    assert first.neighbours(fs[0], 1, lambda _: True) == expected
    edited = [query, *fs[1:]]
    resources.index(second, edited)
    assert second._parents is not first._parents
    assert first.neighbours(fs[0], 1, lambda _: True) == expected
    # Changing token inputs in place must invalidate even when native identity is stable.
    old = second._parents
    query.tokens = ["changed-token"]
    resources.index(second, edited)
    assert second._parents is not old
    import dry_lint.operation_blocks as blocks

    def fail(_):
        raise ValueError("failed preparation")

    monkeypatch.setattr(blocks, "_representations", fail)
    with pytest.raises(ValueError, match="failed preparation"):
        resources.index(first, [query.model_copy()])
    assert first.neighbours(fs[0], 1, lambda _: True) == expected


def test_corrupt_cache_and_failed_tail_reindex_cannot_poison_shared_prefix(model, tmp_path):
    q, peer = extracted(), extracted("peer")
    config = choice(model, tmp_path)
    first = ComparerResources().load(config)
    first.index([q, peer])
    expected = first.neighbours(q, 1, lambda _: True)
    entry = first.cache_dir / (hashlib.sha256(q.code.encode()).hexdigest() + ".npz")
    entry.write_bytes(b"poison")
    resources = ComparerResources()
    prefix = resources.load(config)
    resources.index(prefix, [q, peer])
    assert prefix.cache_misses == 1
    assert prefix.neighbours(q, 1, lambda _: True) == expected
    tail = resources.load(choice(model, tmp_path, "cpu-tail-rrf"))
    resources.index(tail, [q, peer])
    old = tail.neighbours(q, 1, lambda _: True)
    with pytest.raises(ValueError, match="nonempty"):
        resources.index(tail, [peer.model_copy(update={"code": " "})])
    assert tail.neighbours(q, 1, lambda _: True) == old
    assert prefix.neighbours(q, 1, lambda _: True) == expected
    edited = q.model_copy(update={"code": "def query(items):\n    return 934\n"})
    resources.index(prefix, [edited, peer])
    assert not np.array_equal(prefix.vectors, tail.tail.vectors)


def test_configured_detection_exact_parity_and_concurrent_scope_release(model, tmp_path, monkeypatch):
    fs = [extracted(name) for name in ("query", "peer", "another")]
    settings = Settings(discovery={"cpu_recovery": {"model_dir": model, "cache_dir": str(tmp_path)}})
    refs = []
    barrier = Barrier(2)

    class Observed(ComparerResources):
        def __init__(self):
            super().__init__()
            refs.append(weakref.ref(self))

        def load(self, config):
            result = super().load(config)
            if isinstance(result, CpuTailRankFusionComparer):
                refs.append(weakref.ref(result.tail.encoder))
                barrier.wait(timeout=30)
            return result

        def index(self, comparer, functions):
            super().index(comparer, functions)
            if isinstance(comparer, CpuTailRankFusionComparer):
                refs.extend(
                    [
                        weakref.ref(comparer.tail.vectors),
                        weakref.ref(comparer.tail.view_vectors),
                        weakref.ref(comparer.blocks.tfidf),
                    ]
                )

    def run():
        detector = detection.Detector(fs, settings, TfidfComparer(), [PythonExtractor()])
        return [c.model_dump() for c in detector.candidates(fs[:1])]

    monkeypatch.setattr(detection, "ComparerResources", Observed)
    with ThreadPoolExecutor(max_workers=2) as executor:
        a, b = list(executor.map(lambda _: run(), range(2)))
    assert a == b and a
    gc.collect()
    assert all(ref() is None for ref in refs)

    class Independent(ComparerResources):
        def load(self, config):
            return load("comparers", config)

        def index(self, comparer, functions):
            comparer.index(functions)

    monkeypatch.setattr(detection, "ComparerResources", Independent)
    assert run() == a


def test_error_releases_detection_scope(model, tmp_path, monkeypatch):
    refs = []

    class Failing(ComparerResources):
        def __init__(self):
            super().__init__()
            refs.append(weakref.ref(self))

        def load(self, config):
            result = super().load(config)
            if isinstance(result, CpuTailRankFusionComparer):
                refs.append(weakref.ref(result.tail.encoder))
                raise ValueError("construction failure")
            return result

    monkeypatch.setattr(detection, "ComparerResources", Failing)
    settings = Settings(discovery={"cpu_recovery": {"model_dir": model, "cache_dir": str(tmp_path)}})
    fs = [extracted(), extracted("peer")]
    detector = detection.Detector(fs, settings, TfidfComparer(), [PythonExtractor()])

    def fail():
        with pytest.raises(ValueError, match="construction failure"):
            detector.candidates(fs[:1])

    fail()
    gc.collect()
    assert all(ref() is None for ref in refs)
