"""Explicit alternate precision/throughput contracts; never silently changes FP32 reference."""

from gemma_adapter import GemmaEncoder, digest, sha_file


class EfficientGemmaEncoder(GemmaEncoder):
    def __init__(self, model_dir=None, *, mode="symmetric", dtype="bfloat16", threads=4):
        if threads not in (2, 4, 8) or dtype not in ("float32", "bfloat16"):
            raise ValueError("Unsupported measured alternate")
        kwargs = {} if model_dir is None else {"model_dir": model_dir}
        super().__init__(**kwargs, mode=mode)
        self.torch.set_num_threads(threads)
        self.model.to(dtype=getattr(self.torch, dtype))
        self.contract.update(
            dtype=dtype,
            threads=threads,
            variant_adapter_sha256=sha_file(__file__),
            variant="native-weight-and-activation-precision-no-autocast-no-quantization",
        )
        assert all(p.dtype == getattr(self.torch, dtype) for p in self.model.parameters())
        self.contract_sha256 = digest(self.contract)
