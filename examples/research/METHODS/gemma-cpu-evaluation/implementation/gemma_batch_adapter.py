# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: B905, I001
"""Length-batched native BF16 adapter; cache keys contain the whole actual padded batch."""

import hashlib
import json
import time
from gemma_adapter import digest, sha_file
from gemma_variants import EfficientGemmaEncoder


class BatchedGemmaEncoder(EfficientGemmaEncoder):
    def __init__(self, model_dir=None, *, mode="symmetric", dtype="bfloat16", threads=4, batch_size=4):
        if batch_size not in (2, 4, 8):
            raise ValueError("Unmeasured batch size")
        super().__init__(model_dir, mode=mode, dtype=dtype, threads=threads)
        self.batch_size = batch_size
        self.contract.update(
            batch_size=batch_size,
            padding="dynamic-right-actual-batch-max",
            batch_adapter_sha256=sha_file(__file__),
            cache_identity="entire-actual-padded-input-batch-plus-encoder-contract-no-cross-batch-assumption",
        )
        self.contract_sha256 = digest(self.contract)

    def prepare_batch(self, texts, max_length):
        prepared = [self.prepare(text, max_length) for text in texts]
        length = max(len(p["input_ids"]) for p, r in prepared)
        payload = {"input_ids": [], "attention_mask": []}
        for p, r in prepared:
            pads = length - len(p["input_ids"])
            payload["input_ids"].append(p["input_ids"] + [self.tokenizer.pad_token_id] * pads)
            payload["attention_mask"].append(p["attention_mask"] + [0] * pads)
            r["padded_tokens"] = length
            r["batch_rows"] = len(texts)
        return payload, [r for p, r in prepared]

    def forward_batch(self, payload):
        torch = self.torch
        inputs = {k: torch.tensor(v, dtype=torch.long, device="cpu") for k, v in payload.items()}
        with torch.inference_mode():
            hidden = self.model(**inputs).last_hidden_state.float()
            mask = inputs["attention_mask"].unsqueeze(-1).float()
            pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
            result = torch.nn.functional.normalize(pooled, p=2, dim=1, eps=1e-12).numpy().astype(self.np.float32)
        assert result.shape == (len(payload["input_ids"]), 768) and self.np.isfinite(result).all()
        assert self.np.max(self.np.abs(self.np.linalg.norm(result, axis=1) - 1)) < 1e-5
        return result

    def encode(self, texts, max_length):
        if not texts:
            return self.np.empty((0, 768), dtype=self.np.float32)
        matrices = []
        self.last_records = []
        for start in range(0, len(texts), self.batch_size):
            begin = time.perf_counter()
            batch = texts[start : start + self.batch_size]
            payload, records = self.prepare_batch(batch, max_length)
            key = digest({"contract": self.contract_sha256, "actual_padded_batch": payload})
            hit = (
                self.cache.execute(
                    "SELECT payload,vector,vector_sha256 FROM vectors WHERE key=? AND contract=?",
                    (key, self.contract_sha256),
                ).fetchone()
                if self.cache
                else None
            )
            if hit:
                assert json.loads(hit[0]) == payload and hashlib.sha256(hit[1]).hexdigest() == hit[2]
                matrix = self.np.frombuffer(hit[1], dtype=self.np.float32).reshape(len(batch), 768).copy()
                inference = 0.0
            else:
                tick = time.perf_counter()
                matrix = self.forward_batch(payload)
                inference = time.perf_counter() - tick
                if self.cache:
                    raw = matrix.tobytes()
                    self.cache.execute(
                        "INSERT OR REPLACE INTO vectors VALUES (?,?,?,?,?)",
                        (key, self.contract_sha256, json.dumps(payload), raw, hashlib.sha256(raw).hexdigest()),
                    )
                    self.cache.commit()
            wall = time.perf_counter() - begin
            for position, (vector, r) in enumerate(zip(matrix, records)):
                r.update(
                    cache_key=key,
                    cache_hit=bool(hit),
                    batch_position=position,
                    batch_inference_seconds=inference,
                    inference_seconds=inference / len(batch),
                    wall_seconds=wall / len(batch),
                    padded_batch_input_sha256=digest(payload),
                    vector_sha256=hashlib.sha256(vector.tobytes()).hexdigest(),
                )
                if hit:
                    r["equivalence_proof_sha256"] = self.cache_proof_sha256
                self.last_records.append(r)
            matrices.append(matrix)
        return self.np.concatenate(matrices)
