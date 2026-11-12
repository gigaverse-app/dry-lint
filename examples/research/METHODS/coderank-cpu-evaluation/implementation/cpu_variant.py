# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: I001
"""Explicit CPU optimization experiments; never replaces the pinned eager FP32 reference."""

import types
from coderank_adapter import CodeRankEncoder, canonical, digest, file_hash


def sdpa_forward(
    self,
    hidden_states,
    attention_mask=None,
    position_ids=None,
    past_key_value=None,
    output_attentions=False,
    use_cache=False,
    **kwargs,
):
    import torch

    if past_key_value is not None or use_cache or output_attentions:
        raise ValueError("Research SDPA variant only implements embedding inference")
    batch, length, _ = hidden_states.shape
    qkv = self.Wqkv(hidden_states).reshape(batch, length, 3, self.num_heads, self.head_dim)
    if self.rotary_emb_dim > 0:
        if self.rotary_head_dim:
            raise ValueError("Unsupported rotary head dimension")
        qkv = self.rotary_emb(qkv, seqlen_offset=0)
    query, key, value = [qkv[:, :, i].transpose(1, 2) for i in range(3)]
    output = torch.nn.functional.scaled_dot_product_attention(
        query, key, value, attn_mask=attention_mask, dropout_p=0.0, is_causal=False
    )
    return self.out_proj(output.transpose(1, 2).reshape(batch, length, self.embed_dim))


def float_output(module, args, output):
    output.last_hidden_state = output.last_hidden_state.float()
    return output


class CPUVariant(CodeRankEncoder):
    def __init__(self, *args, threads=2, precision="fp32", attention="sdpa", batch_mode="dynamic", **kwargs):
        if threads not in (2, 4, 8) or precision not in ("fp32", "bf16") or attention not in ("eager", "sdpa"):
            raise ValueError("Unsupported explicit variant")
        if batch_mode not in ("dynamic", "singleton"):
            raise ValueError("Unsupported batch mode")
        self.batch_mode = batch_mode
        super().__init__(*args, **kwargs)
        self.torch.set_num_threads(threads)
        if attention == "sdpa":
            for layer in self.model.encoder.layers:
                layer.attn.forward = types.MethodType(sdpa_forward, layer.attn)
        if precision == "bf16":
            self.model.to(dtype=self.torch.bfloat16)
            self.model.register_forward_hook(float_output)
        self.contract.update(
            threads=threads,
            dtype="bfloat16" if precision == "bf16" else "float32",
            attention=attention,
            variant_source_sha256=file_hash(__file__),
            normalization="L2 in float32",
            experimental_variant=True,
        )
        if batch_mode == "singleton":
            self.contract["padding"] = "canonical singleton; no padding; actual truncated input length"
        self.contract_digest = digest(canonical(self.contract))

    def _batches(self, rows, indices):
        if self.batch_mode == "singleton":
            for i in sorted(indices, key=lambda i: (len(rows[i]["input_ids"]), i)):
                yield [i]
        else:
            yield from super()._batches(rows, indices)
