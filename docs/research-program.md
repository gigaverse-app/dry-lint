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

The earlier studies in [what the recall research established](research-results.md) (#110 to #121) are not
triaged here yet. Their closing lesson is this program's Phase 2: "trace the first loss: source scope,
score/filter, shortlist, funding, or judging."

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
- **2026-11-11:** Track B differences passed both bars (AUC 0.963 inside the interval, +0.92 points of false
  reports at 0.4, 47 of 50 differences real); shipped in [#192](https://github.com/gigaverse-app/dry-lint/pull/192).
