## TLDR

Source-reading judges might recover useful reports when function bodies omit helper contracts. This PR publishes the corrected experiment and runnable recorded-source kit, so reviewers can inspect why this recipe should stay an investigation tool rather than become a default. Both arms reported the same useful operations; source reads resolved two non-reporting uncertainties at greater cost. Merging preserves the negative result, original implementation and comparator repair without changing product behavior.

```text
BEFORE: full function pair -> supplied-source judge -> final report decision
AFTER:  full function pair -> judge <-> bounded pinned-source tools -> final report decision
```

| Novel R2 metric (9 pairs) | Before: corrected body-only | After: source tools | Meaning |
|---|---:|---:|---|
| Certain finals (higher helps interpretation) | 6/9 | 8/9 | Two supported non-report resolutions |
| Useful reports (higher preferred) | 1 | 1 | No added report |
| Actual novel USD (lower preferred) | 0.085286 | 0.233598 | Recorded settled usage |

V3 has nine valid finals: six certain and three uncertain. Old unavailable-tool replies remain unknown; the failed forced-tool repair holds $0.127882 as an unknown maximum, separate from settled spend. This is selected development evidence, one response per request, with differing procedures; it is not a pure same-prompt causal ablation. Tiny operations, related judgments and Windows source disputes remain explicit.

Read the [canonical report](https://github.com/gigaverse-app/dry-lint/blob/research/study-agentic-judge/docs/research/agentic-judge/README.md), [original answers](https://github.com/gigaverse-app/dry-lint/blob/research/study-agentic-judge/docs/research/agentic-judge/CASES.md), [original implementations](https://github.com/gigaverse-app/dry-lint/blob/research/study-agentic-judge/docs/research/agentic-judge/data/original/README.md), and [reproduction boundary](https://github.com/gigaverse-app/dry-lint/blob/research/study-agentic-judge/docs/research/agentic-judge/REPRODUCTION.md). Python-only replay recomputes the corrected comparison; `native.py` executes original final parsing on 18 recorded finals. The package includes 18 exact licensed public source files, sanitized observable answers and provenance hashes. Full source-search and full-corpus reconstruction require the [external manifest](https://github.com/gigaverse-app/dry-lint/blob/research/study-agentic-judge/docs/research/agentic-judge/FULL-RERUN.json).

Validation: clean-copy `reproduce.py`, `native.py`, and `audit.py`; exact source spans, request hashes, reporting/uncertainty parity, usage/cost parity, local links and decompressed-payload scan. No provider calls, credentials, CI changes, agents or new experiments. Root owns branch creation and publication.
