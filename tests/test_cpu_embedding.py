"""Offline encoder, vector-cache integrity and real Detector discovery contracts."""

import builtins
import hashlib
import os
from types import SimpleNamespace

import numpy as np
import pytest

from dry_lint import cpu_embedding as cpu
from dry_lint.detector import Detector
from dry_lint.models import Function
from dry_lint.plugins import load
from dry_lint.settings import PluginChoice, Settings


def minilm_dir() -> str:
    """The pinned local MiniLM artifacts CI fetches; tests never download them."""
    folder = os.environ.get("DRY_LINT_TEST_MINILM_DIR")
    if not folder:
        pytest.skip("Supply pinned local MiniLM artifacts with DRY_LINT_TEST_MINILM_DIR; tests never download")
    return folder


def function(name, code=None):
    return Function(path=name + ".py", name=name, line=1, end_line=2, code=code or name)


def unit(index=0):
    vector = np.zeros(cpu.DIMENSIONS, dtype=np.float32)
    vector[index] = 1
    return vector


class Encoder:
    def __init__(self, model_dir, threads=2):
        self.np = np
        self.contract = {"model": cpu.MODEL, "revision": cpu.REVISION, "threads": threads}
        self.codes = []
        self.values = {}

    def encode(self, codes):
        self.codes.extend(codes)
        return np.asarray([self.values.get(code, unit()) for code in codes])


@pytest.fixture
def fake_encoder(monkeypatch):
    monkeypatch.setattr(cpu, "MiniLMEncoder", Encoder)
    monkeypatch.setattr(cpu, "validate_artifacts", lambda *args: None)


def test_plugin_registration_and_stable_filtered_self_excluding_ranks(fake_encoder):
    comparer = load("comparers", PluginChoice(use="cpu-embedding", model_dir="offline"))
    query, first, second = map(function, ["query", "first", "second"])
    comparer.index([query, first, second])
    assert comparer.neighbours(query, 2, lambda _: True) == [(first, 1), (second, 1)]
    assert comparer.neighbours(query, 1, lambda f: f is not first) == [(second, 1)]
    assert comparer.neighbours(query, 0, lambda _: True) == []
    assert comparer.similarity(query, function("unindexed")) == 1
    assert not comparer.similarity_reusable
    comparer.index([query, query, first])
    assert comparer.neighbours(query, 1, lambda _: True) == []
    assert comparer.neighbours(first, 1, lambda _: True) == []
    comparer.index([])
    assert comparer.neighbours(query, 1, lambda _: True) == []


def test_invalid_sources_and_failed_matrix_do_not_publish_partial_index(fake_encoder):
    comparer = cpu.CpuEmbeddingComparer("offline")
    q, target = function("q"), function("target")
    comparer.index([q, target])
    assert comparer.neighbours(q.model_copy(update={"line": 0}), 1, lambda _: True) == []
    comparer.index([q, target.model_copy(update={"end_line": -1})])
    assert comparer.neighbours(q, 1, lambda _: True) == []
    for vector in [np.zeros(384, np.float32), np.full(384, np.nan, np.float32), unit().astype(np.float64)]:
        comparer.encoder.values["bad"] = vector
        with pytest.raises(ValueError, match="Invalid CPU embedding matrix"):
            comparer.index([function("bad")])
        assert len(comparer.functions) == 2
    with pytest.raises(ValueError, match="nonempty"):
        comparer.index([function("blank", " \n")])


def test_disk_cache_is_bound_to_input_contract_and_validated_atomically(fake_encoder, tmp_path, monkeypatch):
    cache = str(tmp_path / "vectors")
    first = cpu.CpuEmbeddingComparer("offline", cache_dir=cache)
    q = function("q", "sensitive full source")
    first.index([q, q.model_copy(update={"name": "alias"})])
    assert first.cache_misses == 1
    assert not list((tmp_path / "vectors").rglob(".pending-*"))
    second = cpu.CpuEmbeddingComparer("another-path", cache_dir=cache)
    second.index([q])
    assert second.cache_hits == 1 and second.encoder.codes == []
    assert first.version == second.version
    assert cpu.CpuEmbeddingComparer("offline", min_similarity=0.7, cache_dir=cache).version != first.version
    assert cpu.CpuEmbeddingComparer("offline", threads=1, cache_dir=cache).version != first.version
    key = hashlib.sha256(q.code.encode()).hexdigest()
    entry = second.cache_dir / (key + ".npz")
    with np.load(entry, allow_pickle=False) as saved:
        assert set(saved.files) == {"vector", "input_sha256", "contract_sha256"}
    for bad in [np.zeros(384, np.float32), np.full(384, np.inf, np.float32), unit()[:3]]:
        np.savez(entry, vector=bad, input_sha256=key, contract_sha256=second.cache_contract)
        fresh = cpu.CpuEmbeddingComparer("offline", cache_dir=cache)
        fresh.index([q])
        assert fresh.cache_misses == 1 and fresh.cache_hits == 0
    for kwargs in [{"input_sha256": "wrong"}, {"contract_sha256": "wrong"}]:
        fields = dict(vector=unit(), input_sha256=key, contract_sha256=second.cache_contract)
        fields.update(kwargs)
        np.savez(entry, **fields)
        fresh = cpu.CpuEmbeddingComparer("offline", cache_dir=cache)
        fresh.index([q])
        assert fresh.cache_misses == 1
    entry.write_bytes(b"corrupt cache")
    fresh = cpu.CpuEmbeddingComparer("offline", cache_dir=cache)
    fresh.index([q])
    assert fresh.cache_misses == 1
    monkeypatch.setattr(cpu.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("write failed")))
    with pytest.raises(OSError, match="write failed"):
        fresh.index([function("new")])
    assert fresh.functions == [q] and not list(fresh.cache_dir.glob(".pending-*"))


