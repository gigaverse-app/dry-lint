# Reproduction, acquisition and limits

Run `python3 reproduce.py`, `python3 native.py` (dependency below), and `python3 audit.py` from this directory. `reproduce.py --output /tmp/recorded-results-NEW` writes CSV decisions and machine metrics into a fresh directory. Source code is data: no nominated target code executes. `--case CASE_ID` prints the complete representative source, rendered inputs and sanitized observations. The selected replay is portable outside the lab and does not rebuild rankings from a small replacement corpus.


The CPU model is `sentence-transformers/all-MiniLM-L6-v2` at `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` (Apache-2.0), FP32 ONNX CPU, 384 dimensions, first 256 wordpieces, masked mean pooling then L2 normalization, batch size 8, two CPU threads. [Acquisition URLs and SHA-256 records](data/evidence/acquisition.json) bind the 90,405,214-byte ONNX graph and tokenizer. We distribute eight recorded vectors, not model weights or a corpus cache. Obtain weights explicitly into a caller-owned directory only for a separately planned full rerun; the original encoder refuses unexpected hashes and does not download automatically.

To run the original pair cosine algorithm, use an environment with NumPy 2.5.4 (the recorded version). For example, `uv run --python 3.14 --with numpy==2.5.4 python native.py` installs that dependency explicitly if needed. This command does not call a judge or encode source. Standard `reproduce.py` requires no third-party packages. Exact float32 selected dot products are compared with the original full-matrix scores using 1e-6 tolerance.

Every selected answer retains model, prompt version, output cap, request settings, exact rendered input, original response hash, observable answer and usage. Claude uses `claude-sonnet-5-5`, shared-operations, max 1024, reporting threshold .8; Jev uses `jev-1.14.0` and reuse-context-v3 for diagnostic comparison. Temperature/effort are omitted, retries are recorded as zero in the central request options. Provider answers are observations, not truth. Parsed verdicts are recomputed from sanitized responses; hidden reasoning and transport identifiers are omitted, without claiming the sanitized response hash equals the original.

The selected full source files already ship with license notices. To independently hydrate exact source from Git:

```bash
git clone https://github.com/BerriAI/litellm.git /tmp/litellm-source
git -C /tmp/litellm-source fetch origin fc1e47e580d9e3d2e8b46ad05a293a58ed0b8f1f
python3 hydrate.py --repository BerriAI/litellm --git /tmp/litellm-source --output /tmp/litellm-selected-NEW
```

All other allowed repository URLs and exact pins are in [source-pins.json](data/source-pins.json). `hydrate.py` makes no network call and fails on mismatched file hashes. For the source-free historical hold, independently authorized local hydration is explicit:

```bash
python3 hydrate.py --repository Garsson-io/kaizen --git /your/authorized/local-repository --output /tmp/held-local-NEW
```

That local-only export uses commit `4941b4a8928054910b5053255a99c84ac32bf3c2`; it is not included in the selected case replay and must not be redistributed. [Hold records](data/holds.json) exclude source-bearing prompts and answers. Private historical inputs remain local-only and are represented publicly only by anonymous aggregate/outcome data.

Public sparse backgrounds are separately available through [pinned exact-hash corpus acquisition](CORPUS.md). Preserve each extraction scope and source order; do not treat a different public revision as a replacement. A matching sparse background supplies document frequencies/competitors, not necessarily native source, historical labels or vector caches.

Restore original runnable code and configuration without executing it:

```bash
python3 materialize.py --output /tmp/original-NEW --lab-root /tmp/study-lab-NEW
```

Place restored `lab/` files under `.lab-results/` and product `src/`, `pyproject.toml`, `uv.lock` into an isolated study copy. The original programs refer to `LAB_ROOT/jobs/...` and `LAB_ROOT/reports/...`; materialization replaces that prefix with your explicit root. Restore the [full manifest](FULL-RERUN.json) inputs in that layout before using the original full-evaluation commands. Do not execute archived acquisition/provider commands implicitly, and never point mutation-producing evaluation programs at the frozen experiment directories.

Original full-evaluation commands (external inputs required; **not** equivalent to portable selected replay):

```bash
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 PYTHONPATH="$PWD/.lab-results/venv/lib/python3.14/site-packages" python .lab-results/promotion/compare.py --behavior-rerank
python .lab-results/funded-rounds/summarize_round2.py
python .lab-results/funded-rounds/project_round2.py
python .lab-results/funded-rounds/matched_sparse_baselines.py

```

The original locked package and experiment runtime specifications provide the dependency inventory: CPython 3.14 in the lab, dry-lint's locked Pydantic/parser environment, Git, and for CPU NumPy/ONNX Runtime/tokenizers at the recorded versions. Python 3.11+ suffices for the standard-library recorded-answer replay. Original provider request implementations are archived for audit; new physical judge execution would require separately authorized adopter-owned credentials and a new experiment/output location. No provider execution or refitting is needed to inspect these results.
