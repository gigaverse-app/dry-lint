"""Opt-in, offline MiniLM candidate retrieval. No model acquisition or judging; an explicitly supplied vector cache is optional."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from zipfile import BadZipFile

from dry_lint.models import Function

MODEL = "sentence-transformers/all-MiniLM-L6-v2"
REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
ARTIFACTS = {
    "onnx/model.onnx": "6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452",
    "tokenizer.json": "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037",
}
DIMENSIONS = 384
MAX_LENGTH = 256
BATCH_SIZE = 8


def _dependencies():
    try:
        os.environ["ORT_DISABLE_TELEMETRY"] = "1"
        import numpy
        import onnxruntime
        import tokenizers
    except ImportError as error:
        raise ValueError("CPU embedding requires optional dependencies: install 'dry-lint[cpu-embedding]'.") from error
    return numpy, onnxruntime, tokenizers


def validate_artifacts(model_dir, threads):
    """Recheck files even on a run-local encoder hit; paths are not evidence."""
    if type(threads) is not int or not 1 <= threads <= 2:
        raise ValueError("CPU embedding threads must be 1 or 2.")
    folder = Path(model_dir)
    for relative, expected in ARTIFACTS.items():
        path = folder / relative
        if not path.is_file():
            raise ValueError(f"Supply the pinned offline {MODEL}@{REVISION} artifact: {path}")
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected:
            raise ValueError(f"CPU embedding artifact SHA256 mismatch: {path}")


class MiniLMEncoder:
    """Only the pinned FP32 ONNX graph and complete tokenizer JSON are accepted."""

    def __init__(self, model_dir: str | Path, threads: int = 2):
        validate_artifacts(model_dir, threads)
        folder = Path(model_dir)
        self.np, ort, tokens = _dependencies()
        self.contract = {
            "model": MODEL,
            "revision": REVISION,
            "artifacts": ARTIFACTS,
            "pooling": "attention-mask-mean-float32-l2-epsilon1e-9-v1",
            "max_length": MAX_LENGTH,
            "tokenization": "unchanged-code-specials-serial-dynamic-right-padding-v1",
            "dimensions": DIMENSIONS,
            "batch_size": BATCH_SIZE,
            "threads": threads,
            "backend": [self.np.__version__, ort.__version__, tokens.__version__],
            "provider": "CPUExecutionProvider",
        }
        ort.disable_telemetry_events()
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self.session = ort.InferenceSession(
            str(folder / "onnx/model.onnx"), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self.inputs = {item.name for item in self.session.get_inputs()}
        if not {"input_ids", "attention_mask"} <= self.inputs or self.inputs - {
            "input_ids",
            "attention_mask",
            "token_type_ids",
        }:
            raise ValueError("Unexpected CPU embedding model inputs.")
        self.tokenizer = tokens.Tokenizer.from_file(str(folder / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=MAX_LENGTH)
        self.tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")

    def encode(self, codes: list[str]):
        np = self.np
        if not codes or any(not code.strip() for code in codes):
            raise ValueError("CPU embedding requires nonempty source bodies.")
        result = []
        for start in range(0, len(codes), BATCH_SIZE):
            # Serial tokenization avoids a process-wide Rayon pool; ONNX alone uses the configured threads.
            encoded = [self.tokenizer.encode(code) for code in codes[start : start + BATCH_SIZE]]
            length = max(len(item.ids) for item in encoded)
            for item in encoded:
                item.pad(length, pad_id=0, pad_token="[PAD]")
            inputs = {
                "input_ids": np.asarray([item.ids for item in encoded], dtype=np.int64),
                "attention_mask": np.asarray([item.attention_mask for item in encoded], dtype=np.int64),
                "token_type_ids": np.asarray([item.type_ids for item in encoded], dtype=np.int64),
            }
            mask = inputs["attention_mask"]
            if mask.ndim != 2 or not 0 < mask.shape[1] <= MAX_LENGTH or not (mask.sum(1) > 0).all():
                raise ValueError("Invalid CPU embedding tokenizer attention mask.")
            output = np.asarray(self.session.run(None, {k: v for k, v in inputs.items() if k in self.inputs})[0])
            if output.shape != (*mask.shape, DIMENSIONS) or not np.isfinite(output).all():
                raise ValueError("Invalid CPU embedding model output.")
            weights = mask[..., None].astype(np.float32)
            pooled = (output * weights).sum(1) / np.maximum(weights.sum(1), 1e-9)
            norms = np.linalg.norm(pooled, axis=1, keepdims=True)
            if not np.isfinite(norms).all() or not (norms > 1e-9).all():
                raise ValueError("Empty or nonfinite CPU embedding vector.")
            result.append((pooled / norms).astype(np.float32))
        return np.concatenate(result)


class CpuEmbeddingComparer:
    name = "cpu-embedding"
    discovery_unseen = True  # Core excludes earlier routes before applying this route's neighbour cap.
    similarity_reusable = False

    @classmethod
    def for_run(cls, resources, **options):
        return cls(**options, _resources=resources)

    def __init__(
        self,
        model_dir: str,
        min_similarity: float = 0.65,
        threads: int = 2,
        cache_dir: str | None = None,
        *,
        _resources=None,
    ):
        if not math.isfinite(min_similarity) or not 0 <= min_similarity <= 1:
            raise ValueError("CPU embedding min_similarity must be finite and between 0 and 1.")
        if _resources is None:
            self.encoder = MiniLMEncoder(model_dir, threads)
        else:
            validate_artifacts(model_dir, threads)
            self.encoder = _resources.get(
                (MiniLMEncoder, str(Path(model_dir).resolve()), threads),
                lambda: MiniLMEncoder(model_dir, threads),
            )
        self.np = self.encoder.np
        self.min_similarity = min_similarity
        self.cache_contract = hashlib.sha256(json.dumps(self.encoder.contract, sort_keys=True).encode()).hexdigest()
        self.cache_dir = Path(cache_dir) / self.cache_contract if cache_dir is not None else None
        self.cache_hits = self.cache_misses = self.memory_hits = 0
        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        contract = {**self.encoder.contract, "floor": min_similarity, "ranking": "stable-source-order-self-excluded-v1"}
        self.version = "1-" + hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()
        self.functions: list[Function] = []
        self.vectors = self.np.empty((0, DIMENSIONS), dtype=self.np.float32)
        # An explicit shared disk cache preserves the old missing-input batches.
        # Without it each route must encode its own original batch sequence.
        self._bodies: dict[str, object] = (
            _resources.get(("cpu-vectors", self.cache_contract, str(self.cache_dir.resolve())), dict)
            if _resources is not None and self.cache_dir is not None
            else {}
        )
        self._ambiguous: set[str] = set()

    def _valid_vector(self, vector) -> bool:
        np = self.np
        return (
            vector.shape == (DIMENSIONS,)
            and vector.dtype == np.dtype("float32")
            and bool(np.isfinite(vector).all())
            and abs(float(np.linalg.norm(vector)) - 1) <= 1e-5
        )

    def _cached(self, key: str):
        if self.cache_dir is None:
            return None
        try:
            with self.np.load(self.cache_dir / (key + ".npz"), allow_pickle=False) as entry:
                vector = entry["vector"]
                if (
                    entry["input_sha256"].shape == ()
                    and entry["contract_sha256"].shape == ()
                    and str(entry["input_sha256"]) == key
                    and str(entry["contract_sha256"]) == self.cache_contract
                    and self._valid_vector(vector)
                ):
                    return vector.copy()
        except (OSError, ValueError, KeyError, EOFError, BadZipFile):
            pass  # A partial, incompatible or corrupt cache is a miss, never retrieval evidence.
        return None

    def _save(self, key: str, vector) -> None:
        if self.cache_dir is None:
            return
        path = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=self.cache_dir, prefix=".pending-", suffix=".npz", delete=False
            ) as stream:
                path = Path(stream.name)
                self.np.savez(stream, vector=vector, input_sha256=key, contract_sha256=self.cache_contract)
            os.replace(path, self.cache_dir / (key + ".npz"))
        finally:
            if path is not None:
                path.unlink(missing_ok=True)

    def _vectors(self, codes: list[str]):
        if any(not code.strip() for code in codes):
            raise ValueError("CPU embedding requires nonempty source bodies.")
        self.memory_hits += sum(code in self._bodies for code in codes)
        missing = []
        for code in dict.fromkeys(codes):
            if code in self._bodies:
                continue
            key = hashlib.sha256(code.encode()).hexdigest()
            vector = self._cached(key)
            if vector is None:
                missing.append(code)
            else:
                self._bodies[code] = vector
                self.cache_hits += 1
        if missing:
            vectors = self.np.asarray(self.encoder.encode(missing))
            if vectors.shape != (len(missing), DIMENSIONS) or not all(self._valid_vector(v) for v in vectors):
                raise ValueError("Invalid CPU embedding matrix: expected finite float32 unit vectors.")
            for code, vector in zip(missing, vectors, strict=True):
                self._save(hashlib.sha256(code.encode()).hexdigest(), vector)
            self._bodies.update(zip(missing, vectors, strict=True))
            self.cache_misses += len(missing)
        return self.np.asarray([self._bodies[code] for code in codes])

    def index(self, functions: list[Function]) -> None:
        # Build before publishing state, so a failed encode cannot leave a partial index.
        vectors = self._vectors([f.code for f in functions]) if functions else self.np.empty((0, DIMENSIONS))
        self.functions, self.vectors = list(functions), vectors
        self._ambiguous = {name for name, count in Counter(f.qualname for f in functions).items() if count > 1}

    @staticmethod
    def _source_known(function: Function) -> bool:
        return 1 <= function.line <= function.end_line

    def neighbours(
        self, function: Function, k: int, allowed: Callable[[Function], bool]
    ) -> list[tuple[Function, float]]:
        if k <= 0 or not self.functions or function.qualname in self._ambiguous or not self._source_known(function):
            return []
        scores = self.vectors @ self._vectors([function.code])[0]
        found = []
        for position in self.np.argsort(-scores, kind="stable"):
            score, other = float(scores[position]), self.functions[position]
            if score < self.min_similarity:
                break
            if (
                other.qualname != function.qualname
                and other.qualname not in self._ambiguous
                and self._source_known(other)
                and allowed(other)
            ):
                found.append((other, min(1.0, max(0.0, score))))
                if len(found) == k:
                    break
        return found

    def similarity(self, a: Function, b: Function) -> float:
        vectors = self._vectors([a.code, b.code])
        return min(1.0, max(0.0, float(vectors[0] @ vectors[1])))
