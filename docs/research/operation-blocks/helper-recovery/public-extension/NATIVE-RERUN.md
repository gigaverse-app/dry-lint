# Full native rerun requirements

The compact replay is fully self-contained and needs only Python 3.11+:

```bash
python3 -I replay.py --out replayed --verify
```

A full native rerun needs additional frozen inputs that are **not distributed in this package**. Their hashes establish identity; they do not reconstruct missing source or sparse rows.

- The exact 617-row/79-background shared inventory at `/home/researcher/dry-lint-round/jobs/experiment-cpu-embeddings/.lab-results/full-corpus/shared-inputs/9bfa15c84eb72dd2/{rows,cohorts}.jsonl`. The full shared inventory can include material outside this public extension; this package does not export or authorize publication of it.
- All 14 BenchBackground payloads at the exact `background_required_at_original_location` paths in [contexts.jsonl](data/contexts.jsonl), with their recorded SHA-256 values. These preserve raw sparse counts, global document frequencies, order, max_df and scope; a new capture is not an equivalent substitute.
- Nine exact Git commits in `/home/researcher/dry-lint-round/research-corpus/improvement-public-pins/{due,pytest-selective,pytest-obligation}.git`, plus `/home/researcher/dry-lint-round/reports/research-experiments/improvement-wave/public-pin-acquisition.json`. Every revision and repository location is in `contexts.jsonl`. Git is run with lazy fetching and prompts disabled. The runner never acquires missing inputs.
- Readable provenance/support files listed in [input-proofs.json](provenance/input-proofs.json), notably the earlier CPU coverage inventory and both workers' common modules. The reconstruction uses the packaged baseline Python source, not a later production implementation. Current support files are provenance inputs only; the exact shared inventory and backgrounds are hash-checked.
- The recorded Python version and package versions in [dependencies.json](provenance/dependencies.json). The original interpreter is `/home/researcher/dry-lint-round/retrieval/.venv/bin/python`; the original numeric site-packages directory is `/home/researcher/dry-lint-round/jobs/experiment-cpu-embeddings/.lab-results/venv/lib/python3.14/site-packages`. Dependencies must already be installed; no installation or network step is included.
- Existing model artifacts under `/home/researcher/dry-lint-round/jobs/experiment-cpu-embeddings/.lab-results/model-cache`: `onnx/model.onnx` SHA-256 `6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452`, and `tokenizer.json` SHA-256 `be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037`. These are `sentence-transformers/all-MiniLM-L6-v2` at `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. The exact pooling, truncation, batch and backend contract is in `policies.json`.

From this package directory, preflight without extraction, inference or output-directory creation:

```bash
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/home/researcher/dry-lint-round/jobs/experiment-cpu-embeddings/.lab-results/venv/lib/python3.14/site-packages \
/home/researcher/dry-lint-round/retrieval/.venv/bin/python native_rerun.py \
  --out /home/researcher/dry-lint-round/jobs/public-pin-regressions/.lab-results/public-extension/native-rerun
```

When all external dependencies are present, append `--execute` to that exact command to perform the full rerun. The output directory must not exist. It stages byte-identical copies of the archived harness and frozen baseline source; only recipe output paths in the copied source receipt are rebased. It then runs:

```text
materialize.py
checks.py
verify_contract.py
blocks.py
cpu.py
final_check.py
summarize.py
```

Every step writes in the new directory. Materialization checks exact Git blobs, full-file hashes and full native function body hashes against each background. Blocks and CPU retain complete frozen competitor pools and global sparse fit. The CPU run encodes exact full native bodies and the frozen optional views using existing offline weights, with content/contract cache reuse inside the new directory. No discovery sweep or judge execution is performed.

The native preflight was exercised during packaging. A second full native inference run was not needed for this bounded publication followup; its results remain the earlier immutable experiment. The relocated standard-library outcome replay and its mutation test were executed independently during packaging.