def test_detector_preserves_tfidf_exploration_then_adds_one_unseen_dense_candidate(repo, fake_encoder, monkeypatch):
    repo.write(
        "src/tariffs.py", "def debit_tariff(amount, rate):\n    subtotal = amount * rate\n    return subtotal + 17\n"
    )
    repo.commit()
    settings = Settings(
        discovery={
            "enabled": True,
            "comparers": [
                {"use": "tfidf", "neighbours": 20, "min_similarity": 0.35, "min_similarity_small": 0.35},
            ],
        }
    )
    before = Detector.for_repository(repo.root, settings)
    query = before.find("preview_caption_text")
    original = before.candidates([query])
    primary = [c for c in original if c.lane != "relative"]
    target = before.find("debit_tariff")
    assert primary and not any(target.qualname in (c.new.qualname, c.existing.qualname) for c in primary)
    values = {f.code: unit(2) for f in before.functions}
    values[query.code] = unit()
    values[primary[0].existing.code] = unit()  # The first dense result is already owned by TF-IDF.
    values[target.code] = np.asarray([0.8, 0.6] + [0] * 382, np.float32)
    old_init = Encoder.__init__

    def configure(self, *args, **kwargs):
        old_init(self, *args, **kwargs)
        self.values = values

    monkeypatch.setattr(Encoder, "__init__", configure)
    settings.discovery.comparers.append(PluginChoice(use="cpu-embedding", model_dir="offline", neighbours=1))
    # Validate the actual settings shape/loader, not a hand-composed candidate union.
    settings = Settings.model_validate(settings.model_dump())
    after = Detector.for_repository(repo.root, settings).candidates([query])
    after_primary = [c for c in after if c.lane != "relative"]
    assert [c.model_dump() for c in after_primary[: len(primary)]] == [c.model_dump() for c in primary]
    extra = after_primary[len(primary) :]
    assert len(extra) == 1 and extra[0].existing.qualname == target.qualname
    assert extra[0].lane == "exploration" and extra[0].comparer.startswith("cpu-embedding:1-")
    assert not extra[0].similarity_reusable and settings.budget.usd == 0.04


@pytest.fixture
def offline_runtime(tmp_path, monkeypatch):
    for relative in cpu.ARTIFACTS:
        p = tmp_path / relative
        p.parent.mkdir(exist_ok=True)
        p.write_text(relative)
    monkeypatch.setattr(
        cpu, "ARTIFACTS", {name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() for name in cpu.ARTIFACTS}
    )

    class Tokenizer:
        @classmethod
        def from_file(cls, path):
            return cls()

        def enable_truncation(self, max_length):
            self.max_length = max_length

        def enable_padding(self, **kwargs):
            self.padding = kwargs

        def encode(self, code):
            return SimpleNamespace(
                ids=[1, 2, 0], attention_mask=[1, 1, 0], type_ids=[0, 0, 0], pad=lambda *args, **kwargs: None
            )

    class Session:
        inputs = ["input_ids", "attention_mask", "token_type_ids"]

        def __init__(self, path, sess_options, providers):
            assert providers == ["CPUExecutionProvider"] and sess_options.intra_op_num_threads <= 2

        def get_inputs(self):
            return [SimpleNamespace(name=n) for n in self.inputs]

        def run(self, _, inputs):
            output = np.zeros((*inputs["input_ids"].shape, 384), np.float32)
            output[:, :2, 0] = [2, 4]
            output[:, 2, 1] = 1000  # Masked padding must not contribute to pooling.
            return [output]

    ort = SimpleNamespace(
        __version__="test-ort",
        SessionOptions=SimpleNamespace,
        ExecutionMode=SimpleNamespace(ORT_SEQUENTIAL=1),
        disable_telemetry_events=lambda: None,
        InferenceSession=Session,
    )

    class Options(SimpleNamespace):
        def add_session_config_entry(self, *args):
            pass

    ort.SessionOptions = Options
    tokens = SimpleNamespace(__version__="test-tokenizer", Tokenizer=Tokenizer)
    monkeypatch.setattr(cpu, "_dependencies", lambda: (np, ort, tokens))
    return tmp_path, Session, Tokenizer


