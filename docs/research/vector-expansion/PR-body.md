## TLDR

Stop the latent and sparse-association recipes. Latent compression worsens retrieval. Sparse expansion retains 182/227 positive top-three results and 13/78 known funded positives; it adds one source-accepted SMALL polling-helper report, not a substantial gain. Raw already ranks that lead fourth, so the extra slot may explain the result. This PR publishes the closed experiment, original implementation/configuration, licensed selected source and portable recorded-result replay so future retrieval work can build on the measured limitations. Production behavior is unchanged.

[Read the canonical study](https://github.com/gigaverse-app/dry-lint/blob/research/study-vector-expansion/docs/research/vector-expansion/README.md).

```text
BEFORE: Engineer -> scattered lab artifacts -> hard to reconstruct the conclusion
AFTER:  Engineer -> one method package -> selected transform + recorded answer replay
```

| Measurement | BEFORE | AFTER | Evidence and interpretation |
| --- | ---: | ---: | --- |
| Known positive protected funded conditions (higher better) | 13/78 | 13/78 | Frozen paired comparison; one small novel report, no substantial gain |

The historical inventory is 617 records, not the evaluated denominator. Exact revision/scope comparisons, unsupported/private inputs, correlated pairs/families, unknown answers and minor/partial/related findings remain distinct. Actual paid usage is separate from the simulated $.04 query/batch allowance. The source-D small polling acceptance is retained where applicable. No third variant was run.

Validation: run `python3 transform.py`, `python3 reproduce.py replay`, and `python3 reproduce.py audit` in this directory. These commands are tested from a clean copy with no lab imports or providers. [Checks](https://github.com/gigaverse-app/dry-lint/blob/research/study-vector-expansion/docs/research/vector-expansion/CHECKS.json) record exact results. [Corpus acquisition contract](https://github.com/gigaverse-app/dry-lint/blob/research/study-vector-expansion/docs/research/vector-expansion/CORPUS.json) pins the separate goldens repository and distinguishes eight matching study hashes from missing/private backgrounds.

Merge the research record, not the tested recipe. No CI, provider, credential or production changes.
