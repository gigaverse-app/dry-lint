# Original algorithm, configuration and evaluation programs

These readable `.txt` archives preserve the actual original programs as data. [Provenance](../provenance.json) lists original hashes, published hashes and transformations. Absolute local paths were normalized to `LAB_ROOT`; private repository literals were replaced explicitly. Original result hashes are never silently recalculated as if these were untouched originals. Use `materialize.py` to restore runnable files into a new directory; restoration executes nothing.

- [Original region comparer](product/src/dry_lint/operation_blocks.py.txt)
- [Frozen capture implementation](lab/operation_blocks_capture_v1.py.txt)
- [Original residual-coverage veto](lab/funded-rounds/round2/residual_blocks.py.txt)
- [Full native-source census](lab/funded-rounds/round2/full_source_audit.py.txt)
- [Rejection audit selection](lab/funded-rounds/round2/prepare_rejection_audit.py.txt)
- [Original report/evidence join](lab/funded-rounds/finalize_evidence.py.txt)
- [Tested residual preregistration](lab/funded-rounds/round2/PREREGISTRATION.json.txt)
- [Original cold/warm commands](lab/commands.sh.txt)

- [Original full specification](lab/EXPERIMENT.json.txt)
- [Package dependencies](product/pyproject.toml.txt) and [lockfile](product/uv.lock.txt)

The archive includes the complete original product package, original discovery/evaluation programs and earlier failed/pilot recipes. They are evidence, not default-enabled plugins. Read the canonical report for the final interpretation. No adapter imports run merely by browsing or importing the portable replay.
