# Production implementation parity and runtime

The proposed `operation-blocks:2` comparer preserves the original eligible winner and adds a bounded complete-helper search only on original abstention. The implementation was checked against the frozen research recipe across every native cohort available at the original sweep freeze, then checked on all supported known-gold queries and a deterministic sample of original winners and abstentions. These checks support using the reviewed implementation for the measured recipe. They do not prove that balanced scheduling preserves all prior admissions; the parent report explicitly accounts for displaced useful reports.

The candidate patch targets dry-lint commit `73709fdbe884c107b665400a186cb71caecc03f7`. It changes the plugin and tests, with no default enablement or CI changes. Integration and final repository validation are recorded separately. [Machine evidence](production-evidence.json) records exact code, patch and test hashes, the complete per-cohort parity/timing receipt, and supported-gold exposure counts. No source bodies or whole backgrounds appear in that receipt.

## What the implementation changes

Each native function is parsed once to produce the original first 12 eligible regions and, where eligible, one complete executable helper body. The original and fallback routes share the complete-background TF-IDF fit and frequencies, but keep separate retained-anchor state. Original `neighbours` runs first; an original allowed unseen winner keeps its score and position. The fallback uses at most 13 regions, eight anchors, 64 region postings per anchor and 64 candidate parents. The upper bounds on additional search work are 6,656 posting visits and 10,816 region comparisons per query.

The existing guards remain: 4–80 lines, 20–400 executable nodes, eight distinct tokens, two nongeneric calls, three shared concrete operations, two shared calls, a retained shared anchor, .65 region cosine and .1 whole-function cosine. Docstrings do not create retrieval operations. Nested-owner bodies are rejected. Native names, signatures, documentation and code supplied as Candidate evidence remain unchanged. Repeated region-posting frequency and the original source-order cap remain unchanged.

Comparer identity changes from `operation-blocks:1` to `operation-blocks:2`. Similarity is not declared reusable across changed context; the extra representation must not inherit a verdict-reuse assumption from a broader retrieval match. This work contains no measured deployment cache-hit rate or memory benchmark, and claims none.

## Parity and regression coverage

| Check | Measured result |
|---|---:|
| Compatible native-source cohorts | 10 |
| Native function documents | 119,312 |
| Complete background documents in those cohorts | 119,470 |
| Original/helper representations and posting maps | Exact across all ten cohorts |
| Query comparisons | 3,178 |
| Supported known-gold queries included | 211 |
| Sampled original winners preserved exactly | 964/964 |
| Returned/direct pair-score mismatches | 0 |
| Known duplicate exposure, original → treatment | 37/39 → 37/39 |
| Known separate exposure, original → treatment | 38/80 → 38/80 |

Representation and posting checks are exhaustive over these cohorts; the 3,178 query checks are not an exhaustive neighbour comparison for all 119,312 native functions. They include every supported known-gold query, all selected campaign queries, and a deterministic hash sample of up to 200 original winners and 200 abstentions per cohort. Query sampling did not use new source or judge labels. Known historical examples are regression evidence, not fresh holdout cases. The later [public-source extension](public-extension/README.md) is a separate receipt; its additional contexts are not silently included in these original parity totals.

The full supported-gold exposure check uses the original fixed concept ledger and separately records the paired ledger. Accepted duplicate and separate pair/background units total 119. Borderline and unaccepted/unknown observations remain separate in the machine receipt. The broader archive has missing-source and unsupported units; no untested row is counted as retained success or as a negative.

Twenty-one comparer tests pass with 190/190 statements covered; two partial branches remain. Another 139 relevant detector, discovery, plugin, comparer, cost, store and adopter-key integration tests pass. Tests exercise cleanup/finally and error-handler source, a standalone helper, reindexing after changed source, original-winner precedence and region bounds, and a docstring-only body that must not create executable evidence. These tests validate detection and source preservation, not a refactoring of adopter code.

The supplied test import order was corrected after root found a Ruff failure. The final patch copy passes Ruff with explicit `dry_lint` first-party classification matching PR109; the lab checkout lacks the original plugin module and initially classified its import differently. The production implementation was unchanged by that correction. The wider integrated-suite result is a separate receipt and is not inferred from these local tests.

## Measured runtime and cache scope

These are paired measurements of the proposed production implementation and original comparer on complete public backgrounds. Cold indexing includes parsing and fitting both representations in the treatment. Warm query totals use the same selected queries and fitted models, with original query work timed before treatment work. They are one-run local CPU observations, not repeated latency distributions or deployment guarantees.

| Complete public background / work | Original | Candidate | Added time |
|---|---:|---:|---:|
| LiteLLM: cold index, 37,604 documents | 27.463 s | 41.939 s | 14.476 s |
| LiteLLM: 529 paired warm queries | 2.455 s | 3.975 s | 1.520 s |
| OpenHands: cold index, 2,348 documents | 1.946 s | 2.877 s | .931 s |
| OpenHands: 277 paired warm queries | .199 s | .453 s | .254 s |

Cold indexing costs about 1.53× and 1.48× the original on these two backgrounds. Warm query totals are about 1.62× and 2.28×. Original cold timings were not collected for the other eight cohorts; the receipt leaves them null rather than inventing a comparison. Every cohort does have a paired warm-query measurement. These samples were selected for parity coverage and should not be interpreted as an average production query distribution.

A separate 1,000-query cached prototype timing exists in the local research record. It is not substituted for the production measurements above: it uses the research implementation and warm function-vector memoization. Provider request reuse is also separate. R1 made 106 fresh requests; the balanced panel made 71 fresh Haiku and 28 fresh Jev requests and reused 43 exact Jev answers. No provider work enters detection, and physical research spend does not measure adopter cache savings.

## Reproduction limits

The frozen R1 package supplies the original comparer and research fallback, while the final PR109 implementation and patch application are recorded separately. The machine receipt identifies the tested implementation and patch by SHA-256 and retains all per-cohort timing values. Those hashes establish identity; they do not replace the complete inputs required to repeat a fit.

Repeating full-source parity requires the pinned dry-lint base, complete matched background/native-source caches and the recorded deterministic query selection. Private inputs remain held, so the public appendix reports aggregate parity for those cohorts without redistributing them. The public R1 replay independently recomputes recorded admission and judge outcomes, but does not rerun full-corpus retrieval. The measured result supports the bounded opt-in change and exposes its cost; it does not claim free extra recall, zero scheduling loss, or new independent-family validation.
