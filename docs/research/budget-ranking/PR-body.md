## TLDR

Changing candidate order can buy a useful report while hiding scheduling regressions. This PR preserves the budget-ranking study as a reproducible research record: one bounded public test-support addition, one related architectural false lead, and zero added reports from the fairness revision. Keep the current default. Merging the record lets future work rerun the original ordering on a complete 25-candidate campaign and replay all 124 public cases without providers.

[Read the study](https://github.com/gigaverse-app/dry-lint/blob/research/study-budget-ranking/docs/research/budget-ranking/README.md), including original code, tested specifications, exact prompts/answers, licensed selected sources, source decisions and unknowns. This changes research documentation and its offline tools only.

```text
BEFORE: lab-only pools + ledgers -> manual reconstruction of ranking benefit
AFTER: pinned public campaign -> original ordering/admission -> recorded answers -> paired report replay
```

| Metric and unit | Before: current | After: tested treatment | Evidence and implication |
|---|---:|---:|---|
| R1 funded pairs /74 | 55 | fixed 57; cost 63 | More exposure; neutral without usefulness |
| R1 useful emitted reports | 2 | 3 in either flat sort | +1 same bounded family; higher better |
| R1 related emissions | 0 | 1 in either flat sort | Lower better; existing policy already shared |
| R2 known Claude reports /50 | 5 | 5 | No gain; shared malformed control leaves 5–6 in each |
| Fresh research spend | — | R1 $0.69653208; R2 $0.59135360 | Actual paired judging, separate from synthetic $0.04 caps |

The current final historical addendum is represented only by sanitized aggregates. Private adopter source, prompts, identifiers and timelines are excluded. Public R2's paid malformed answer stays unknown; source-unknown pairs are not negatives. No production policy, providers, credentials, agents or CI changes.

Validation: clean-copy `python3 algorithm.py`, `python3 replay.py`, and `python3 verify.py`; exact original order/funding for all four arms in one public campaign; raw Claude parsing and 124-case report/cost replay; source hashes, local links, gzip-content sensitive-pattern scan and checksums. [Validation and limits](https://github.com/gigaverse-app/dry-lint/blob/research/study-budget-ranking/docs/research/budget-ranking/VALIDATION.md). The corpus remains in the [separate pinned goldens repo](https://github.com/gigaverse-app/dry-lint-goldens/tree/bb29c4b71987008d06c2381a68b6833b6d542e3e); both paid-study backgrounds have exact catalog matches.

[Full rebuild requirements](https://github.com/gigaverse-app/dry-lint/blob/research/study-budget-ranking/docs/research/budget-ranking/DATA-CONTRACT.json) distinguish the portable selected-campaign and recorded-result reproduction from reconstructing the full experiment. Root owns branch creation, copying this bundle to `docs/research/budget-ranking/`, pushing and PR creation.
