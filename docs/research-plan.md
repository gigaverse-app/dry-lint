# Detector research plan

**Stop adding tokens to the one TF-IDF bag. Retrieve from several channels, each with its own reserved candidate
slot, and correct for hub functions before choosing neighbours.** Every token family tried so far found a few new
pairs and displaced a similar number of known ones. The limiting factor is competition for the three neighbour
slots, not a shortage of signal.

This page records the evidence so far, the hypotheses it suggests, and the experiments queued to test them, with
decision rules fixed before their results are seen. It changes no runtime behaviour.

**Status:** E1 to E3 have run as [the channel trial](channel-trial.md); no variant met the decision rules.
Reserved slots keep every known duplicate but their extra pairs are judged real about 15% of the time, against 38%
for the baseline scan. Next: E4 (does the judge filter them?) and E9 (a less brittle backlog rule).

## What we know

| Source | Finding |
| --- | --- |
| [Benchmark](benchmark.md#detector-tf-idf-and-embeddings) | TF-IDF ranks known duplicates well (12 of 13 seeds first) but separates duplicates from false alarms poorly: AUC 0.66, against 0.86 for code embeddings that cost minutes to hours of indexing. |
| [Backend follow-up](benchmark.md#backend-follow-up-more-signals-are-not-always-better) | Field/key identities and removing annotation noise helped. Strings, receivers, operators and enclosing-class words did not. |
| [Synonym and signature follow-up](benchmark.md#follow-up-synonyms-stopwords-size-and-call-signatures) | Six hand-written synonym groups, extra stopwords, a lower `max_df`, a size penalty, keyword shapes and attribute roles: none improved retrieval of the 110 judged pairs; several displaced a real duplicate from `scan`. |
| [Dryer comparison](dryer-comparison.md) | Structural Jaccard adds 19 backlog pairs TF-IDF misses (2 plausible consolidations), takes about 10 times as long, and is mostly drawn to setter, serializer and flag idioms. |
| [Semantic signal trial (#11)](https://github.com/gigaverse-app/dry-lint/pull/11) | Resolved API identities, bound arguments and field flow, added to the same bag: the combined variant gains one fresh AI positive and loses two old backend positives (SWR cache, clip eligibility). On the fresh scan sample, positives rise from 9 to 11 of 13 and negatives from 15 to 24 of 27. |

Three lessons follow:

1. **Additive tokens shuffle the ranking.** A true pair often keeps a high score but loses its slot to a different
   neighbour. A new signal has to earn a slot of its own, not compete inside the existing cosine.
2. **The label set is too small to separate variants.** Each trial moves 1 to 3 of 40 positives. Before trusting
   small differences, the gold set needs to grow, in particular with pairs that only a new variant proposes.
3. **Ranking quality, not candidate volume, is the weakness.** Pattern families (one serializer, view or setter
   per resource) share vocabulary and occupy slots. Neither more tokens nor a stricter floor separates them from
   real duplicates.

## Exploratory probes

Unlabelled, on a local gigaverse-backend checkout (`dd2c6d2`, 4,001 functions, default settings). They measure
how much a change moves the output, not whether it improves it.

| Probe | Result |
| --- | --- |
| Hubness: how often a function appears in another function's top three | The 1% most frequent neighbours hold **16.5%** of all top-three slots. The largest hubs are `Serializer.create`, `View.post`, `View.get` and `__init__` methods. |
| Hub correction ([CSLS](https://arxiv.org/abs/1710.04087)): subtract each function's mean similarity to its ten nearest neighbours before ranking | Keeps 254 of 322 scan pairs, drops 68 and adds 22, in about the same time. Added pairs include a privileged-member policy and phone-number validation, both concepts previously judged duplicate, and some mock-versus-real-client pairs. |
| Singular/plural folding of `w:` and `fn:` words | 302 of 2,448 words also occur in the other number (`users`/`user`, `settings`/`setting`). Folding adds 33 scan pairs and drops 23. |
| Exact fragment windows: three consecutive statements with local names canonicalized, at least 25 AST nodes | 21 cross-file pairs, 4 of them outside TF-IDF's top three. Copy-paste is not what the detector misses. |
| `ruff analyze graph` | Import graph of 1,504 modules and 4,617 edges in 0.6 s. |

## Other detectors

| Detector | Representation | Finds | Adopt? |
| --- | --- | --- | --- |
| pylint `duplicate-code` (R0801, `symilar`) | Hashes of N consecutive lines after stripping comments, docstrings and optionally imports and signatures; every pair of files | Copies, Type 1 | No. The fragment probe finds almost nothing TF-IDF misses. |
| [Arid](https://pypi.org/project/arid/0.1.0a1/) | Rust reimplementation of R0801 | Same | No, for the same reason. Pre-release. |
| ruff | No cross-function duplicate rule found. Rules such as identical `if` branches compare expressions structurally inside one function. | Local repetition | Its import resolution and graph, not a detector. |
| [Dryer](dryer-comparison.md) | Normalized syntax subtree fingerprints, Jaccard | Renamed shapes | Already an optional comparer; candidate channel. |
| SourcererCC | Token bag, overlap similarity, prefix filtering by global token rarity | Near-miss clones at very large scale | Its filtering idea, only if speed becomes a problem. Today it is not. |
| Siamese | Several representations in separate indexes, results merged | Several clone types at once | Yes: the multi-channel design below. |
| Code embeddings | Dense vectors from a code model | Same concept with different words | As a channel, if a small model is fast enough on CPU. Measured AUC 0.86. |

## Representations we can reuse

- **Import graph (`ruff analyze graph`).** It is fast and dependency-free beyond ruff. Possible uses: "A already
  imports B, and the new function in A re-implements one in B" is strong evidence of missed reuse and suggests the
  owner; import distance can be a ranking feature.
- **Receiver types.** `self._client.get` means something different on `GetStreamClient` than on a Django manager.
  Type checkers do not yet export per-expression types: ty documents none, and a third-party
  [`ty-types`](https://pypistats.com/packages/ty-types) package exists but is unproven. Most of the value is
  reachable from the syntax tree alone: parameter annotations, `self.x = ...` in `__init__`, and class attribute
  annotations. Annotations then *resolve* calls rather than contributing words, which earlier removal showed are
  noise.
- **Git history.** Files that change together, and identifier renames, are repository-specific statistics that
  cost nothing to read.

## Words

- **Singular/plural: worth a trial.** It normalizes morphology, not meaning, so it is not the synonym trap.
- **Global synonym lists: no.** Six groups had no effect, and verbs like load and fetch are not interchangeable.
- **Learned connections: as a separate channel.** Latent semantic indexing (a truncated SVD of the existing
  TF-IDF matrix) learns which tokens co-occur in this repository, with no model or training data. Small static
  word embeddings are an alternative.
- **Docstrings and comments: untried.** The fingerprint ignores them entirely. Agent-written code often states its
  purpose in a docstring.

## Hypotheses

| | Hypothesis | Evidence that would refute it | Outcome |
| --- | --- | --- | --- |
| H1 | Richer variants lose known positives by displacement: the true partner is still above the floor but no longer in the top three or the mutual first neighbour. | Lost positives mostly fall below the floor. | Partly supported: `scan` losses were displacements, `check` losses dilution below the floor |
| H2 | A complementary channel with one reserved slot retrieves positives the baseline misses without losing any it keeps. | Its novel pairs are judged positive less often than baseline scan pairs. | Refuted as stated: novel pairs 15% positive against 38% |
| H3 | Hub correction lowers the negatives `scan` retains without losing known positives, because pattern families are dense neighbourhoods. | Known positives drop out, or negatives do not fall. | Refuted: helps AI, displaces a known duplicate on backend |
| H4 | Folding singular and plural words is close to neutral on known pairs and finds a few new ones. | A known positive drops out, or more than two extra known negatives are retained. | Refuted: displaces a known duplicate in each repository |
| H5 | Import relationships predict which side should own a consolidation. | Owner labels in the gold set disagree with import direction. | Untested |
| H6 | A larger, judge-labelled gold set (Jev and Gemini, people only on disagreements) ranks variants the same way as the hand labels. | Rankings disagree on the overlapping pairs. | Untested |

## Experiment queue

| | Experiment | Tests | Cost |
| --- | --- | --- | --- |
| E1 | Reserved-slot channels: TF-IDF keeps three slots; a behaviour-only TF-IDF channel (calls, attributes, keys, control flow; no words), an LSI channel and Dryer each add one | H1, H2 | Offline script, numpy for LSI |
| E2 | Hub correction (CSLS) of TF-IDF scores before the neighbour budget and mutual-nearest scan | H3 | A few lines |
| E3 | Singular/plural folding of `w:` and `fn:` words | H4 | A few lines |
| E4 | Judge-labelled gold set of several hundred pairs drawn from every channel | H6 | Judge calls |
| E5 | Import graph: owner suggestion and an "already imports" feature | H5 | `ruff analyze graph` |
| E6 | API identity (#11) plus syntax-level receiver types, as a separate channel | H2 | Offline script |
| E7 | Docstring channel | H2 | Offline script |
| E8 | Pattern-family detection: report a dense family once instead of as many pairs | H3 | Offline script |
| E9 | A softer backlog rule: pairs in each other's top two, not only mutual first neighbours | H1 | Offline script |

E1 to E3 ran first, together, as [the channel trial](channel-trial.md). E4 is next: it decides whether a cheap
channel such as behaviour-only TF-IDF pays for its extra judge calls. Dryer and LSI are dropped as channels.

### Protocol for E1 to E3

Fixed before any result:

- **Corpora.** The pinned trial snapshots: gigaverse-backend `22dfbe1` (5,057 functions) and gigaverse-ai
  `78467d3` (9,907). Native TF-IDF on current main must reproduce the #11 baseline scans exactly (412 and 839
  pairs, same scores) before anything is compared.
- **Labels.** The 110 old backend pairs remain a regression set. The 40 #11 pairs are the fresh set; they were
  labelled before these variants existed. In addition, sample pairs that only the new variants propose, plus a
  baseline sample for comparison. Two independent assistant labellers judge each new pair blind to variant,
  source and score; a third breaks disagreements. Freeze labels before scoring them.
- **Budget.** `check` gives TF-IDF its usual three neighbours and each extra channel one; `scan` takes the union of
  each channel's mutual-nearest pairs. Count the extra candidates, since judge calls are the real cost.
- **Floors.** Calibrated without labels. Each one-slot channel except Dryer gets the single floor at which the same
  share of functions has a neighbour as with native TF-IDF. Dryer keeps its defaults. (Amended before any trial
  corpus was run: the first draft kept TF-IDF's floors for the behaviour-only channel, but a smoke run on
  dry-lint's own code showed its shorter vectors give 28% of functions a neighbour, against 17% for the baseline.)
- **Fixed parameters.** LSI rank 128, two power iterations, seed 0, `max_df` 0.3. CSLS uses the ten nearest
  functions in other files. Plural folding changes regular plurals only (`-ies`, `-sses`, `-xes`, `-ches`,
  `-shes`, `-zes`, `-s`, but not `-ss`, `-us`, `-is` or `-ous`).
- **Sample.** Per repository, 8 baseline scan pairs and 4 scan pairs found only by each of the plural, CSLS,
  behaviour, LSI and Dryer channels, excluding labelled pairs, drawn with `random.Random(20261106)`.

### Decision rules

A variant can become a production proposal only if all of these hold:

1. All 27 regression positives stay retained in both `check` and `scan`.
2. Fresh positives retained do not fall in either repository.
3. Among newly judged pairs, the variant's novel pairs are judged positive at least as often as the baseline scan
   sample.
4. The extra candidates per changed function are reported, and the added time is under a second per `check` on
   either repository.

Otherwise it stays an offline experiment and this page records why.

## What not to do

- Add more token families to the single TF-IDF cosine.
- Ship a global synonym dictionary or a general English stopword list.
- Port pylint's line-window matching.
- Tune weights against the 110 regression pairs and then call them a holdout.

## Sources

- [pylint `duplicate-code`](https://pylint.readthedocs.io/en/latest/messages/refactor/duplicate-code.html) and
  [`symilar`](https://manpages.org/symilar)
- [Arid](https://pypi.org/project/arid/0.1.0a1/)
- [ty CLI reference](https://docs.astral.sh/ty/reference/cli/) and [`ty-types`](https://pypistats.com/packages/ty-types)
- [CSLS, Conneau et al. 2017](https://arxiv.org/abs/1710.04087)
