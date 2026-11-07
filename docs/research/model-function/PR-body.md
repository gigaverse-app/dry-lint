## TLDR

Linking functions through their data models might expose repeated operations that token retrieval misses. This PR preserves both tested static join recipes, their useful scoped findings and their negative promotion result: no known-positive funding gain from the original recipe, and no incremental reports from 18 fully answered revised treatment-only pairs. Keep function-only as the default. Merging the record makes the original operation matcher and recorded public results reproducible without judge calls.

[Read the study](https://github.com/gigaverse-app/dry-lint/blob/research/study-model-function/docs/research/model-function/README.md), with original code, configurations, native source/resolved links, exact prompts/model settings, original answers and final source decisions.

```text
BEFORE: function tokens -> original ranked/funded candidates -> judge
R1:     baseline + similar model shapes/shared fields -> one protected extra -> same judge
R2:     baseline + same model/matching field operations -> one protected extra -> same judge
REPLAY: original matcher + selected native source -> recorded admissions/answers -> paired results
```

| Metric and unit | Before: function-only | After: joined route | Evidence / implication |
|---|---:|---:|---|
| Original default positives funded /78 | 32 | 32 | No added coverage; higher better |
| Original default separate pairs funded /104 | 16 | 17 | Extra known-negative exposure; lower better |
| Revised supplement funded pairs /48 | 30 | 48 | 18 treatment-only candidates |
| Revised supplement reports /48 | 7 | 7 | Zero incremental reports |
| Original default aggregate normal estimates | $5.63708786 | $6.67979714 | Estimates across synthetic campaigns, not spend |
| Actual fresh research judging | — | R1 $0.20703060; R2 $0.51609920 | Separate from $0.04 logical batch cap |

The final Source-D interpretation retains five bounded extractions and one tiny convenience, all baseline-cofunded. Two treatment-only pairs are source-reviewed (related and negative); 16 remain source-unknown, with zero known original-policy emissions across all 18. Seven supplemental reports are five bounded, one related and one source-unknown. Test-maintenance wins and standalone model-contract findings are separate from production/function-join recall.

Validation: clean-copy execution of the original Python signature matcher reproduces 15 context hashes and source-line bindings; 115-record result replay preserves 32 unanswered first-round novels. [Validation](https://github.com/gigaverse-app/dry-lint/blob/research/study-model-function/docs/research/model-function/VALIDATION.md) also covers source hashes, exact prompts, report boundaries, links and sensitive-pattern scans inside gzip files. Payloads comprise 87 licensed public records plus 28 source-free holds; no private adopter source/prompts/IDs are published.

Four paid-case background hashes match the [separate pinned goldens corpus](https://github.com/gigaverse-app/dry-lint-goldens/tree/bb29c4b71987008d06c2381a68b6833b6d542e3e); the held fifth is explicitly missing. [Full reconstruction requirements](https://github.com/gigaverse-app/dry-lint/blob/research/study-model-function/docs/research/model-function/DATA-CONTRACT.json) distinguish this selected algorithm/result replay from a full retrieval run. No provider, credential, agent, production or CI changes. Root owns copying to `docs/research/model-function/`, pushing and opening the separate PR.
