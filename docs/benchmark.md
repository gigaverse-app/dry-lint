# Benchmark

The opt-in [model duplication probe](model-duplication.md#fresh-production-plugin-evaluation) measures
Pydantic/dataclass and TypeScript/Zod retrieval separately from function similarity. The follow-up preserves
903 baseline pairs and adds bounded TF-IDF/wider-Dice exploration across 4,164 declarations. Two independent
source reviewers adjudicated 54 fresh stratified candidates: 11 useful, 42 separate, one borderline. Live
`jev-models` declaration triage places 6 useful pairs in the first 8 slots versus 1 for Dice; same-file context
places 4. It retains every score for coding-agent review and carries adopter ownership policies. These sample
yields and ranking results do not inherit the function benchmark's population precision/recall claims.

The maintained text prompt is now `dry-operations-v3`; the former concept and compact names are compatibility
aliases. The historical second-judge results below used `dry-v1` and do not calibrate the new prompt.
The Jev `reuse-v2` and contextual `reuse-context-v3` profiles remain explicit compatibility choices.

The production `balanced` agent-hook profile has separate [58-commit validation](production-discovery-results.md):
cumulative budgets, preserved baseline coverage, same-file exploration and reviewed feedback. Its small known-positive
panel does not inherit the corpus precision/recall estimates below. `auto` now selects balanced with Anthropic
credentials; see [judging defaults](judges.md) for credential fallback and the separate model-review lane.

The shared-operation judge and protected historical scheduler have separate
[paired development and fresh-PR measurements](protected-exploration.md). Those historical results do not
calibrate the updated prompt now used by balanced.

## Current default regression panel

One live Claude Haiku 5.5 run with `dry-operations-v3`, a 2,048-token response limit and the balanced 0.5 threshold
produced these results. These are small curated, agent-labelled regression panels, not population estimates.

| Panel | Useful duplication detected (higher is better) | False positives (lower is better) |
| --- | --- | --- |
| [Oz's actual fixtures](../examples/oz-fixtures-gold.toml) | 6/6 | 0/6 |
| [pytest-obligation](../examples/pytest-obligation-gold.toml), excluding borderline cases | 5/6 | 1/6 |
| [Due](../examples/due-consolidation-gold.toml) | 5/7 | 0/3 |

Oz's shared-helper adapters produced 6/6 false positives in the recorded Jev/agent incident. The new panel
also retains their original independent setup/yield/teardown implementations as positive controls. The initial
shared-operation v2 replay caught 5/6 of those controls; v3 explicitly distinguishes owning a resource lifecycle
from entering an existing owner. Broader misses above remain limitations; these results do not establish the
precision or recall of the new default across repositories.

The opt-in cross-repository TypeScript judge has a separate [context calibration probe](context-probe.md).
Its small diagnostic sample does not inherit the Python precision/recall claims below.

Measured in November 2026 on gigaverse-ai: a Python monorepo of 7,000–10,000 functions (depending on what is excluded),
much of it written with coding agents. The gold labels contain that private code and are not published, apart from
[30 example pairs](#example-pairs). The method is described here so it can be repeated on another codebase.

## Public cleanup regression panel

The [pytest-obligation cleanup](case-studies/pytest-obligation-cleanup.md) adds
[15 pinned public pairs](../examples/pytest-obligation-gold.toml): six repeated
operations, six separate/delegated pairs, and three context-dependent borderline
cases. Four families include the original duplication and its repaired form.
These are agent-adjudicated regression examples, not additional observations in
the population estimates below. The panel includes misses and false positives;
it changes no prompt or threshold.

## Gold set

The [budgeted recall follow-up](budgeted-recall.md) compares the cleanup panels with
broader frozen labels, rejects prompt changes that regress precision, and measures
a small scheduling improvement under the unchanged estimated PR allowance.

The separate [pytest-selective cleanup panel](case-studies/pytest-selective.md#regression-goldens) contains
source-reviewed before/after regression pairs. Its implementation-agent labels and case-study outcomes are
diagnostic evidence, not an addition to the population-calibrated figures below.

**Population.** dry-lint's own detector ran on the functions changed by the 600 most recent merged gigaverse-ai
pull requests (10 September to 3 November 2026), against main, and proposed **2,012 candidate pairs** (per PR:
median 0, p90 10). Jev `reuse-v2` scored every pair; the scores are used only to stratify the sample.

**Sample.** 250 pairs, stratified by Jev score and weighted toward where decisions happen: 15, 15 and 20 pairs from
below 0.1, 0.1–0.3 and 0.3–0.5; 30, 40, 40, 45 and 45 from 0.5–0.6, 0.6–0.7, 0.7–0.8, 0.8–0.9 and 0.9 up. Each
pair carries its stratum's weight (stratum size over sample size), so the numbers describe all 2,012 pairs.

**Labels.** Three labellers from three vendors (Claude Opus 5.5, GPT-5.5, Gemini 3.1 Pro) labelled every pair blind,
without scores, with [the guideline below](#labelling-guideline); the label is the majority. They were unanimous on
211 of 250, and agreed pairwise on 86% to 96%. All 16 pairs shared with the earlier gold set got the same label.
**117 duplicates.** Labels from one vendor's model would lean toward that vendor's judge; three vendors dilute that,
but the labels are still LLM opinions, not people's.

`dry-lint bench` reports every figure with a 90% interval from a stratified bootstrap, because a few heavily
weighted pairs can move a point estimate a long way.

## Results

Jev `reuse-v2` alone, by threshold (the default `report_at` and `fail_at` are both 0.8):

| Score at or above | Precision | Recall | Pairs flagged, of 2,012 | Pull requests failed, of 600 |
| --- | --- | --- | --- | --- |
| 0.6 | 70% (66–74) | 95% (89–99) | 714 | |
| 0.7 | 82% (78–86) | 85% (80–91) | 550 | |
| **0.8** | **94% (91–98)** | **73% (68–79)** | **410** | **92 (15%)** |
| 0.85 | 99% (97–100) | 61% (55–67) | 326 | 84 (14%) |
| 0.9 | 100% (100–100) | 45% (42–49) | 238 | 69 (12%) |
| 0.95 | 100% | 19% (14–25) | 100 | |

AUC 0.97. A failed pull request has a median of 2 flagged pairs. These are pull requests before any `patterns` or
`distinct-from` comments, which a repository adds as it meets its deliberate look-alikes.

## Escalation

`dry-lint bench`, live, Jev first and the second judge on first scores in `[0.6, 0.91)`, at 0.8:

| Judging | Precision | Recall |
| --- | --- | --- |
| Jev alone (2 runs) | 94–95% (91–98) | 71–73% (66–79) |
| **Jev, then Claude Sonnet 5.5** (2 runs) | **98% (96–100)** | **75–76% (69–83)** |

Sonnet 5.5 roughly halves false blocks, from about one in 18 to about one in 50; the recall gain is within the
intervals. About a quarter of candidates fall in the band, so it is about 0.8 Sonnet calls per pull request at
about 3 seconds each, 4 at a time. Sonnet is a Claude model and one of the three labellers was Claude Opus; the
other two vendors' labels keep that from deciding the gold labels on their own.

**Choosing the second judge.** Before the gold set grew, five models judged the same 38 band pairs three times each
(through OpenRouter, the same prompt). The sample was too small to rank precision and recall, but two things held:

| Second judge | Block decisions that changed between runs | Median seconds per pair |
| --- | --- | --- |
| Claude Sonnet 5.5 | 1 of 38 | 3 |
| Claude Opus 5.5 | 2 of 38 | 7 |
| Gemini 3.1 Pro (preview) | 4 of 38 | 12 |
| GPT-5.5 | 5 of 38 | 8 |
| Gemini 2.5 Pro | 12 of 38 | 17 |

Sonnet 5.5 was the most consistent and the fastest; Gemini 2.5 Pro was the least consistent and the least precise.

## Thresholds with a second judge

When a stronger judge re-judges the uncertain band, the threshold that fails a pull request can come down. Claude
Sonnet 5.5 judged all 250 gold pairs twice through the API (7 of 250 block decisions changed between the runs);
the table combines its answers with Jev's on Jev scores in the band, with 90% intervals:

| Judging | Fails at | Precision | Recall | Second-judge calls per pull request |
| --- | --- | --- | --- | --- |
| Jev alone | 0.8 | 94% (91–98) | 73% (68–79) | 0 |
| Jev, then Sonnet on [0.5, 0.91) | 0.6 | 94% (89–98) | 88% (82–94) | 1.1 |
| **Jev, then Sonnet on [0.5, 0.91)** (`jev+sonnet`) | **0.7** | **97% (94–99)** | **84% (77–91)** | **1.1** |
| Jev, then Sonnet on [0.5, 0.91) | 0.8 | 98% (96–100) | 77% (70–84) | 1.1 |
| Jev, then Sonnet on [0.3, 0.91) | 0.7 | 97% (94–99) | 84% (77–91) | 1.7 |
| Sonnet alone (`sonnet`) | 0.7 | 97% (94–99) | 84% (77–91) | 3.4 |
| Jev, then `codex` (ChatGPT subscription) on [0.5, 0.91) (`jev+codex`) | 0.7 | 96% (93–99) | 85% (79–91) | 1.1 |

Escalating below 0.5 found nothing more; failing at 0.7 rather than 0.8 trades a point of precision for seven of
recall. `codex` used the account's default model, its scores barely moved between 0.6 and 0.8, and it agreed with
Sonnet on 138 of the 158 band pairs. Live `dry-lint bench` runs of the shipped `jev+sonnet` preset gave 96–98%
precision and 85% recall at 0.7 (two runs).

**Cost, measured.** A Sonnet 5.5 call on a gigaverse-ai pair used 959 input tokens and about 126 output tokens
(thinking included; p90 150), 2.8 characters per token: about $0.0032 at $2 and $10 per million. With 3.35
candidate pairs per pull request and a third of them in the band, `jev+sonnet` costs about $0.004 per pull request
(Jev's share is about $0.0001), and the largest pull request in the sample (103 candidates) about $0.12. A Sonnet
call took a median of 2.1 s through the API; a `codex` call took 14 s.

## Within a budget

The question for a team: at most $0.04 of model use per pull request, every push included and subscription use
counted at list price, which judging finds the most duplicates without blocking separate code?

**Method.** Claude Opus 5.5 and Haiku 5.5 judged all 250 gold pairs twice through the API, as Sonnet had, with the
same prompt. Every gold pair belongs to one of the 600 pull requests, so each setup was simulated on each pull
request's real candidates, exactly as the ledger runs it: the first judge takes pairs by similarity, the second
takes first scores nearest the middle of its band, each until the pull request's budget is spent, with each pair's
real prompt length and each model's measured answer length (Sonnet 126 tokens, Opus 217, Haiku 444). To count the
pushes, every one of the 184 pull requests with candidates was replayed commit by commit: a pair is judged once
when it appears and again whenever its new function's logic changes, 1.27 times on average if every commit were
pushed alone. Figures average the two runs of each model.

**Every judge on every pair, no budget** (fails at the threshold shown):

| Judge | Fails at | Precision | Recall | Cost a pull request |
| --- | --- | --- | --- | --- |
| Jev | 0.8 | 94% (91–98) | 73% (68–79) | $0.0002 |
| Claude Haiku 5.5 | 0.7 | 92% (87–97) | 89% (82–95) | $0.0014 |
| Claude Sonnet 5.5 | 0.6 | 94% (89–98) | 92% (88–95) | $0.015 |
| Claude Opus 5.5 | 0.6 | 99% (98–100) | 87% (79–94) | $0.037 |

**Jev first, a second judge on [0.5, 0.91), within $0.04 a pull request**, the second judge's answers at the
threshold shown and Jev's unescalated answers at its own 0.8:

| Judging | Fails at | Precision | Recall | Average a pull request | Pull requests that reach the budget |
| --- | --- | --- | --- | --- | --- |
| Jev alone (`jev`) | 0.8 | 94% (91–98) | 73% (68–79) | $0.0002 | 0 of 600 |
| Jev, then Sonnet (`jev+sonnet`) | 0.7 | 97% (94–99) | 84% (77–90) | $0.0035 | 25 |
| Jev, then Sonnet | 0.6 | 94% (89–98) | 87% (81–93) | $0.0035 | 25 |
| **Jev, then Opus** (`jev+opus`) | **0.55** | **98% (96–100)** | **85% (79–92)** | **$0.0053** | **51** |
| Jev, then Opus | 0.7 | 99% (97–100) | 78% (71–85) | $0.0053 | 51 |
| Jev, then Sonnet, then Opus on Sonnet's [0.5, 0.85) | 0.55 | 96% (91–99) | 86% (79–92) | $0.0057 | 55 |
| Sonnet alone (`sonnet`) | 0.7 | 97% (93–99) | 63% (55–72) | $0.0068 | 62 |
| Opus alone | 0.55 | 99% | 40% | $0.0083 | 115 |

So `jev+opus` is the default when both keys are present. It blocks about one separate pair in 60 against one in
30 for `jev+sonnet`, at the same recall. A budget only binds on large pull requests (72% of candidate pairs come
from pull requests with 12 or more), so a judge that can fall back on Jev's answers keeps most of its recall:
Sonnet or Opus on every pair loses a third or more of it to unjudged pairs. Without the first-judge bar, a large
pull request that ran out of budget failed on Jev's scores from 0.55, and `jev+opus` fell to 82% precision. A
looser cap buys little: `jev+opus` gets 99% and 88% within $0.10 a pull request (average $0.009), and 99% and 90%
with no budget at all (average $0.013). A live `dry-lint bench --preset jev+opus` (Jev's API, then Opus through the
`anthropic` judge, no budget) gave 98% (97–100) precision, 90% (84–95) recall and AUC 0.98.

**Checks.** Opus 5.5 was one of the three labellers, which favours it. On the 219 pairs where the two non-Claude
labellers (GPT-5.5 and Gemini 3.1 Pro) agree, without the Opus label, `jev+opus` scores 99% precision and 86%
recall within the budget, `jev+sonnet` 99% and 84%, and Jev alone 96% and 74%: Opus still leads, but by less than
the intervals, so part of its lead on all labels is likely the shared vendor. Between its two runs, Opus changed 7
of 250 decisions at 0.55, and Sonnet 7 at 0.7. Haiku 5.5 often gives a high score with a `separate` label, so its
scores cannot pick a band; read by label, as reports do, it is a fair cheap judge (`jev` then Haiku on [0.5, 0.91)
fails at 0.8 with 97% precision and 78% recall for $0.0007 a pull request), but no Haiku combination beat
`jev+opus`. The claude-code presets use the same models and prompt through the CLI and were not measured through
it: the local CLI login had expired.

## Other repositories

The thresholds above were measured on gigaverse-ai. Three more gold sets test them elsewhere, built the same way
([retrieval presets](retrieval-presets.md#method)): every pair production retrieval proposed for the last 150
first-parent commits of main, scored by Jev, sampled by Jev band toward the decision band (10/10/10 below 0.5,
20/25/25/25/25 above), labelled blind by the same three vendors' models. `dry-lint bench` live, 90% intervals:

| Repository | Pairs (duplicates) | `jev` at 0.8: precision / recall | `jev+sonnet` reports from 0.6 | `jev+sonnet` fails at 0.7 |
| --- | --- | --- | --- | --- |
| gigaverse-ai (above) | 250 (117) | 94% (91–98) / 73% (68–79) | 94% / 88% | 97% / 84% |
| gigaverse-backend, Python | 142 (61) | 100% (100–100) / 45% (37–54) | 100% (100–100) / 70% (60–81) | 100% (100–100) / 62% (52–73) |
| gigaverse-web-app, TypeScript | 145 (52) | 81% (69–92) / 56% (45–67) | 80% (69–91) / 79% (69–89) | 100% (100–100) / 64% (52–76) |
| gigaverse-mobile, TypeScript | 138 (52) | 80% (69–91) / 56% (48–65) | 89% (82–96) / 78% (69–87) | 91% (83–98) / 72% (62–82) |

- **Failing at 0.7 with a second judge holds.** 91% to 100% precision on all three, as on gigaverse-ai.
- **Jev alone is less precise on TypeScript:** about 80% at 0.8, against 94% on gigaverse-ai. Its score bands put
  every TypeScript false positive below 0.9 except one; prefer `jev+sonnet` there, or raise `fail_at` to 0.9.
- **Recall is lower everywhere than on gigaverse-ai**, at 45% to 72% when failing. More real duplicates go unreported
  on repositories dry-lint does not yet gate.
- **Reports from 0.6 are noisier on web-app** (80%): Sonnet's 0.6–0.7 answers there are as often wrong as right. They
  warn without failing.

### `jev+opus` and the budget elsewhere

Live, with no budget, `jev+opus` failing at 0.55 scored 100% (100–100) precision and 64% (53–75) recall on
gigaverse-backend, 90% (81–100) and 75% (63–86) on web-app, and 96% (91–100) and 75% (65–85) on mobile.

The budget binds harder on these repositories than on gigaverse-ai. Opus and Sonnet answers to every gold pair in
Jev's band were saved, and each preset was simulated commit by commit over the replayed history: the 57, 77 and 59
first-parent commits of main that had candidate pairs, each standing for a squashed pull request, with 1.27 judge
calls per pair for re-pushes. Within $0.04 a pull request, Opus could not reach about half of the pairs in its
band. 13 to 15 of those commits reached the budget with `jev+opus`, and 5 to 7 with `jev+sonnet`:

| Within $0.04 a PR | `jev+opus` fails at 0.55 | `jev+sonnet` fails at 0.7 | Average per commit, Opus / Sonnet |
| --- | --- | --- | --- |
| gigaverse-ai (above) | 98% / 85% | 97% / 84% | $0.005 / $0.0035 a pull request |
| gigaverse-backend | 96% (89–100) / 60% (48–72) | 100% (100–100) / 60% (49–72) | $0.017 / $0.011 |
| gigaverse-web-app | 83% (73–92) / 75% (62–88) | 86% (76–94) / 70% (58–82) | $0.017 / $0.010 |
| gigaverse-mobile | 89% (81–96) / 77% (68–87) | 87% (78–95) / 74% (63–85) | $0.017 / $0.011 |

- **The two presets tie off gigaverse-ai.** Opus finds a few more duplicates and Sonnet blocks a little less, all
  within the intervals. Sonnet costs about two thirds as much, so it reaches more pairs before the budget runs out.
  `jev+opus` stays the default because it leads on the largest gold set, but on these repositories either is as good.
- **The budget costs TypeScript precision.** Without a budget, `jev+opus` scored 90% on web-app and 98% on mobile;
  within $0.04, 83% and 89%. The difference is pairs left on Jev's answer, held to 0.8, where Jev alone is about 80%
  precise on TypeScript. A larger budget barely helps (web-app gets 84% and 79% within $0.10), because Opus itself
  scores 90% there. Raising Jev's bar trades too much recall: at `first_at` 0.91, web-app gets 93% precision and
  46% recall. So a TypeScript repository should keep `warn-only` for now, as gigaverse-web-app does; on Python,
  either preset can block.
- One Opus run per pair: on gigaverse-ai, two runs differed on 7 of 250 decisions, which moves a 140-pair set's
  figures by a few points.

## Earlier gold set (superseded)

The first gold set had 96 pairs from the 120 most recent pull requests, with 23 duplicates. It put Jev at 75%
precision and 59% recall at 0.8, and suggested `fail_at` 0.91. With so few duplicates and heavy stratum weights,
one pair in a low band moved recall by 8 points: those figures were mostly noise, and the 250-pair set replaces
them. The lesson is built into `bench`: every figure now comes with its interval.

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
- A file ending in `.toml` holds the same fields as `[[pair]]` tables instead, with the code in `'''` blocks, as
  in [`examples/gold.toml`](../examples/gold.toml): easier to read and review than JSON lines.

```bash
dry-lint bench --gold gold.jsonl                       # the configured judge: AUC, precision and recall, bands
dry-lint bench --gold gold.jsonl --judge command --judge-command "claude -p"
dry-lint bench --gold gold.jsonl --comparer            # is each duplicate's partner proposed, on today's code?
```

Without a gold set, `dry-lint bench --replay N` shows what `check` would have done on each of the last N first-parent
commits of the default branch, with this checkout's settings and preset: which commits would have failed or only
warned, the findings, how many pairs were judged and the estimated cost. It replays oldest first in a temporary
worktree, so your checkout is never touched, and it goes through the verdict store like `check`: running it again with
another `--fail-at` or `report_at` judges nothing new, and later checks reuse its verdicts. Each commit gets the judging
budget a pull request's check would (`budget.usd`, or `--budget-usd`), so a replay spends what CI would have.

```bash
dry-lint bench --replay 50                             # the configured preset on the last 50 commits
dry-lint bench --replay 50 --fail-at 0.9               # the same verdicts, a stricter threshold: free
dry-lint bench --replay 50 --preset jev --ref origin/release --format json --report replay.json
```

On gigaverse-backend, the last 30 commits with `jev+sonnet` took about 70 seconds and $0.18: 19 findings, 5 commits
that would have failed. At `--fail-at 0.9` the same 19 findings fail 2 commits and warn on 3, with no new judge
calls. The store keeps one verdict per pair, the latest, so a pair met again at a later commit reuses it whenever
`check` would.

### Labelling a replay

`--label K` turns the replay into a gold set of your own and says what the judging made of it. About K distinct
pairs are sampled by the configured judge's score, most from the bands where presets decide (as for the gigaverse-ai
gold set), each weighted by its band's size over its sample size. A panel labels each pair blind, with the
[guideline below](#labelling-guideline) and the two functions only, no score or verdict; the strict majority is the
label, and a split is borderline. The default panel is the `labellers` setting, three vendors' models through
OpenRouter (`OPENROUTER_API_KEY`), so no single judge's family decides its own gold; `--labeller` replaces it, and
`--labeller "command:<cli>"` runs any command that reads the prompt and prints a JSON answer, including a script that
asks a person.

```bash
dry-lint bench --replay 150 --label 100                # about $3 through OpenRouter
dry-lint bench --gold .git/dry-lint/gold/replay.jsonl --preset jev    # any other preset, on the same labels
```

The report adds, per 100 commits with 90% intervals: real duplicates proposed, reported (real and not), blocking
(real and not), and real duplicates the judging did not report, plus precision and recall when reporting and when
blocking. They come from the replay's own verdicts, so labelling never re-judges. The gold set is written inside the
git directory by default (`--gold-out` to choose); every answer is kept beside it, so running again, or with a larger
`--label`, asks only about pairs nobody has answered. `--label-budget-usd` (default 5) caps a run's labelling.

On gigaverse-backend's last 30 commits, 60 labelled pairs ($1.71) gave about 80 real duplicates proposed per 100
commits, 63 reported with none wrongly, and 16 (0–49) not reported.

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

## Example pairs

[`examples/gold.toml`](../examples/gold.toml) holds 30 labelled pairs from the four gold sets: 15 duplicates and 15
separate, in Python and TypeScript. They were chosen by hand among short functions whose paths and code name no
vendor, customer or credential. Each pair carries its majority label, the three labellers' votes, and the scores
Jev, Opus and Sonnet gave it (a `separate` answer counts as 0, as in reports; Opus and Sonnet were only asked in
Jev's band). The file is TOML, so the code reads as written. `dry-lint bench --gold examples/gold.toml` runs on them, with no key at all using
`--judge command --judge-command "python examples/fake_judge.py"`.

They were picked for being hard: mostly from the decision band, where look-alikes and duplicates are hard to tell
apart, and including pairs the labellers split on. So they show how judging decides, but no figure measured on them
says anything about a real repository: Jev scores AUC 0.58 here, against 0.97 on the 250-pair set. Four of them:

- **A duplicate every judge finds** (gigaverse-ai): two stores read optional context from Redis with the same
  0.25-second timeout and the same comment; only the model they parse differs. Jev 0.71, Opus 0.72, Sonnet 0.80.
- **Look-alikes that already share the concept** (gigaverse-web-app): `transientRetryDelayMs` and `chatRecoveryDelayMs`
  both call the shared `backoffDelayMs` with their own policy. Nothing is left to consolidate: two labellers said
  separate and one pattern, and Opus and Sonnet answered separate, though Jev scored 0.72.
- **A template, not a duplicate** (gigaverse-mobile): context-selector hooks such as `useAudienceProfileContext` and
  `useChatMessageContext` repeat one shape per context. All three labellers said PATTERN. Jev scored 0.85, so these
  fail with Jev alone and pass once Opus re-judges them.
- **A split decision** (gigaverse-ai): `StatsQuery.retrieval_key` and `ShownKind.of` both normalize the teams of a
  query (casefold, sorted). GPT-5.5 and Gemini said consolidate and Opus separate, so the label is duplicate; as a
  judge, Opus answered separate again and Sonnet called it drifted at 0.6. Jev scored 0.78.

## Speed

Measured on gigaverse-ai with a warm checkout:

| Run | Time |
| --- | --- |
| `check` on the last 40 commits: 49 candidate pairs, all judged by Jev | 7.0 s |
| The same check again, every verdict from the store | 3.5 s |
| `scan`, the whole-repository backlog | 22 s |
| Parse, tokenize and index 9,976 functions | 3.2 s, 1.6 s, 0.2 s |

## Optional Dryer detector on gigaverse-backend

The [backend comparison](dryer-comparison.md) measures the native TF-IDF and optional Dryer plugins on the same
frozen Python corpus, with shared candidate policy, repeated timings and exploratory source review.

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

## Follow-up: synonyms, stopwords, size and call signatures

A second exploratory pass starts from `tfidf:2` at dry-lint commit `1344627`, using the same backend commit,
5,057 functions and 110 previously judged pairs above. **These labels have already informed feature selection;
none of their splits is a fresh holdout for this pass.** Each variant changes one signal, fits the full corpus,
uses the existing floors and three-neighbour budget, and applies the production filtering and scan rules.
`PYTHONHASHSEED=0` fixes ordering. No runtime defaults changed as a result.

Higher positive retention and lower negative retention are better. Counts are retained **known pairs**; newly
proposed neighbours were not judged, so a lower negative count does not establish higher overall precision.

| Variant | Positives in `check` / `scan` (of 27) | Negatives in `check` / `scan` (of 83) |
| --- | ---: | ---: |
| Current fingerprint | 27 / 27 | 72 / 59 |
| Add synonym hints | 27 / 27 | 73 / 59 |
| Replace word tokens with canonical synonyms | 27 / 27 | 72 / 59 |
| Remove nine additional English words | 27 / 27 | 72 / 58 |
| Remove framework word tokens | 27 / 26 | 70 / 57 |
| Lower `max_df` from 0.30 to 0.15 | 27 / 26 | 72 / 56 |
| Penalize different AST sizes | 25 / 24 | 61 / 42 |
| Add call-specific keyword names | 27 / 26 | 71 / 58 |
| Add call arity and keyword-set shape | 27 / 26 | 70 / 54 |
| Add attribute read/write roles | 27 / 26 | 73 / 57 |

The variants are deliberately simple probes, not claims that every possible implementation of a signal fails:

- **Synonyms:** use six groups: `fetch/load/retrieve/read`, `remove/delete`, `shorten/truncate/clip`,
  `validate/check`, `create/build/make`, and `send/emit/publish`. For each existing `w:` or `fn:` token in a
  group, either add `syn:<first-word>` alongside the original token, or replace its word with the first word
  while preserving the token family. Leave `call:`, `attr:` and `key:` identities intact. Neither variant
  improves known-pair retrieval here. These verbs are not universally interchangeable: a load may fetch, cache,
  validate or mutate; a publish may have different guarantees from a send. Do not add a global natural-language
  synonym dictionary on this evidence. If a repository needs domain aliases, test a small explicit mapping as
  an optional comparer, preserving original tokens and versioning its similarity semantics.
- **Stopwords:** the English probe drops `the/and/with/from/that/this/for/into/then` from `w:` and `fn:` tokens.
  The framework probe instead drops `create/update/save/object/objects/serializer/client/request/response/validated/default/context`
  from those two families. The latter and stricter `max_df` filtering both displace the image-replacement
  duplicate from the scan. The English probe removes just one known negative from scanning; that is too little
  repeatedly consulted evidence to change the default. Keep the existing code-specific stopwords and frequency
  filter. Avoid a general English list that might discard meaningful terms such as negation; tokenization and
  stopword lists must agree ([scikit-learn guidance](https://github.com/scikit-learn/scikit-learn/blob/main/doc/modules/feature_extraction.rst#using-stop-words)).
- **Size:** count executable AST nodes, excluding annotations, decorators and type parameters. Multiply cosine
  by `sqrt(min(size_a, size_b) / max(size_a, size_b))`, then rerank and apply the same floors. This loses the
  rendition-admission and clip-eligibility pairs from PR retrieval, plus a privileged-role policy from scanning.
  Drift can add guards or side effects to only one implementation, which is precisely a reason to inspect it.
  Keep the existing lower floor for tiny functions; do not introduce a hard size-ratio rejection or this penalty.
- **Keywords:** current `key:` tokens already preserve keyword names without making their order significant.
  The extra keyword probe adds `kw:<callee-leaf>:<keyword-name>` per named keyword. The shape probe instead adds
  `shape:<callee-leaf>:<positional-count>:<sorted-keywords>` per call, using `**` for an unpacked mapping. Both
  displace the privileged-role pair from scanning. Positional and keyword calls may be equivalent; resolving that
  requires a known callable signature. Do not infer argument names for unknown SDK methods or dynamic calls.
- **Attribute roles:** add `access:<AST-context>:<attribute-name>` for each attribute access, distinguishing
  `Load`, `Store` and `Del`. This also displaces the privileged-role pair from scanning and admits one extra
  known negative in PR checking. It does not justify another token family by itself.

The next useful experiments should target information these probes lack: statically resolved API identities
(import aliases should not change meaning), arguments bound to a known signature, and which domain field feeds
an output or mutation. Keep these as separate experimental comparers until they improve retrieval on **newly
judged pairs and a second repository**, with the same judge budget. Another option is reserving a candidate slot
for a complementary comparer rather than adding every token to one cosine score; test both extra recall and the
false-positive cost. More features can change which neighbour wins even when a true pair's score remains high.

The [research plan](research-plan.md) collects these results, hypotheses and the experiments queued next.

## Offline CPU discovery

The optional [offline CPU comparer](cpu-embedding.md) implements the pinned MiniLM channel through ordered
`discovery.comparers`, retaining ordinary baseline and explicit existing TF-IDF exploration before one unseen
CPU candidate. It is an optional cached channel, not a default cold CI workload.

A production-plugin check of 100 complete OpenHands source bodies (88 unique) measured **6.623 seconds cold** and
**0.440 seconds warm**, including runtime construction and artifact validation. Warm retrieval had 88 disk-cache
hits and zero encodings; fresh vectors matched the research cache exactly (maximum absolute difference 0).
Cold whole-corpus research encoding of 37,604 LiteLLM functions took 2,496 seconds on two CPU threads. This
cost motivates an explicitly configured local vector cache, not a change to the default comparer.

The original fixed laboratory default-plus-one route added four funded positive pairs and seven negative
exposures across source/background contexts, with no lost baseline positives. Its balanced diagnostic added one
of each. Those are development/regression observations and funding exposures, not deployed configuration or
emitted-report gains. The production profile also preserves the original 20-neighbour TF-IDF exploration route,
so its measured result is a separate comparison: across 207 source-supported function records and 16 backgrounds,
adding one CPU neighbour recovered no additional known positive pair and exposed three additional known negatives.
Earlier primary candidates were unchanged. Negative exposure is not a false report; the judge still decides.
Budgets and judge defaults remain unchanged. Public pretrained
weights may contain source contamination. Provider agreement alone does not establish accepted source labels.
