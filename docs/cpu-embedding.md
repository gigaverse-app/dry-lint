# Offline CPU embedding discovery

`cpu-embedding` is an optional candidate comparer. It adds local MiniLM neighbours through the existing discovery
lane, preserving the baseline and earlier routes. It does not judge, acquire a model, read credentials, contact a
provider or change budgets. TF-IDF remains the default. Installation and model acquisition are explicit adopter
steps; offline runs need only the supplied files and installed dependencies.

Install `dry-lint[cpu-embedding]` in the environment that runs detection. Prepare these two files from
[`sentence-transformers/all-MiniLM-L6-v2`](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/tree/1110a243fdf4706b3f48f1d95db1a4f5529b4d41)
(revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, Apache-2.0). No weights are bundled. For example, these explicit
download commands run once, on a network-enabled machine; the resulting directory can then be copied offline:

```bash
mkdir -p .dry-lint-local/minilm/onnx
curl --fail --location 'https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/1110a243fdf4706b3f48f1d95db1a4f5529b4d41/onnx/model.onnx' -o .dry-lint-local/minilm/onnx/model.onnx
curl --fail --location 'https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/1110a243fdf4706b3f48f1d95db1a4f5529b4d41/tokenizer.json' -o .dry-lint-local/minilm/tokenizer.json
```

Keep `.dry-lint-local/` out of version control. The plugin requires these exact SHA256 values and rejects missing
or changed artifacts before loading the runtime:

| File | SHA256 |
| --- | --- |
| `onnx/model.onnx` | `6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452` |
| `tokenizer.json` | `be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037` |

For `.dry-lint.toml`, explicitly retain the existing TF-IDF exploration route before adding CPU discovery:

```toml
[discovery]
enabled = true
comparers = [
  { use = "tfidf", neighbours = 20, min_similarity = 0.35, min_similarity_small = 0.35 },
  { use = "cpu-embedding", neighbours = 1, model_dir = ".dry-lint-local/minilm", cache_dir = ".dry-lint-local/vectors" },
]
```

Run from the adopting repository: `dry-lint detect --root . --base origin/main --out candidates.json`.
Paths are relative to the process working directory; use absolute paths when running elsewhere. For configuration
in `pyproject.toml`, the table is `[tool.dry-lint.discovery]`. No budget or judge settings need changing.

The list order is significant. Ordinary baseline retrieval runs first, existing TF-IDF exploration retains its
20-neighbour cap, and CPU discovery proposes at most one **new, unsettled** pair per changed function after both
routes. It declares the generic `discovery_unseen` contract so earlier pairs are excluded before its cap. Scores
are not blended; the first route owns the candidate. Discovery permits same-file neighbours under the existing
core rules. This production profile is distinct from baseline-only plus one dense neighbour and from the
standalone balanced laboratory diagnostic. Existing discovery campaign limits still decide funding; exposure
alone is not an emitted report.

The encoder uses unchanged full function code, including comments/docstrings, first 256 wordpieces including
special tokens, dynamic right padding, attention-mask mean pooling and float32 L2 normalization (384 dimensions).
There are no chunks or learned corpus updates. ONNX runs sequentially on CPU with one or two threads (`threads=2`
by default), batches of eight, and serial tokenization. Exact cosine retrieval uses a fixed default floor of
0.65, excludes self identities, abstains on duplicate identities/invalid native spans, and breaks equal scores
by original input order. Empty/nonfinite/zero/non-unit vectors fail safely. The comparer identity includes the
pinned artifacts, pooling/truncation, runtime versions, floor and CPU configuration. It never permits the
changed-logic “not closer” verdict-reuse shortcut.

`cache_dir` is optional. Without it, vectors live only in memory. With it, a namespace binds the complete encoder
contract and each entry binds the SHA256 of the complete encoded source. Entries store vectors and hashes, not
source code. Reads require finite float32 unit vectors of the expected shape and matching input/contract hashes;
corrupt entries are misses. Atomic replacement prevents partial writes. Only missing bodies are encoded on later
runs. Changing only the retrieval floor can reuse vectors while changing comparer identity. Cache placement and
retention are the adopter's choice; use a private directory and do not commit or publish it. This is a vector
cache, not a verdict store, and introduces no new verdict reuse rule.

The public pretrained encoder may contain source seen during training. Measurements are development/regression
evidence, not an independent holdout. Cold whole-corpus encoding is expensive; persist the optional cache before
using the channel repeatedly. See [benchmark measurements](benchmark.md#offline-cpu-discovery).
