# Recover operations beyond the embedding prefix

Use `cpu-tail-rrf` as an **opt-in extra discovery route** when a long Python or TypeScript function repeats a complete operation that its first 256 wordpieces do not show. It combines complete-statement embeddings with operation-block ranks and proposes at most one extra pair of full functions. It is intended for a repository-specific trial with an existing vector cache; the cold CPU cost is substantial.

A measured example is T3's desktop portal registration. `LinuxCaptureConnection.backend` and `PortalCaptureShortcut.initialize` both construct a D-Bus request that registers the host application, behind different initialization workflows. The complete-statement route ranks the pair first at cosine .83356; the block route has no eligible match. Independent review supports sharing the registration operation while keeping caller-specific errors and initialization order local. The native judge reports it at .72. This is a bounded shared operation, not a recommendation to merge the whole functions.

## What the combination does

The existing TF-IDF, operation-block and prefix-embedding routes run first. The additional route:

1. Keeps the existing full-source prefix vectors. It also extracts at most two disjoint complete statement regions from each long function, choosing larger eligible regions first and breaking equal sizes by source order. A region must extend beyond the original prefix, contain 48–180 tokenizer tokens, and fit with the function-name prefix within 256 tokens. Python docstring-only statements are excluded. Native line text is preserved.
2. Takes the best prefix-to-statement, statement-to-prefix or statement-to-statement cosine. Prefix-to-prefix comparison stays with the existing route. Statement matches require cosine at least .80.
3. Obtains the top 20 eligible neighbours from that route and the existing operation-block comparer. Eligibility, including earlier-route ownership and settling, is applied **before** each cap.
4. Adds `1 / (60 + rank)` for each route that proposes a neighbour. Missing routes add zero; ties use original corpus order. It emits at most the highest-ranked unseen neighbour, retaining its **raw rank score**.

A tail-only first-ranked pair therefore has score `1/61`, rounded by the existing Detector to `.016`. Even agreement at rank one scores only `2/61`. These numbers are neither cosine nor duplication confidence. Returning the original .83 cosine made new candidates jump ahead of useful older exploration candidates under the existing budget sorter. Raw rank scores avoided those losses in this selected experiment, without a protected slot, a budget-dependent comparer, or a scheduler change. Query fairness can still let an extra candidate displace another query's work; the route does not guarantee preservation under every campaign.

All candidates and judge prompts retain the complete native functions. The view text is only a retrieval representation. No learned weights, judge scores or provider calls are involved in detection. Cache and comparer identities include the encoder/runtime, view recipe and ranking contract; this comparer forbids similarity-based verdict reuse.

## Measured result and its boundary

The comparison appends this route to PR109's TF-IDF3 baseline plus TF-IDF20/.35, operation-blocks2/top1 and prefix CPU/.65/top1. It uses actual cold CampaignStore admissions at a $0.04 campaign cap and Haiku 5.5/shared-operations/2048, .50 reporting/drop thresholds, .80 drift and no escalation. These are explicit experimental settings, not evidence of adopter deployment. Cached exact answers still receive normal logical charges in each arm.

| Measurement | Existing stack | With extra raw-rank route |
| --- | ---: | ---: |
| Admissions across 66 selected single-function campaigns | 191 | 207 |
| Useful bounded reports among the 16 added pairs | 0 | 3 |
| Tiny-overlap reports among the added pairs | 0 | 3 |
| Unsupported reports among the added pairs | 0 | 0 |
| Prior admissions lost | — | 0 |
| Admissions across five four-function shared campaigns | 27 | 27 |

All 338 matched labeled/context regression units retain their baseline admission outcomes, including 309 accepted positive/negative contexts and 29 borderline/unaccepted/unknown contexts. This does **not** mean all 338 were retrieved or reported. The positive families gained here are desktop portal registration, manual-permission visibility after project auto-approval, and session extension-panel entry discovery: three families across T3 and opencode. Tiny reports are kept separate rather than counted as useful gains.

The first high-score tail and fusion arms lost useful reports. The raw-rank successor was selected after examining those failures, so this is development evidence. The five shared campaigns show no added report opportunity. There is no historical PR replay, sequential settlement, conditional-relative/report cascade, or fresh holdout result for this method. Tail and fused selection chose the same new pairs in the tested panel: the evidence supports the new representation and its budget ordering, **not extra predictive power from fusion or learned boosting**.

The [CPU study](https://github.com/gigaverse-app/dry-lint/pull/116) contains the full comparison, exact source, prompts, answers, original failed arms, independent labels and reproduction contract. The [ensemble study](https://github.com/gigaverse-app/dry-lint/pull/114) explains what this does and does not establish about combining signals.

## Configure and measure locally

Install the optional `dry-lint[cpu-embedding]` dependencies and provide the exact pinned model files described in the [CPU setup guide](cpu-embedding.md#install-and-configure). Both CPU routes can share its validated disk vector cache. The plugin never downloads weights or acquires credentials.

In `.dry-lint.toml`, retain the evaluated route order:

```toml
[discovery]
enabled = true
comparers = [
  { use = "tfidf", neighbours = 20, min_similarity = 0.35, min_similarity_small = 0.35 },
  { use = "operation-blocks", neighbours = 1 },
  { use = "cpu-embedding", neighbours = 1, model_dir = ".dry-lint-local/minilm", cache_dir = ".dry-lint-local/vectors" },
  { use = "cpu-tail-rrf", neighbours = 1, model_dir = ".dry-lint-local/minilm", cache_dir = ".dry-lint-local/vectors" },
]
```

Use `[tool.dry-lint.discovery]` in `pyproject.toml`. Paths are relative to the process working directory. The explicit comparer list replaces implicit exploration, so omitting TF-IDF changes the comparison. The normal baseline remains first. No judge, threshold, budget or default changes are required by the plugin itself.

```bash
dry-lint detect --root . --base origin/main --out candidates.json
```

This detection command makes no provider calls. Compare treatment and baseline with the same base/head and budget; inspect full source and actual report additions/losses before adopting. Self and ambiguous identities are ineligible; discovery can include same-file pairs. The three useful additions measured here are cross-file. Missing source and unanswered questions remain unknown.

Cold inference is the main cost. On two measured public snapshots, the standalone prefix comparer took 102.07s for 1,601 T3 functions and 178.00s for 2,349 OpenHands functions; the composite took 118.84s and 182.99s. These are single shared-host measurements, not repeated performance estimates. With all validated vectors cached, composite indexing took 5.15s and 7.06s with zero encodes. The actual configured stack also retains the earlier prefix and block indexes; a standalone comparison understates its total memory/time. Appending the warm composite while those earlier comparers remained loaded added 5.19s/7.60s and about 124.5 MiB of process peak RSS on these two snapshots. Full gain-sized cold inference and production PR latency were not measured. Keep a persistent cache and measure the complete stack on your repository.
