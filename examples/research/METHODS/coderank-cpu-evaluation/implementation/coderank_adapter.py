# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: I001
"""Pinned, offline, CPU-only CodeRankEmbed; full source in, normalized CLS vectors out."""

from __future__ import annotations
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import types

HERE = Path(__file__).resolve().parent
MODEL_ID = "nomic-ai/CodeRankEmbed"
REVISION = "3c4b60807d71f79b43f3c4363786d9493691f8b1"
QUERY_PREFIX = "Represent this query for searching relevant code: "
LIMITS = (1024, 2048, 4096)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def file_hash(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def setup_environment():
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[key] = "2"
    os.environ.update(
        CUDA_VISIBLE_DEVICES="",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_IMPLICIT_TOKEN="1",
        HF_HUB_DISABLE_TELEMETRY="1",
        HF_HOME=str(HERE / "hf-cache"),
        TOKENIZERS_PARALLELISM="false",
    )
    sys.dont_write_bytecode = True


class CodeRankEncoder:
    def __init__(self, model_dir=HERE / "model", cache_path=None, allow_cross_limit_reuse=False):
        setup_environment()
        start = time.perf_counter()
        import numpy as np
        import torch
        from transformers import AutoTokenizer
        from safetensors.torch import load_file

        self.np, self.torch = np, torch
        torch.set_num_threads(2)
        if torch.get_num_interop_threads() != 1:
            torch.set_num_interop_threads(1)
        model_dir = Path(model_dir).resolve()
        manifest = json.loads((HERE / "model-artifacts.json").read_text())
        for artifact in manifest:
            if file_hash(model_dir / artifact["file"]) != artifact["sha256"]:
                raise ValueError("Model artifact hash mismatch: " + artifact["file"])
        # Only reviewed local Python files can execute. Bypass permissive remote custom loader.
        package_name = "_reviewed_coderank_" + REVISION
        package = types.ModuleType(package_name)
        package.__path__ = [str(model_dir)]
        sys.modules[package_name] = package
        config_cls = importlib.import_module(package_name + ".configuration_hf_nomic_bert").NomicBertConfig
        model_cls = importlib.import_module(package_name + ".modeling_hf_nomic_bert").NomicBertModel
        config = config_cls(**json.loads((model_dir / "config.json").read_text()))
        assert (
            config.n_positions == 8192 and config.rotary_scaling_factor is None and config.rotary_emb_scale_base is None
        )
        pool = json.loads((model_dir / "1_Pooling/config.json").read_text())
        assert pool["pooling_mode_cls_token"] and not any(
            v for k, v in pool.items() if k.startswith("pooling_mode_") and k != "pooling_mode_cls_token"
        )
        torch.manual_seed(0)
        self.model = model_cls(config, add_pooling_layer=False)
        self.load_result = str(
            self.model.load_state_dict(load_file(str(model_dir / "model.safetensors"), device="cpu"), strict=True)
        )
        self.model.to(device="cpu", dtype=torch.float32).eval()
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True, trust_remote_code=False)
        self.tokenizer.padding_side = "right"
        self.tokenizer.truncation_side = "right"
        self.contract = {
            "schema": 1,
            "model": MODEL_ID,
            "revision": REVISION,
            "artifacts": {x["file"]: x["sha256"] for x in manifest},
            "adapter_sha256": file_hash(__file__),
            "runtime": {
                p: importlib.metadata.version(p)
                for p in ("torch", "transformers", "tokenizers", "einops", "safetensors", "numpy")
            },
            "python": sys.version,
            "device": "cpu",
            "dtype": "float32",
            "pooling": "last_hidden_state[:,0,:]",
            "normalization": "L2",
            "threads": 2,
            "inter_op_threads": 1,
            "attention": "unmodified upstream eager matmul/softmax",
            "prompt_policy": "symmetric_code_unprefixed; nl_query_prefix_separate",
            "truncation": "right; limit includes CLS/SEP/prompt",
            "padding": "length_sorted_dynamic; max_batch=8; padded_tokens<=2048; attention_cells<=4194304; singleton_over_budget_allowed",
            "native_context": 8192,
        }
        self.contract_digest = digest(canonical(self.contract))
        self.allow_cross_limit_reuse = allow_cross_limit_reuse
        self.db = sqlite3.connect(cache_path) if cache_path else None
        if self.db:
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, contract TEXT NOT NULL, input_hash TEXT NOT NULL, first_limit INTEGER NOT NULL, vector BLOB NOT NULL)"
            )
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS arms (contract TEXT, source_hash TEXT, role TEXT, limit_tokens INTEGER, input_hash TEXT, vector_key TEXT, PRIMARY KEY(contract,source_hash,role,limit_tokens))"
            )
            self.db.commit()
        self.load_seconds = time.perf_counter() - start
        self.last_stats = {}

    def token_inputs(self, texts, max_length, role="code"):
        if max_length not in LIMITS:
            raise ValueError("max_length must be 1024, 2048 or 4096")
        if role not in ("code", "nl_query"):
            raise ValueError("role must be code or nl_query")
        if not all(isinstance(x, str) and x.strip() for x in texts):
            raise ValueError("Full source strings must be nonempty")
        rendered = [QUERY_PREFIX + x if role == "nl_query" else x for x in texts]
        full = self.tokenizer(rendered, add_special_tokens=True, truncation=False, padding=False, verbose=False)
        inputs = self.tokenizer(
            rendered, add_special_tokens=True, truncation=True, max_length=max_length, padding=False, verbose=False
        )
        rows = [{k: v[i] for k, v in inputs.items()} for i in range(len(texts))]
        return rows, [len(x) for x in full["input_ids"]]

    def _batches(self, rows, indices):
        batch = []
        longest = 0
        for index in sorted(indices, key=lambda i: (len(rows[i]["input_ids"]), i)):
            size = len(rows[index]["input_ids"])
            n = len(batch) + 1
            if batch and (n > 8 or n * size > 2048 or n * size * size > 4194304):
                yield batch
                batch = []
                longest = 0
            batch.append(index)
            longest = max(longest, size)
        if batch:
            yield batch

    def encode(self, texts, max_length, role="code", use_cache=True):
        texts = list(texts)
        if not texts:
            return self.np.empty((0, 768), dtype=self.np.float32)
        start = time.perf_counter()
        rows, full_lengths = self.token_inputs(texts, max_length, role)
        vectors = self.np.empty((len(rows), 768), dtype=self.np.float32)
        keys = []
        input_hashes = []
        missing = []
        hits = 0
        cross = 0
        for i, row in enumerate(rows):
            ih = digest(canonical(row))
            input_hashes.append(ih)
            # Equal model input is necessary; provenance retains every full source hash and arm.
            key = digest(
                canonical([self.contract_digest, role, ih, None if self.allow_cross_limit_reuse else max_length])
            )
            keys.append(key)
            cached = (
                self.db.execute("SELECT vector,first_limit FROM vectors WHERE key=?", (key,)).fetchone()
                if use_cache and self.db
                else None
            )
            if cached:
                vectors[i] = self.np.frombuffer(cached[0], dtype=self.np.float32)
                hits += 1
                cross += cached[1] != max_length
            else:
                missing.append(i)
        batches = []
        with self.torch.inference_mode():
            for ids in self._batches(rows, missing):
                batch_start = time.perf_counter()
                inputs = self.tokenizer.pad([rows[i] for i in ids], padding=True, return_tensors="pt", verbose=False)
                hidden = self.model(**inputs).last_hidden_state
                result = (
                    self.torch.nn.functional.normalize(hidden[:, 0, :], p=2, dim=1)
                    .cpu()
                    .numpy()
                    .astype(self.np.float32)
                )
                if not self.np.isfinite(result).all() or not self.np.allclose(
                    self.np.linalg.norm(result, axis=1), 1, atol=1e-5
                ):
                    raise ValueError("Invalid embeddings")
                for i, vector in zip(ids, result, strict=True):
                    vectors[i] = vector
                    if self.db and use_cache:
                        self.db.execute(
                            "INSERT OR IGNORE INTO vectors VALUES(?,?,?,?,?)",
                            (keys[i], self.contract_digest, input_hashes[i], max_length, vector.tobytes()),
                        )
                batches.append(
                    {
                        "rows": ids,
                        "shape": list(inputs["input_ids"].shape),
                        "seconds": time.perf_counter() - batch_start,
                        "unpad_tokens": sum(len(rows[i]["input_ids"]) for i in ids),
                    }
                )
                if self.db and use_cache:
                    self.db.commit()
                del hidden, result, inputs
        if self.db and use_cache:
            self.db.executemany(
                "INSERT OR REPLACE INTO arms VALUES(?,?,?,?,?,?)",
                [
                    (self.contract_digest, digest(text.encode()), role, max_length, input_hashes[i], keys[i])
                    for i, text in enumerate(texts)
                ],
            )
            self.db.commit()
        self.last_stats = {
            "rows": len(texts),
            "role": role,
            "limit": max_length,
            "seconds": time.perf_counter() - start,
            "cache_hits": hits,
            "cross_limit_hits": cross,
            "encoded_rows": len(missing),
            "tokens_before": full_lengths,
            "tokens_after": [len(r["input_ids"]) for r in rows],
            "truncated_rows": sum(n > max_length for n in full_lengths),
            "omitted_tokens": sum(max(0, n - max_length) for n in full_lengths),
            "source_sha256": [digest(t.encode()) for t in texts],
            "input_hashes": input_hashes,
            "vector_keys": keys,
            "batches": batches,
            "contract_digest": self.contract_digest,
        }
        return vectors


_default = None


def encode(texts, max_length):
    """Reusable symmetric code-to-code API. No labels, query instruction, or source rewriting."""
    global _default
    if _default is None:
        _default = CodeRankEncoder()
    return _default.encode(texts, max_length)
