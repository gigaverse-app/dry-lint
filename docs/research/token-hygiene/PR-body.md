## TLDR

Keep the current matcher. The body-word presence revision improves positive top-three ranks from 182/227 to 189/227, but default funded positives fall from 39/77 to 35/77. Its one emitted novel report is source-confirmed related, not a useful nominated-body duplicate. This PR publishes the closed experiment, original implementation/configuration, licensed selected source and portable recorded-result replay so future retrieval work can build on the measured limitations. Production behavior is unchanged.

[Read the canonical study](https://github.com/gigaverse-app/dry-lint/blob/research/study-token-hygiene/docs/research/token-hygiene/README.md).

```text
BEFORE: Engineer -> scattered lab artifacts -> hard to reconstruct the conclusion
AFTER:  Engineer -> one method package -> selected transform + recorded answer replay
```

| Measurement | BEFORE | AFTER | Evidence and interpretation |
| --- | ---: | ---: | --- |
| Positive default funded pairs (higher better) | 39/77 | 35/77 | Frozen paired comparison; four useful admissions lost |

The historical inventory is 617 records, not the evaluated denominator. Exact revision/scope comparisons, unsupported/private inputs, correlated pairs/families, unknown answers and minor/partial/related findings remain distinct. Actual paid usage is separate from the simulated $.04 query/batch allowance. The source-D small polling acceptance is retained where applicable. No third variant was run.

Validation: run `python3 transform.py`, `python3 reproduce.py replay`, and `python3 reproduce.py audit` in this directory. These commands are tested from a clean copy with no lab imports or providers. [Checks](https://github.com/gigaverse-app/dry-lint/blob/research/study-token-hygiene/docs/research/token-hygiene/CHECKS.json) record exact results. [Corpus acquisition contract](https://github.com/gigaverse-app/dry-lint/blob/research/study-token-hygiene/docs/research/token-hygiene/CORPUS.json) pins the separate goldens repository and distinguishes eight matching study hashes from missing/private backgrounds.

Merge the research record, not the tested recipe. No CI, provider, credential or production changes.
