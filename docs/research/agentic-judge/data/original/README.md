# Original implementation archive

The files below are readable `.txt` archives, not importable modules. They preserve original implementation and dependency files with original SHA-256 values in [provenance](../provenance.json). Absolute laboratory paths are explicitly normalized to `LAB_ROOT`; any private repository literals are replaced with `WITHHELD_PRIVATE_REPOSITORY`. These transformations are recorded, not passed off as original-byte hashes. No source-result values are rewritten.

Key files:

- [Bounded source tools and original final validation](lab/agentic-claude/harness.py.txt)
- [Original terminal submission and provider loop](lab/resolution/teacher_v2.py.txt)
- [Length repair and strict submission](lab/funded-rounds/round1/teacher_v3_adapter.py.txt)
- [Literal supporting-source search](lab/funded-rounds/round2/teacher_v4_adapter.py.txt)
- [Corrected v3 body-only request and response contract](lab/funded-rounds/round2/paired-baselines-repair-v3/adapter.py.txt)
- [Original corrected comparison evaluator](lab/funded-rounds/round2/paired-baselines-repair-v3/analyze.py.txt)
- [Original configuration](lab/EXPERIMENT.json.txt)
- [Dependency specification](product/pyproject.toml.txt) and [lockfile](product/uv.lock.txt)

`materialize.py` restores all archive files to a new explicit directory. No archived code executes during restoration. The original full evaluator requires the complete external data contract; only the selected final-decision algorithm is executed by `native.py`.
