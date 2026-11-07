## TLDR

Whole-function retrieval can miss a useful helper inside a larger workflow. This PR publishes the region comparer, its recorded recovery and a failed coverage-veto revision, so reviewers can inspect both the bounded opt-in mechanism and why the veto should not ship. RF14 is a useful diagnostic recovery; the veto removes it and a useful atomic-commit opportunity. No default or balanced-preset report gain is established.

```text
BEFORE: whole-function baseline3 + explicit TF-IDF20 -> judge
AFTER:  same baseline + one guarded syntax-region parent -> judge
REVISION: remove regions covered by a baseline neighbor -> fewer extra parents
```

| Measured quantity | Before | After | Interpretation |
|---|---:|---:|---|
| Accepted duplicate funded contexts (/39; higher preferred) | Whole-function: 35 | Plus blocks: 37 | Exposure, not emitted-report gain |
| Accepted separate funded contexts (/80; lower preferred) | Whole-function: 35 | Plus blocks: 38 | More separate-pair judging |
| Extra selected native queries | Original: 1,132 | Residual veto: 692 | 13,256 rare-anchor query denominator |
| Reviewed useful opportunities retained | Original: 2 | Residual veto: 0 | Two distinct useful pair losses |

The shared 617-record inventory is not the evaluated denominator: 103 source-supported Python records support the archived conditional comparison. The later complete-source census covers only two public pinned backgrounds (39,952 functions; 39,806 native spans). RF14 native concept and balanced Haiku answers remain unknown; Sonnet/shared-operations is not a substitute. Fresh actual spend is $0.22461896 and $0.22776080, separate from simulated $0.04 funding. Related cleanup scaffolding remains related, and the veto has no demonstrated false-report prevention in reviewed report-bearing cases.

Read the [canonical report](https://github.com/gigaverse-app/dry-lint/blob/research/study-operation-blocks/docs/research/operation-blocks/README.md), [original answers](https://github.com/gigaverse-app/dry-lint/blob/research/study-operation-blocks/docs/research/operation-blocks/CASES.md), [original algorithm/configuration](https://github.com/gigaverse-app/dry-lint/blob/research/study-operation-blocks/docs/research/operation-blocks/data/original/README.md), [portable reproduction](https://github.com/gigaverse-app/dry-lint/blob/research/study-operation-blocks/docs/research/operation-blocks/REPRODUCTION.md), and [full rerun manifest](https://github.com/gigaverse-app/dry-lint/blob/research/study-operation-blocks/docs/research/operation-blocks/FULL-RERUN.json). Exact public background matches use the separate pinned [goldens acquisition contract](https://github.com/gigaverse-app/dry-lint/blob/research/study-operation-blocks/docs/research/operation-blocks/CORPUS.md); private/missing inputs are not treated as reproduced. Original provenance hashes remain distinct from sanitized publication hashes.

Validation: clean-copy recorded replay, original selected-algorithm replay, local links, source/request hashes, secret scan including compressed source, and private-payload boundary checks. No production/CI changes, provider calls, credentials, agents or new experiment. Root owns creation/push of this separate research branch.
