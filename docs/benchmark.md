# Benchmark

Measured in November 2026 on gigaverse-ai: a Python monorepo of 7,000–10,000 functions (depending on what is excluded), much of it written with
coding agents. The gold labels contain that private code and are not published. The method is described here so
it can be repeated on another codebase.

## Population

The population is the 120 most recent merged pull requests. For each, the detector ran at its merge commit against
the functions the PR changed, which produced **295 candidate pairs**. Jev `reuse-v2` scored each pair.

Changed functions per commit: median 1, p90 13. Per PR that is 2.46 Jev calls on average before caching, so a
judge is cheap at PR scale.

## Gold set

The 295 pairs were split by Jev score into six bands: <0.1, 0.1–0.3, 0.3–0.5, 0.5–0.7, 0.7–0.9 and 0.9+. Sampling
was stratified across the bands, giving **96 pairs**. Two labellers labelled them blind, without the scores, using
[the guideline below](#labelling-guideline), and disagreements were reconciled. Precision and recall are projected
to the whole population with stratum weights (each band's size over its sample size).

## Results, prompt `reuse-v2`

| | |
| --- | --- |
| AUC | 0.97 |
| `report_at = 0.8` | 75% precision, 59% recall |
| `drop_below = 0.6` | 100% recall: no true duplicate scored under 0.6 |
| `fail_at = 0.8` (the default) | the same pairs as `report_at`: 75% precision, 59% recall |
| `fail_at = 0.91`, if raised | 100% precision, 21% recall; about 6 of the 295 candidates, roughly 1 PR in 20. The highest false positive scored 0.892 and the lowest true positive above it 0.910, so 0.90 and 0.91 flag the same pairs; 0.91 keeps twice the margin |
| Comments per PR at 0.8 | about 0.18 |
| Pairs between 0.6 and 0.8 per PR | about 0.3 |

The pairs between 0.6 and 0.8 are where a stronger second judge would earn its cost.

## Known duplicates (seeds)

Thirteen duplicates were found by hand in the codebase before the spike. Eleven scored ≥ 0.81, and a threshold of
about 0.55 would catch twelve.

## Ablations

| Variant | Result |
| --- | --- |
| Adding caller counts and the family of other look-alikes to Jev's state | did not help; owner agreement with the labellers fell from 14 of 17 to 12 of 17; dropped |
| Fixed 0.5 detector floor | missed tiny helpers; the 0.3 floor for functions under six lines found them |

## Detector: TF-IDF and embeddings

| | TF-IDF fingerprint | jina code (161M) | Qodo-Embed (1.5B) |
| --- | --- | --- | --- |
| Model size | none | 311 MB | 5.8 GB |
| Index the whole repository (7,195 functions) | 4.4 s on CPU | 11 s on an RTX 3090; about 80 min on CPU | 79 s on an RTX 3090 |
| Known pairs ranked first (of 13) | 12 | 10 | 10 |
| AUC separating real duplicates from false alarms in a judged sample | 0.66 | 0.86 | 0.85 |

The judged sample's negatives were TF-IDF's mistakes, which favours the embeddings on AUC. The two kinds of
detector agree on about 40% of their top pairs.

## Running it

`dry-lint bench` runs a judge, or the comparer, on a gold set: JSON lines, one labelled pair per line.

```json
{"new": {"id": "src/widgets/caption.py::preview_caption_text", "code": "def preview_caption_text(...): ..."},
 "existing": {"id": "src/text.py::shorten_text", "code": "def shorten_text(...): ..."},
 "label": "duplicate", "drifted": true, "owner": "existing", "weight": 4.5}
```

- `label` is `duplicate`, `separate` or `borderline`; borderline pairs are left out of the numbers.
- Each side carries its code as it was when labelled, so the judge benchmark still runs after the code has moved.
- `weight` projects a stratified sample back to its population: the stratum's size over its sample size.

```bash
dry-lint bench --gold gold.jsonl                       # the configured judge: AUC, precision and recall, bands
dry-lint bench --gold gold.jsonl --judge command --judge-command "claude -p"
dry-lint bench --gold gold.jsonl --comparer            # is each duplicate's partner proposed, on today's code?
```

## Labelling guideline

Use this to build a gold set for your own codebase:

> The test: does reconciling the two reveal ONE real concept with legitimate variations (it should have one
> implementation, parameterized where they differ), or TWO different concepts that happen to share structure or APIs?
>
> - **CONSOLIDATE**: one concept. Includes identical copies, renamed copies, independent re-implementations of the
>   same concept, and variants whose differences should be parameters, even when the details differ or have drifted.
> - **SEPARATE**: two different concepts that coincidentally look alike; or one calls the other; or the client and
>   server ends of one endpoint; or an interface or stub and its implementation.
> - **PATTERN**: deliberate instances of one template (one router, handler, command, fixture per resource) where a
>   shared helper would not clearly be simpler.
>
> For each item, also give:
> - `concept`, in at most six words;
> - `variation`: identical, parameterizable, drifted or n/a;
> - `owner`: new, existing or a new shared helper.

## Speed

Measured on gigaverse-ai with a warm checkout:

| Run | Time |
| --- | --- |
| `check` on the last 40 commits: 49 candidate pairs, all judged by Jev | 7.0 s |
| The same check again, every verdict from the store | 3.5 s |
| `scan`, the whole-repository backlog | 22 s |
| Parse, tokenize and index 9,976 functions | 3.2 s, 1.6 s, 0.2 s |

## Backend follow-up: more signals are not always better

The backend review uses commit `22dfbe180c6704101658a088cc269a25fa9c82dd`, default settings, and the detector
after PR #1 (`9fcc870`). Codex judged **110 of its 420 scan pairs**, inspecting both bodies and surrounding
ownership for ambiguous cases. There were 27 duplicate/drift pairs and 83 intentional-pattern/separate pairs.
The remaining 310 original pairs were not judged. Private code and per-pair judgments are not published here.

Selection and evaluation:

1. Select the first 30 pairs and 60 sampled without replacement from the remainder with Python
   `random.Random(20261103)`. Continue using that RNG to reserve 30 of the selected IDs as a holdout; use the
   other 60 for development. Label pairs before feature experiments.
2. Fit each variant's TF-IDF index over the same 5,057 implemented functions, not just the labeled pairs.
   Keep the existing floors and three-neighbour budget. Measure whether either direction retrieves each
   labeled pair, and separately whether the whole-repository mutual-nearest `scan` retains it.
3. After a follow-up question about identifier/class names, compare acronym splitting and enclosing-class
   context. Judge 20 previously unused pairs sampled with `random.Random(20261104)` as a confirmation set
   before evaluating those variants on it. Do not describe the previously consulted 30-pair holdout as fresh
   evidence for this second selection round.
4. Run the final production detector, including suppression rules, against the frozen corpus. Use
   `PYTHONHASHSEED=0`; round cosine scores to 12 decimal places for AUC ties so floating-point noise does not
   break mathematically equal scores. The counts are candidate retrieval, not judge precision.

### What the experiments rejected

These initial development ablations used the original word splitter. Higher duplicate retention and lower
negative retention are better. A retained pair is still available to a subsequent judge.

| Fingerprint variant | Duplicates retained by top-three retrieval (of 15) | Negatives retained (of 45) |
| --- | ---: | ---: |
| Original | 15 | 45 |
| Add field/key identities | 15 | 41 |
| Add all short string literals, including messages | 15 | 40 |
| Add full call-receiver expressions | 14 | 41 |
| Add operator kinds | 15 | 45 |
| Remove type-annotation noise | 15 | 42 |
| Add keys, strings, receivers and operators together | 14 | 33 |
| Add keys and remove annotation noise | 15 | 37 |

The all-signals variant lost a real rendition-admission duplicate. Full receiver expressions can overweight
incidental object/variable names. Arbitrary message strings and operators provided less useful separation than
field keys plus removal of annotation noise.

Enclosing-class words improved ranking, but the final `scan` check displaced two real duplicate pairs from the
confirmation set (privileged-role policy and image replacement). They were still in the top three, but no longer
mutual first neighbours. The shipped fingerprint therefore excludes enclosing-class context. Class names used
in executable code still contribute their words. Acronym splitting had a small ranking effect; its principal
benefit is consistent tokenization of names such as `parseHTTPHeader` and `parse_http_header`.

### Final production result

The final fingerprint adds field/key identities, excludes annotations, and splits acronym boundaries. It keeps
the existing thresholds. Both PR-style top-three retrieval and backlog scanning retain all 27 reviewed duplicates.

| Split | Duplicate pairs retained, before -> after (higher better) | Negative pairs retained by `check`, before -> after (lower better) | Negative pairs retained by `scan`, before -> after (lower better) | Ranking AUC, before -> after (higher better) |
| --- | --- | --- | --- | --- |
| Development (60 pairs) | 15 -> 15 | 45 -> 37 | 45 -> 31 | 0.717 -> 0.800 |
| Initial holdout (30 pairs) | 7 -> 7 | 23 -> 21 | 23 -> 17 | 0.770 -> 0.857 |
| Additional confirmation (20 pairs) | 5 -> 5 | 15 -> 14 | 15 -> 11 | 0.667 -> 0.653 |
| Total | 27 -> 27 | 83 -> 72 | 83 -> 59 | Not pooled |

The results were reproduced after merging the plugin pipeline. Exporting the same 110 labels to the native
`GoldPair` format and running `dry-lint bench --comparer` also retrieved all 27 positives in the top three in
the stored direction (zero missing functions). The detailed split table above additionally applies filtering
and the mutual-nearest scan policy.

The ranking AUC declined slightly in the additional confirmation set, even while all its duplicates remained
retrievable and four negatives left the scan. This supports a narrower claim about retrieval, not that every
ranking metric improved. The full, mostly unjudged backlog changed from 420 to 412 pairs; that count alone says
nothing about precision. New neighbours were not comprehensively judged.

These are a single assistant's judgments on one repository, with selection biased toward the old detector's
results and no independent second labeller. They are regression evidence, not calibrated judge probabilities,
repository-wide recall, or a reason to retune the global judge thresholds. Real findings included repeated
notification queries, role-label defaults, phone validation, OAuth refresh requests and batching; intentional
patterns included unrelated serializers, command options, factories, fake providers and adapters already calling
the same shared helper. No broad framework-name exclusions were introduced.
