# Original algorithm, configuration and evaluation programs

These readable `.txt` archives preserve the actual original programs as data. [Provenance](../provenance.json) lists original hashes, published hashes and transformations. Absolute local paths were normalized to `LAB_ROOT`; private repository literals were replaced explicitly. Original result hashes are never silently recalculated as if these were untouched originals. Use `materialize.py` to restore runnable files into a new directory; restoration executes nothing.

- [Original encoder, cached comparer and revised reranking](product/src/dry_lint/cpu_embedding.py.txt)
- [Original pilot/full-cohort evaluation](lab/experiment.py.txt) and [full-corpus runner](lab/full-corpus/run_full.py.txt)
- [Actual revised discovery and frozen selection](lab/funded-rounds/discover_round2.py.txt)
- [Matched wider lexical baseline](lab/funded-rounds/matched_sparse_baselines.py.txt)
- [Original report projection](lab/funded-rounds/project_round2.py.txt)
- [Original commands/hashes](lab/funded-rounds/round2/REPRODUCE.json.txt)
- [Tested revised specification](lab/funded-rounds/round2/EXPERIMENT.json.txt)
- [Runtime dependency versions](lab/runtime-requirements.lock.txt)

- [Original full specification](lab/EXPERIMENT.json.txt)
- [Package dependencies](product/pyproject.toml.txt) and [lockfile](product/uv.lock.txt)

The archive includes the complete original product package, original discovery/evaluation programs and earlier failed/pilot recipes. They are evidence, not default-enabled plugins. Read the canonical report for the final interpretation. No adapter imports run merely by browsing or importing the portable replay.
