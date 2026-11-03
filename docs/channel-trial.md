# Channel trial

**Keep the production detector unchanged. No variant met the [pre-registered decision rules](research-plan.md#decision-rules).**
Reserved-slot channels keep every known duplicate and find some real pairs TF-IDF misses. But the pairs only they
propose are judged real about 15% of the time, against 38% for the baseline scan. Hub correction and plural
folding each displace a known duplicate from `scan`. The scripts stay offline experiments.

This runs experiments E1 to E3 of the [research plan](research-plan.md). The feature definitions, sampling and
decision rules were committed (`45aa1f1`) before any trial corpus was run.

## What was tried

| Variant | Channels (neighbour slots) | What it tests |
| --- | --- | --- |
| baseline | production TF-IDF (3) | |
| plural | TF-IDF over tokens with `w:` and `fn:` words in their singular (3) | H4: plural folding |
| csls | TF-IDF re-ranked by [CSLS](https://arxiv.org/abs/1710.04087) over the ten nearest functions in other files (3) | H3: hub correction |
| plural-csls | both of the above (3) | |
| behaviour | TF-IDF (3) + TF-IDF over `call:`, `attr:`, `key:` and `ctl:` tokens only (1) | H2: what a function does, without its words |
| lsi | TF-IDF (3) + rank-128 latent semantic indexing of the TF-IDF matrix (1) | H2: co-occurrence learned from the repository |
| dryer | TF-IDF (3) + Dryer at its defaults (1) | H2: structure |
| channels | TF-IDF (3) + behaviour, LSI and Dryer (1 each) | H2 |
| combined | plural-csls (3) + behaviour, LSI and Dryer (1 each) | |

A variant's `check` retains a pair when any of its channels proposes it, in either direction, and no production
rule settles it. Its `scan` is the union of each channel's mutual-nearest pairs. The behaviour and LSI channels
each get one floor, calibrated without labels: the floor at which as many functions keep a neighbour as with
production TF-IDF (41% on backend, 39% on AI). CSLS keeps TF-IDF's floors and reported scores; it changes only the
order. Each channel has a `trial-*` identity and never opts into verdict reuse.

## Method

- Corpora: gigaverse-backend `22dfbe1` (5,057 functions) and gigaverse-ai `78467d3` (9,907 functions, of which two
  share a qualified name). Clean worktrees, Python 3.14.7, `PYTHONHASHSEED=0`, dry-lint main `fc87426` plus this
  trial.
- Parity: production TF-IDF on current main reproduced the semantic signal trial's baseline scans exactly (412 and
  839 pairs, same scores). The harness asserts its precomputed scan equals `Detector.scan` on every run.
- Known labels: the 110 judged backend pairs (27 positive / 83 negative) as a regression set, and the 40 pairs
  judged for [#11](https://github.com/gigaverse-app/dry-lint/pull/11) (backend 6 / 14, AI 7 / 13), which predate
  these variants.
- New labels: per repository, 8 baseline scan pairs and 4 scan pairs found only by each of the plural, CSLS,
  behaviour, LSI and Dryer channels, excluding labelled pairs, drawn with `random.Random(20261106)`: 56 pairs.
  Two assistant labellers judged each pair independently, with paths, code and read-only repository access, but no
  variant, source or score. They agreed on duplicate versus not for 55 of 56 pairs (exact label 53 of 56); a
  third independent labeller settled the remaining pair. Labels were frozen before they were scored. `duplicate`
  and `drifted` count as positive; `pattern` and `separate` as negative.

## Known pairs

Retained known pairs, `check` / `scan`. Higher is better for positives, lower for negatives.

| Variant | Backend regression positives (27) | Backend regression negatives (83) | Backend fresh positives (6) | Backend fresh negatives (14) | AI fresh positives (7) | AI fresh negatives (13) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 27 / 27 | 72 / 59 | 6 / 4 | 14 / 8 | 6 / 5 | 11 / 7 |
| plural | 27 / **26** | 74 / 60 | 6 / **3** | 14 / 7 | 6 / **4** | 11 / 7 |
| csls | 27 / **26** | 74 / 59 | 6 / 5 | 14 / 11 | 6 / 6 | 11 / 6 |
| plural-csls | 27 / **26** | 76 / 58 | 6 / 5 | 14 / 12 | 6 / 6 | 11 / 5 |
| behaviour | 27 / 27 | 74 / 61 | 6 / 4 | 14 / 9 | 7 / 7 | 11 / 8 |
| lsi | 27 / 27 | 73 / 63 | 6 / 5 | 14 / 9 | 6 / 5 | 11 / 7 |
| dryer | 27 / 27 | 73 / 61 | 6 / 4 | 14 / 8 | 6 / 5 | 11 / 7 |
| channels | 27 / 27 | 76 / 66 | 6 / 5 | 14 / 10 | 7 / 7 | 11 / 8 |
| combined | 27 / **26** | 76 / 63 | 6 / 5 | 14 / 12 | 7 / 7 | 11 / 6 |

- The reserved-slot variants cannot lose a pair the baseline keeps, by construction. They recover real pairs the
  baseline misses: custom-campaign community selection (AI, behaviour channel, in both `check` and `scan`),
  fleet-spawn orchestration (AI, behaviour and CSLS) and past-event deep-link drift (backend, LSI).
- Plural folding and CSLS both push the privileged-role policy duplicate out of the backend `scan`. Earlier trials
  displaced the same pair with enclosing-class words, keyword shapes and attribute roles. Plural folding also
  displaces durable effect-attempt admission (backend) and active-showcase expiry (AI).
- Hub correction depends on the repository. On AI it adds a positive and drops a negative from `scan`. On backend
  it admits more serializer `create` pairs: when one hub stops being everyone's first neighbour, members of its
  family become each other's.

## New labels: are the extra pairs real?

Positives among the newly labelled pairs that each variant's `scan` adds to the baseline, against the baseline's
own scan sample. A pair can count for several variants.

| Variant | Backend | AI | Both |
| --- | ---: | ---: | ---: |
| baseline scan sample | 2 / 8 | 4 / 8 | **6 / 16 (38%)** |
| plural | 1 / 4 | 2 / 5 | 3 / 9 (33%) |
| csls | 1 / 5 | 1 / 5 | 2 / 10 (20%) |
| plural-csls | 2 / 7 | 2 / 7 | 4 / 14 (29%) |
| behaviour | 1 / 7 | 1 / 6 | 2 / 13 (15%) |
| lsi | 1 / 5 | 1 / 8 | 2 / 13 (15%) |
| dryer | 0 / 4 | 0 / 4 | 0 / 8 (0%) |
| channels | 2 / 13 | 2 / 16 | 4 / 29 (14%) |
| combined | 4 / 19 | 2 / 20 | 6 / 39 (15%) |

Real pairs that only a trial channel proposed: rooms and streams each joining a room and minting a token, with
drifted checks (LSI); two implementations of the required community feed visibility (behaviour); a windowed cache
counter with a limit in two phone-auth guards (plural); poll-event construction and guarded promotion detection,
each implemented twice (plural); fetching a community event by a prefixed identifier (CSLS). Dryer's extra pairs
were model setters, onboarding hooks and unrelated small helpers, as in [the Dryer comparison](dryer-comparison.md).

Each rate rests on 8 to 39 labels; the differences between trial channels are not meaningful. The gap between
the trial channels together (14 to 15%) and the baseline sample (38%) is the consistent result in both repositories.

## Cost

Scan pairs, extra candidates per function over the baseline's 0.90 (backend) and 0.83 (AI), and each channel's
index time and mean query time. Timings come from one developer machine running both repositories at once.

| Variant | Scan pairs, backend / AI | Extra candidates per function, backend / AI |
| --- | ---: | ---: |
| baseline | 412 / 839 | 0 / 0 |
| plural | 427 / 869 | 0.04 / 0.04 |
| csls | 452 / 892 | 0 / 0 |
| plural-csls | 470 / 918 | 0.04 / 0.04 |
| behaviour | 702 / 1,306 | 0.24 / 0.21 |
| lsi | 686 / 1,313 | 0.20 / 0.20 |
| dryer | 431 / 893 | 0.01 / 0.02 |
| channels | 974 / 1,806 | 0.45 / 0.42 |
| combined | 1,002 / 1,862 | 0.48 / 0.45 |

| Channel | Index, backend / AI (s) | Query, backend / AI (ms) |
| --- | ---: | ---: |
| production TF-IDF | 0.10 / 1.07 | 1.9 / 2.7 |
| plural | 0.39 / 0.39 | 2.0 / 5.7 |
| csls | 0.11 / 0.77 | 3.1 / 4.6 |
| behaviour | 0.14 / 0.17 | 0.5 / 0.8 |
| lsi | 26.9 / 22.5 | 6.5 / 9.3 |
| dryer | 1.7 / 4.6 | 4.1 / 10.0 |

LSI's index time comes from building the sparse products with `numpy.add.at`; a sparse-matrix library would cut
it substantially, but its precision gives no reason to.

## Decision

| Variant | 1. Keeps 27/27 regression positives | 2. Fresh positives do not fall | 3. Novel pairs as real as baseline's | 4. Under a second added per `check` |
| --- | --- | --- | --- | --- |
| plural | no | no | no (AI) | yes |
| csls | no | yes | no | yes |
| plural-csls | no | yes | no | yes |
| behaviour | yes | yes | no | yes |
| lsi | yes | yes | no | no |
| dryer | yes | yes | no | no |
| channels | yes | yes | no | no |
| combined | no | yes | no | no |

No variant becomes a production proposal. Against the hypotheses:

- **H1, partly supported.** In the semantic signal trial's own data, two known positives lost only from `scan`
  were displaced (in five variant runs): still above the floor, at rank 2 or 3. Two positives lost from `check`
  as well were diluted instead: the extra tokens pushed their cosine under the 0.5 floor. Both mechanisms argue
  for separate channels over a bigger bag.
- **H2, refuted as stated.** Reserved slots keep every known pair and find real ones, but at about 15% precision
  against 38%: roughly one real pair per seven extra judge calls instead of one per two or three.
- **H3, refuted.** Hub correction helps AI and hurts backend, including a known duplicate.
- **H4, refuted.** Plural folding displaces a known duplicate in each repository.

## What this suggests

- **Judge the channels, do not just count them.** The judge already reaches AUC 0.97 on PR candidates. If it
  rejects channel-only negatives as reliably, the behaviour channel (0.15 s index, sub-millisecond query) could be
  an opt-in backlog source where judge calls are cheap. Measure that with the judge itself (E4) before proposing it.
- **The mutual-nearest rule is brittle.** The privileged-role duplicate has now been displaced by at least five
  unrelated changes. A softer backlog rule, such as mutual membership in each other's top two, deserves its own
  trial (E9).
- **Drop Dryer and LSI as channels.** Neither was more precise than the behaviour channel, and both cost seconds
  per run.

## Limits

The new labels come from assistant labellers of one model family, the older ones from a different assistant.
Neither is an independent human panel. Samples are small, and the novel strata were deliberately enriched with
trial-only pairs, so the rates above compare sources; they are not repository-wide precision or recall.
Labels, samples and per-pair results contain private code and remain local.

## Reproduce

From a dry-lint checkout with the Dryer extra, against each pinned target checkout:

```bash
PYTHONHASHSEED=0 uv run --extra dryer python scripts/benchmark_channel_trial.py \
  --root ../target-repository --out /private/channel-trial --gold /private/regression.jsonl --gold /private/fresh.jsonl
```

The run writes each channel's scan, `sample.json` for blind labelling and `results.json` with the corpus revision,
per-channel timings and floors, per-variant scan keys, candidate counts and gold retention. Validate the scripts
with:

```bash
uv run pytest tests/test_channel_trial.py --cov=scripts
uv run coverage report --include='*/channel_trial.py,*/benchmark_channel_trial.py' --fail-under=100
```
