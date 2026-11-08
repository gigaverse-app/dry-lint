# Acquire exact public study backgrounds

The corpus stays in **gigaverse-app/dry-lint-goldens**, separate from this source repository. [Exact study-hash lookups](data/background-acquisition.json) match the migration catalog at commit `bb29c4b71987008d06c2381a68b6833b6d542e3e`. A matching repository name is insufficient: compressed bytes, revision, extraction scope and ordering must match.

```bash
git clone https://github.com/gigaverse-app/dry-lint-goldens.git /tmp/dry-lint-goldens
git -C /tmp/dry-lint-goldens checkout --detach bb29c4b71987008d06c2381a68b6833b6d542e3e
python3 /tmp/dry-lint-goldens/corpus.py verify
python3 /tmp/dry-lint-goldens/corpus.py materialize candidate-first-gold-v1 --out /tmp/candidate-first-gold
python3 /tmp/dry-lint-goldens/corpus.py materialize public-gold-v1 --out /tmp/public-gold
```

For each `exact_study_hash_present` row, use the materialized dataset-relative path and verify its SHA-256 equals `study_background_sha256`. Do not copy a corpus into this research PR. Missing catalog matches remain `study_hash_not_in_pinned_public_catalog`; private historical backgrounds are counted without publishing identifiers. A public sparse background does not supply native source, vectors, labels, ledger history or missing provider answers. Preserve held-source licensing separately in [holds](data/holds.json).

This lookup used the provided migration catalog and verified its manifest hashes locally; it did not fetch GitHub or rerun corpus extraction. Acquisition availability does not retroactively enlarge any study's evaluated denominator. Full rerun requirements remain in [the manifest](FULL-RERUN.json).
