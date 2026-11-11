# Research program

Most of dry-lint's research so far could not reach a decision. Experiments ended with most outcomes "unknown",
because the only labels covered pairs the detector had already proposed. A method that finds something new cannot
win when every new find is scored as unknown. This program builds a human-confirmed reference first, measures the
shipped product against it, and only then spends money on new methods.

Started 2026-11-11. The [log](#log) at the end records what has run.

## The goal

dry-lint should report the duplicates reviewers act on, and we should know which ones it misses. Today we know its
precision on model-labelled pairs (4.1% of labelled non-duplicates reported at 0.5, see the
[benchmark](benchmark.md)). We do not know its recall against duplicates people actually removed.

## Rules for every experiment

1. **No experiment without labels for what it finds.** If a method can surface pairs the reference does not cover,
   those pairs are labelled before anything is decided.
2. **The pass bar and the sample size are written down before the run.** When the sample cannot separate the
   variants, the result is "inconclusive", never "rejected".
3. **At least two public repositories.** The evidence can then be shared, and a two-repository bar can be met.
4. **Every experiment ends in a decision.** Ship as a default, park with an honest status, or drop. A record that
   it ran is not a result.
5. **Cheapest first.** Reuse what already exists (encoder matrices, stored verdicts) before computing anything new.

## Phase 0: an honest status for the merged research

Each merged study, sorted by what its own numbers can support. "Untested" means the study never ran a test that
could have shown its idea working; it is not a rejection.

| Study | Status | Why |
| --- | --- | --- |
| [grouped-pair-judging](https://github.com/gigaverse-app/dry-lint/tree/main/examples/research/grouped-pair-judging) | Solid | 78 commits, over 1,250 pairs per variant, Opus as referee. Cheaper and less precise. |
| [budget-family-proof](https://github.com/gigaverse-app/dry-lint/tree/main/examples/research/budget-family-proof) | Solid, one case | A patch with passing tests: 18 guards in ten functions share one helper. |
| [cross-repo-recall-audit](https://github.com/gigaverse-app/dry-lint/tree/main/examples/research/METHODS/cross-repo-recall-audit) | Solid | 159 known duplicates on two panels; fusion's gain reversed on the second. |
| [family-judging](https://github.com/gigaverse-app/dry-lint/tree/main/examples/research/family-judging) | Weak | 748 labelled pairs, but one prompt version, one model setting, one run; seven follow-ups never run. |
| [residual-budget](https://github.com/gigaverse-app/dry-lint/tree/main/examples/research/residual-budget) | Weak | 12 additions across 11 campaigns. |
| [grounded-operation-claims](https://github.com/gigaverse-app/dry-lint/tree/main/examples/research/grounded-operation-claims) | Weak | 27 reports. |
| [complementary-signal-learning](https://github.com/gigaverse-app/dry-lint/tree/main/examples/research/METHODS/complementary-signal-learning) | Weak | The learned ranker trained on 10 examples. |
| [adaptive-judge-budget](https://github.com/gigaverse-app/dry-lint/tree/main/examples/research/METHODS/adaptive-judge-budget) | Untested | One report across all arms; nothing could separate them. |
| [learned-budget-policy](https://github.com/gigaverse-app/dry-lint/tree/main/examples/research/METHODS/learned-budget-policy) | Untested | Four campaigns, 37 reports against 40, all additions in one repository. |
| [spectral-family-recovery](https://github.com/gigaverse-app/dry-lint/tree/main/examples/research/METHODS/spectral-family-recovery) | Untested | Its own README calls it a "saturated/unknown smoke"; 417 of 418 leads unknown. |
| [cluster-calibration](https://github.com/gigaverse-app/dry-lint/tree/main/examples/research/METHODS/cluster-calibration) | Untested | 323 and 420 of 510 outcomes unknown. |
| [confirmed-cluster-expansion](https://github.com/gigaverse-app/dry-lint/tree/main/examples/research/METHODS/confirmed-cluster-expansion) | Untested | About 2,500 leads produced and never labelled. |
| [refactor-discovery-bundles](https://github.com/gigaverse-app/dry-lint/tree/main/examples/research/METHODS/refactor-discovery-bundles) | Untested | One example, no real confirmed seeds. |
| [tfidf-blindspot-recovery](https://github.com/gigaverse-app/dry-lint/tree/main/examples/research/METHODS/tfidf-blindspot-recovery) | Untested | "No numeric yield"; its useful part shipped as operation blocks. |
| [encoder-corpus-evaluation](https://github.com/gigaverse-app/dry-lint/tree/main/examples/research/METHODS/encoder-corpus-evaluation), [coderank](https://github.com/gigaverse-app/dry-lint/tree/main/examples/research/METHODS/coderank-cpu-evaluation), [gemma](https://github.com/gigaverse-app/dry-lint/tree/main/examples/research/METHODS/gemma-cpu-evaluation) | Untested | 174 similarity matrices and about 14 hours of compute, never used to rank anything. |

The earlier studies in [what the recall research established](research-results.md), rated the same way from their
pull requests and linked docs. None of them wrote down a pass bar or sample size before running.

| Study | Status | Why |
| --- | --- | --- |
| [Token hygiene and weighting, #111](https://github.com/gigaverse-app/dry-lint/pull/111) | Solid | 227 positives; top-three ranks 182 to 189, but funded positives 39/77 to 35/77, four useful admissions lost. |
| [Operation/contract tokens, #112](https://github.com/gigaverse-app/dry-lint/pull/112) | Weak | 61 of 72 known positives funded before and after; one minor reuse added. |
| [Budget-aware ranking, #113](https://github.com/gigaverse-app/dry-lint/pull/113) | Weak | Useful reports 2 to 3 in one campaign; known reports 5/50 unchanged. |
| [Signal ensembles, #114](https://github.com/gigaverse-app/dry-lint/pull/114) | Weak | No added report across 28 answered pairs, 28 more unknown; the raw-rank follow-up added 3 in 66 campaigns. |
| [Operation blocks, #115](https://github.com/gigaverse-app/dry-lint/pull/115) | Weak, shipped | 9 net useful and 3 unsupported added in a labelled delta; a 47-revision replay added none. Runs inside `balanced`. |
| [CPU embeddings, #116](https://github.com/gigaverse-app/dry-lint/pull/116) | Weak, opt-in | 3 useful among 16 added pairs in 66 single-function campaigns; none in 5 shared ones. Shipped opt-in as `cpu-tail-rrf`. |
| [Latent vectors and sparse associations, #118](https://github.com/gigaverse-app/dry-lint/pull/118) | Weak | Funded positives 13/78 before and after; one small report added. |
| [Model/function signals, #119](https://github.com/gigaverse-app/dry-lint/pull/119) | Weak | 32/78 positives funded either way; 16 of 18 treatment-only pairs source-unknown. |
| [Linked documentation, #120](https://github.com/gigaverse-app/dry-lint/pull/120) | Weak | 31 known positives, funded counts unchanged in both presets. |
| [Historical protected recovery, #121](https://github.com/gigaverse-app/dry-lint/pull/121) | Weak | Half-name weighting: 3/5 to 5/5 in one family over eight revisions; the guard lost 19 report versions. |
| [Mechanically extracted judge context, #110](https://github.com/gigaverse-app/dry-lint/pull/110) | Untested | Two novel useful cases per model, recovered by neither arm. |
| [Source-reading judges, #117](https://github.com/gigaverse-app/dry-lint/pull/117) | Untested | Nine novel pairs; one useful report in each arm. |

Their closing lesson is this program's Phase 2: "trace the first loss: source scope, score/filter, shortlist,
funding, or judging."

## Phase 1: a reference from git history

Projects record their own duplicates when they remove them. Mine four to six public Python and TypeScript
repositories, starting with LiteLLM and OpenHands, for two kinds of commit:

- **Pairs.** A commit deletes or shrinks a function and points its callers at a function that already existed.
- **Families.** A commit adds a helper and replaces two or more copies with calls to it.

For every case, also find the commit that introduced the later copy, from the history of its lines.

**Labels.** The maintainer's commit is the first label. Opus then confirms that the functions, as they stood before
the commit, duplicated each other. A person reviews a random sample of 50.

**Bar, written before mining:**
- The person agrees with at least 45 of the 50 sampled cases. Until that review, the reference is marked
  "maintainer commit plus Opus, human review pending".
- At least 200 pairs and 40 families, from at least four repositories, with at least 50 pairs in each of two.

**Where it goes.** Each case is stored in [dry-lint-goldens](https://github.com/gigaverse-app/dry-lint-goldens) as a
judged pair or family: the two function bodies before and after, the commits, and the labels. Never whole files.
Files stay small enough to read in a browser.

## Phase 2: measure today's product against the reference

For each case, replay `dry-lint check` with the shipped `balanced` preset on the commit that introduced the later
copy, against its parent. Record the first loss:

1. **Never proposed.** No route put the pair in front of the judge. A candidate problem.
2. **Proposed, judged no.** The judge scored it below 0.4. A judge problem.
3. **Proposed, not funded.** The budget ran out first. A budget problem.
4. **Reported.**

Record which route proposed it: the baseline, exploration, operation blocks or relatives. Report each share per
repository, with a 95% interval.

**This phase sets the agenda.** The largest loss decides where the next money goes.

## Phase 3: three tracks

Each track runs only if Phase 2 says its loss matters, except where marked. Every bar compares against the shipped
`balanced` preset.

**Track A: finding more candidates.** Runs if "never proposed" is the largest loss.
- First, rank with the existing encoder matrices; they are already computed.
- Then TF-IDF and embeddings combined, and deeper operation blocks.
- **Bar:** at least 10% more reference cases reported in each of two repositories, at no more judge spend, with
  false reports on the labelled pairs no more than one point above the shipped judge.

**Track B: what the judge says.** Runs regardless, because it improves every report.
- **Differences between copies.** One more answer field listing how the two functions behave differently: what each
  does, the consequence, and what has to be decided. The family study's most useful find was such a difference:
  three budget checks block at `>=` and one at `>`.
  - **Bar:** AUC on the labelled pairs stays inside the shipped judge's interval (0.952 to 0.974), false reports
    rise by no more than one point, and Opus confirms at least 40 of 50 sampled differences as real.
  - **Extra check:** a consolidation commit in the reference that had to pick one behaviour shows real drift.
- **Pairs where both functions call the same helper.** First count how often stored verdicts give this as the reason.
  **Bar:** build a rule only if at least 5% of judged pairs are of this kind.
- If "proposed, judged no" is the largest loss in Phase 2, read those cases before changing the prompt.

**Track C: families.** Runs regardless, because the reference contains families.
- The product's structural nomination (`[discovery.families]`) proposes families; the pair judge confirms each pair
  before anything is reported.
- **Bar:** confirmed families are at least as precise as pair reports, measured the same way, at no more than $0.50
  per useful family through `dry-lint scan`, and find at least half of the reference families whose copies were
  present at one revision.

## Phase 4: ship or park

What clears its bar becomes a default. The rest goes into the research directory with an honest status.

**Parked from the start:** spectral cuts, learned or adaptive budget allocation, grouped questions, and clustering
(including e-means). They are revisited only if Phase 2 shows the judge budget limits recall.

## Cost and constraints

- **API:** about $30 to $50 for the whole program.
- **People:** about an hour to review the 50 sampled reference cases.
- **Disk:** replaying history needs repositories and per-revision function indexes. Indexes are built one revision
  at a time and deleted after use.

## Log

- **2026-11-11:** program written; Phase 0 statuses recorded above.
- **2026-11-11:** Phase 0 extended to the earlier studies #110 to #121.
- **2026-11-11:** Track B, pairs where both functions call the same helper: the frequency bar passed (about 21% of
  the 756 labelled pairs), but 62 of the 178 such pairs are labelled duplicates: functions that call the same helpers
  in the same order are still duplicated orchestration. A rule would discard them, so it is dropped.
- **2026-11-11:** Phase 1, first mining run: 166 cases from LiteLLM and OpenHands. Opus labelled 107 yes, 46 partial,
  12 no and 1 unclear. About 35 of the real ones had copies that already behaved differently before the consolidation.
  Widening to more repositories is in progress.
- **2026-11-11:** Track B differences passed both bars (AUC 0.963 inside the interval, +0.92 points of false
  reports at 0.4, 47 of 50 differences real); shipped in [#192](https://github.com/gigaverse-app/dry-lint/pull/192).
- **2026-11-12:** Phase 1 done. 557 cases from the full history of six public repositories (LiteLLM, OpenHands,
  Saleor, Zulip, Prefect, NetBox). Opus: 453 yes, 60 partial, 42 no, 2 unclear; 184 of the 513 real ones had already
  drifted. 199 real pairs (bar 200; the second repository has 43 against a bar of 50) and 314 real families (bar 40).
  402 cases are in [dry-lint-goldens](https://github.com/gigaverse-app/dry-lint-goldens) under `history-reference/`.
  The human review of 50 sampled cases is pending.
- **2026-11-12:** Phase 2 done (details in `examples/research/history-reference/README.md`). On 424 replayable
  cases the shipped `balanced` preset reports 57% (52 to 61) on the commit that introduced the later copy, 62% of the
  clear ones. First losses: never proposed 20%, not funded 14% (mostly the 50-calls-per-commit cap on big commits,
  not the dollar budget), judged below the line 9% (every score 0.15 to 0.35). The two product rules "one calls the
  other" and "Python special method" dismissed 19 real duplicate pairs. Agenda: Track A first, run the fast way
  (candidates only, then judge only the target pair); then the call cap on big commits, which un-parks budget
  allocation for that one question; then the judge's low scores.
