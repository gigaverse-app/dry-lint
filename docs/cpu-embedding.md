# Offline CPU embedding discovery

Use CPU embeddings as an experimental secondary route when vocabulary, naming or short natural-language
descriptions may connect functions that lexical matching misses. It maps source text into a pretrained vector
space: nearby vectors suggest similar text or behavior for the existing judge to inspect. It does not learn
your repository's ownership rules, and similar purpose can still require separate implementations.

For example, an `inspect_active_cache_entries` function and a differently named `list_live_cache_state` function
might express the same inventory operation with different identifiers. An encoder can propose that comparison
without an exact token overlap. However, a cache inventory and cache eviction routine may also look similar;
reading and deleting are different contracts. These names illustrate the hypothesis, not measured discoveries.

The current implementation encodes only the **first 256 wordpieces**, including special tokens, of each full
function. Long handlers can therefore look alike because of their setup while an important tail is invisible.
The judge still receives complete functions. Prefer a repository-specific experiment on short, well-described
functions; do not assume this implementation fixes long-function partial-operation misses. For Python operations
inside longer workflows, also consider [operation blocks](operation-blocks.md).

The completed wide-baseline evaluation found **no added known positive contexts and three added negative
contexts** over TF-IDF20; its sole later Claude report was also baseline-funded and source-reviewed as related.
This route is not a demonstrated default recall upgrade. Its practical implementation benefit is reusable
offline encoding: 100 supplied bodies took **6.623 seconds cold versus 0.440 seconds with the cache**, while the
original 37,604-function LiteLLM cold encoding took about **2,496 seconds**. These are development measurements,
not guarantees for your hardware. Start with the [paired trial guide](discovery-comparers.md), persist the cache,
and judge the additional candidates against independent controls.

## How it works

A later [complete-statement experiment](https://github.com/gigaverse-app/dry-lint/pull/116) tested the tail
that this plugin cannot see. It kept the original routes first, encoded at most two complete tail statements,
and appended at most one unseen candidate at cosine >= .80. The first version ran only when the original CPU
route abstained and produced no new reports in five funded novel pairs. Removing that gate yielded two
source-supported reports among 47 novel pairs, with no reports among 16 controls. One of those two would also pass the first tail recipe; only the public snapshot case specifically requires
removing the gate. The selected rounds are not a paired causal comparison. The two reports also survived
a separate, post-hoc balanced-budget check of those two queries; that check is not overall precision or recall.

One public example is OpenHands' metrics snapshot: its tail repeats a projection that the 256-token prefix
misses. Reuse must preserve whether mutable token usage is copied or retained by reference. A direct substitution
of the existing helper changes that behavior. This is evidence for a carefully scoped shared operation, not
interchangeable functions. The statement-view recipe remains research code in the linked study; the installed
plugin described below still uses one prefix vector. Keep it opt-in: two useful reports justify the mechanism,
but do not establish broad recall, and adding statement vectors increases cold encoding work.

```text
Full native function -> first 256 wordpieces -> pinned MiniLM on CPU -> 384-number vector
                                                                      |
                                             attention-mask mean pool + normalize
                                                                      |
Changed function vector -> cosine against indexed vectors -> unseen full-function pair
```

MiniLM was trained before this run. Detection performs inference, not fitting or fine-tuning. The current
representation has one vector per function: it does not combine code and documentation as independently
weighted fields, split the body into chunks, or resolve called helpers. Exact cosine ranking then supplies
at most the configured number of eligible new parents. The normal scope, settling, budget and judging rules
still apply. A vector cache saves inference; it cannot supply or authorize a judge's verdict.

## Install and configure

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
