# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B905, F401, I001
"""Offline EmbeddingGemma2 text adapter; full unchanged source, native projection/pooling."""

from __future__ import annotations
from _recovery_paths import recovery_path
import hashlib
import importlib.metadata
import inspect
import json
import os
from pathlib import Path
import sqlite3
import time

HERE = Path(__file__).resolve().parent
MODEL = "google/embeddinggemma-2"
REVISION = "f9972ac22e696a105c482202646979e33e4b5a1e"
DEFAULT_MODEL_DIR = Path(recovery_path("reports/encoder-comparison/models/gemma"))
MODES = {"symmetric": "SentenceSimilarity", "code_query": "CodeRetrieval", "document": "Document", "unprompted": None}
LIMITS = (1024, 2048, 4096)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def sha_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def offline_environment():
    # Never inspect credentials or default hub directories. Every load is local-only with token=False.
    for key, value in {
        "HF_HOME": str(HERE / "hf-home"),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "OMP_NUM_THREADS": "2",
        "MKL_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "2",
        "CUDA_VISIBLE_DEVICES": "",
    }.items():
        os.environ[key] = value


class GemmaEncoder:
    """encode(texts, max_length) returns ordered FP32 unit vectors, with last_records provenance.

    Default: symmetric similarity prefix on both sides, sequential unpadded batch-size-one FP32 CPU.
    Max length includes prefix and native BOS/EOS; no source strip/dedent/docstring removal.
    """

    def __init__(self, model_dir=DEFAULT_MODEL_DIR, *, mode="symmetric", load_model=True):
        offline_environment()
        if mode not in MODES:
            raise ValueError(f"Unknown explicit task mode: {mode}")
        import numpy as np
        import torch
        import transformers
        from transformers import AutoConfig, AutoModel, AutoTokenizer

        self.np, self.torch = np, torch
        torch.set_num_threads(2)
        if torch.get_num_interop_threads() != 1:
            torch.set_num_interop_threads(1)
        torch.manual_seed(0)
        torch.use_deterministic_algorithms(True)
        self.mode, self.folder = mode, Path(model_dir)
        begin = time.perf_counter()
        manifest = json.loads((HERE / "model-artifacts.json").read_text())
        hashes = {}
        for row in manifest:
            if not load_model and row["file"] == "model.safetensors":
                continue
            actual = sha_file(self.folder / row["file"])
            if actual != row["sha256"]:
                raise ValueError(f"Artifact mismatch: {row['file']}")
            hashes[row["file"]] = actual
        self.artifact_verify_seconds = time.perf_counter() - begin
        pooling = json.loads((self.folder / "1_Pooling/config.json").read_text())
        if pooling != {"embedding_dimension": 768, "pooling_mode": "mean", "include_prompt": True}:
            raise ValueError("Unverified native pooling configuration")
        catalog = json.loads((self.folder / "config_sentence_transformers.json").read_text())["prompts"]
        self.prefix = catalog[MODES[mode]] if MODES[mode] else ""
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.folder, local_files_only=True, token=False, trust_remote_code=False
        )
        self.tokenizer.padding_side = "right"
        self.tokenizer.truncation_side = "right"
        self.model = None
        self.contract = {
            "model": MODEL,
            "revision": REVISION,
            "artifact_sha256": hashes,
            "adapter_sha256": sha_file(__file__),
            "device": "cpu",
            "dtype": "float32",
            "threads": 2,
            "interop_threads": 1,
            "batch_size": 1,
            "padding": "none",
            "mode": mode,
            "prefix": self.prefix,
            "dimensions": 768,
            "pooling": "native-projected-last_hidden_state-mask-mean-include-prompt-float32-l2-eps1e-12",
            "tokenization": "exact-prefix-plus-unmodified-source-native-specials-right-truncation",
            "attention": "sdpa",
            "limits_supported": list(LIMITS),
            "runtime": {
                name: importlib.metadata.version(name)
                for name in ("torch", "transformers", "numpy", "tokenizers", "safetensors", "huggingface-hub")
            },
        }
        self.load_seconds = None
        self.loading_info = None
        if load_model:
            config = AutoConfig.from_pretrained(
                self.folder, local_files_only=True, token=False, trust_remote_code=False
            )
            config.vision_config = None
            config.audio_config = None
            begin = time.perf_counter()
            self.model, self.loading_info = AutoModel.from_pretrained(
                self.folder,
                config=config,
                local_files_only=True,
                token=False,
                trust_remote_code=False,
                dtype=torch.float32,
                attn_implementation="sdpa",
                output_loading_info=True,
            )
            self.model.eval()
            self.load_seconds = time.perf_counter() - begin
            if (
                self.loading_info.get("missing_keys")
                or self.loading_info.get("mismatched_keys")
                or self.loading_info.get("error_msgs")
            ):
                raise ValueError(f"Incomplete checkpoint load: {self.loading_info}")
            if self.model.vision_tower is not None or self.model.audio_tower is not None:
                raise ValueError("Nontext tower loaded")
            params = list(self.model.parameters())
            assert all(p.device.type == "cpu" and p.dtype == torch.float32 for p in params)
            assert self.model.language_model.embedding_projection.out_features == 768
            self.contract["parameter_count"] = sum(p.numel() for p in params)
            self.contract["native_runtime_source_sha256"] = sha_file(inspect.getfile(type(self.model)))
        self.contract_sha256 = digest(self.contract)
        self.last_records = []
        self.cache = None

    def prepare(self, text, max_length):
        if max_length not in LIMITS or not isinstance(text, str) or not text.strip():
            raise ValueError("Need nonempty source and one of 1024/2048/4096 total-token limits")
        rendered = self.prefix + text
        full = self.tokenizer(
            rendered,
            add_special_tokens=True,
            truncation=False,
            padding=False,
            return_special_tokens_mask=True,
            return_offsets_mapping=True,
        )
        limited = self.tokenizer(
            rendered,
            add_special_tokens=True,
            truncation=True,
            max_length=max_length,
            padding=False,
            return_special_tokens_mask=True,
            return_offsets_mapping=True,
        )
        payload = {k: limited[k] for k in ("input_ids", "attention_mask")}
        assert 0 < len(payload["input_ids"]) <= max_length
        assert all(v == 1 for v in payload["attention_mask"])
        # Native tokenizer retains BOS and EOS when truncating; compare its special-token mask.
        full_specials = [x for x, s in zip(full["input_ids"], full["special_tokens_mask"]) if s]
        actual_specials = [x for x, s in zip(limited["input_ids"], limited["special_tokens_mask"]) if s]
        assert actual_specials == full_specials
        full_source_tokens = sum(
            b > len(self.prefix) and not special
            for (a, b), special in zip(full["offset_mapping"], full["special_tokens_mask"])
        )
        kept_source_tokens = sum(
            b > len(self.prefix) and not special
            for (a, b), special in zip(limited["offset_mapping"], limited["special_tokens_mask"])
        )
        rec = {
            "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "rendered_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
            "input_sha256": digest(payload),
            "max_length": max_length,
            "mode": self.mode,
            "tokens_before": len(full["input_ids"]),
            "tokens_after": len(payload["input_ids"]),
            "native_special_token_ids": actual_specials,
            "special_tokens": len(actual_specials),
            "framed_source_tokens_before": full_source_tokens,
            "framed_source_tokens_after": kept_source_tokens,
            "source_tokens_omitted": full_source_tokens - kept_source_tokens,
            "retained_source_character_end": max(
                [b - len(self.prefix) for (a, b) in limited["offset_mapping"] if b > len(self.prefix)], default=0
            ),
            "truncated": len(full["input_ids"]) > len(payload["input_ids"]),
            "contract_sha256": self.contract_sha256,
        }
        return payload, rec

    def forward_payload(self, payload, *, return_hidden=False):
        if self.model is None:
            raise ValueError("Tokenizer-only adapter has no loaded model")
        torch = self.torch
        tensors = {k: torch.tensor([v], dtype=torch.long, device="cpu") for k, v in payload.items()}
        with torch.inference_mode():
            hidden = self.model(**tensors).last_hidden_state.float()
            mask = tensors["attention_mask"].unsqueeze(-1).to(torch.float32)
            pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
            vector = torch.nn.functional.normalize(pooled, p=2, dim=1, eps=1e-12)
        out = vector[0].numpy().astype(self.np.float32)
        assert out.shape == (768,) and self.np.isfinite(out).all()
        assert abs(float(self.np.linalg.norm(out)) - 1) < 1e-5
        return (out, hidden, tensors) if return_hidden else out

    def enable_cache(self, path, equivalence_proof):
        proof = json.loads(Path(equivalence_proof).read_text())
        if not proof.get("passed") or proof.get("contract_sha256") != self.contract_sha256:
            raise ValueError("Cache needs successful parity evidence for this exact encoder contract")
        self.cache = sqlite3.connect(path)
        self.cache.execute(
            "CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, contract TEXT NOT NULL, payload TEXT NOT NULL, vector BLOB NOT NULL, vector_sha256 TEXT NOT NULL)"
        )
        self.cache.commit()
        self.cache_proof_sha256 = sha_file(equivalence_proof)

    def encode(self, texts, max_length):
        if not texts:
            return self.np.empty((0, 768), dtype=self.np.float32)
        vectors, self.last_records = [], []
        for text in texts:
            start = time.perf_counter()
            payload, rec = self.prepare(text, max_length)
            key = digest({"contract": self.contract_sha256, "input": payload})
            hit = (
                self.cache.execute(
                    "SELECT payload,vector,vector_sha256 FROM vectors WHERE key=? AND contract=?",
                    (key, self.contract_sha256),
                ).fetchone()
                if self.cache
                else None
            )
            if hit:
                assert json.loads(hit[0]) == payload
                assert hashlib.sha256(hit[1]).hexdigest() == hit[2]
                vector = self.np.frombuffer(hit[1], dtype=self.np.float32).copy()
                rec.update(cache_hit=True, inference_seconds=0.0, equivalence_proof_sha256=self.cache_proof_sha256)
            else:
                begin = time.perf_counter()
                vector = self.forward_payload(payload)
                rec.update(cache_hit=False, inference_seconds=time.perf_counter() - begin)
                if self.cache:
                    raw = vector.tobytes()
                    self.cache.execute(
                        "INSERT OR REPLACE INTO vectors VALUES (?,?,?,?,?)",
                        (key, self.contract_sha256, json.dumps(payload), raw, hashlib.sha256(raw).hexdigest()),
                    )
                    self.cache.commit()
            rec.update(
                cache_key=key,
                wall_seconds=time.perf_counter() - start,
                vector_sha256=hashlib.sha256(vector.tobytes()).hexdigest(),
            )
            self.last_records.append(rec)
            vectors.append(vector)
        return self.np.stack(vectors)