def test_pinned_offline_runtime_masked_mean_normalization_and_limits(offline_runtime):
    folder, _, _ = offline_runtime
    encoder = cpu.MiniLMEncoder(folder)
    assert encoder.tokenizer.max_length == 256
    assert encoder.tokenizer.padding == {"pad_id": 0, "pad_token": "[PAD]"}
    assert np.array_equal(encoder.encode(["code"] * 9), np.tile(unit(), (9, 1)))
    assert encoder.contract["batch_size"] == 8
    with pytest.raises(ValueError, match="nonempty"):
        encoder.encode([])
    with pytest.raises(ValueError, match="threads"):
        cpu.MiniLMEncoder(folder, threads=3)
    (folder / "tokenizer.json").write_text("changed")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        cpu.MiniLMEncoder(folder)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 1.01])
def test_invalid_floor_fails_before_loading_model(value):
    with pytest.raises(ValueError, match="finite"):
        cpu.CpuEmbeddingComparer("missing", min_similarity=value)


def test_missing_artifacts_never_download(tmp_path):
    with pytest.raises(ValueError, match="offline"):
        cpu.MiniLMEncoder(tmp_path)


def test_missing_optional_dependency_has_install_instruction(monkeypatch):
    original = builtins.__import__

    def offline(name, *args, **kwargs):
        if name == "onnxruntime":
            raise ImportError("not installed")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", offline)
    with pytest.raises(ValueError, match=r"dry-lint\[cpu-embedding\]"):
        cpu._dependencies()


def test_runtime_rejects_invalid_model_inputs_outputs_and_empty_masks(offline_runtime, monkeypatch):
    folder, session, tokenizer = offline_runtime
    monkeypatch.setattr(session, "inputs", ["unexpected"])
    with pytest.raises(ValueError, match="model inputs"):
        cpu.MiniLMEncoder(folder)
    monkeypatch.setattr(session, "inputs", ["input_ids", "attention_mask"])
    encoder = cpu.MiniLMEncoder(folder)
    for shape, value, message in [
        ((1, 3, 383), 1, "model output"),
        ((1, 3, 384), np.nan, "model output"),
        ((1, 3, 384), 0, "embedding vector"),
    ]:
        monkeypatch.setattr(
            encoder.session, "run", lambda *args, shape=shape, value=value: [np.full(shape, value, np.float32)]
        )
        with pytest.raises(ValueError, match=message):
            encoder.encode(["code"])
    monkeypatch.setattr(
        tokenizer,
        "encode",
        lambda *args: SimpleNamespace(ids=[0], attention_mask=[0], type_ids=[0], pad=lambda *args, **kwargs: None),
    )
    with pytest.raises(ValueError, match="attention mask"):
        encoder.encode(["code"])


def test_similarity_clamps_negative_cosine_and_empty_source_fails(fake_encoder):
    comparer = cpu.CpuEmbeddingComparer("offline")
    comparer.encoder.values["negative"] = -unit()
    assert comparer.similarity(function("positive"), function("negative")) == 0
    with pytest.raises(ValueError, match="nonempty"):
        comparer.similarity(function("blank", "  "), function("negative"))


def test_real_optional_runtime_disables_telemetry_before_session(tmp_path, monkeypatch):
    model_dir = minilm_dir()
    ort = pytest.importorskip("onnxruntime")
    pytest.importorskip("tokenizers")
    calls = []
    disable, session = ort.disable_telemetry_events, ort.InferenceSession

    def disable_first():
        calls.append("disabled")
        return disable()

    def session_after(*args, **kwargs):
        assert calls == ["disabled"]
        return session(*args, **kwargs)

    monkeypatch.setattr(ort, "disable_telemetry_events", disable_first)
    monkeypatch.setattr(ort, "InferenceSession", session_after)
    comparer = cpu.CpuEmbeddingComparer(model_dir, cache_dir=str(tmp_path))
    comparer.index([function("actual", "def actual(n):\n    return n + 1")])
    assert comparer.cache_misses == 1 and calls == ["disabled"]
