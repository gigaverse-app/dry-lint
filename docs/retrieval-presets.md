# Retrieval presets

**Keep today's retrieval as the only setting: three neighbours above the 0.5 / 0.3 TF-IDF floors.** Measured on
600 recent commits across four repositories, wider retrieval finds a few more real duplicates (about 15% more
reported) for 2.6 times the judge calls. Its precision holds only because the second judge rejects what it adds; with
Jev alone, false reports almost quadruple. Narrower retrieval saves calls but never raises precision. Precision is the
judge's job, so presets stay judging presets.

This answers [research plan](research-plan.md) experiment E4, on real pull request traffic instead of a backlog scan,
and is the first measurement of dry-lint on the two TypeScript repositories.

## Question

`check` gives each changed function up to three neighbours above the floor. Would a conservative preset (fewer) or an
aggressive one (more) serve people better, once the judge has decided which candidates to report?

| Option | What `check` would propose for a changed function |
| --- | --- |
| baseline | production: the three nearest functions in other files above the TF-IDF floor (0.5; 0.3 under six lines) |
| rank 1 / rank 2 | production's nearest one or two only |
| k5 | neighbours four and five, above the same floor |
| floor | the three nearest above a lower floor (0.4; 0.2 under six lines) |
| behaviour | one slot from TF-IDF over calls, attributes, keys and control flow only, with a label-free floor ([channel trial](channel-trial.md)) |
| aggressive | baseline plus all three additions |

## Method

- **Replay.** The last 150 first-parent commits of each repository's main branch, each checked against its parent as
  `check` would run on that pull request, with the repository's own settings and production rules (patterns, inline
  suppressions, "one calls the other").

  | Repository | Language | Head | Commits from | With analysed changes | Changed functions | Distinct pairs, baseline / aggressive |
  | --- | --- | --- | --- | ---: | ---: | ---: |
  | gigaverse-backend | Python | `b620faf` | 2026-10-19 | 77 | 1,910 | 832 / 2,054 |
  | gigaverse-ai | Python | `5307dcd` | 2026-10-23 | 95 | 1,446 | 412 / 1,190 |
  | gigaverse-web-app | TypeScript | `cf19bff` | 2026-10-16 | 101 | 1,244 | 660 / 1,540 |
  | gigaverse-mobile | TypeScript | `4b392bc` | 2026-10-24 | 85 | 839 | 265 / 793 |

  Neither TypeScript repository has a dry-lint configuration, so the replay used the exclusions in
  [TypeScript and Bun](typescript.md#configuration) plus their end-to-end apps, mock harnesses and test support.
- **Sample.** Per repository, 40 baseline pairs and 20 pairs that only each wider option adds, drawn with
  `random.Random(20261107)`, excluding pairs labelled in earlier trials. Each pair is weighted by its stratum's size
  over its sample size, so estimates describe every distinct pair proposed in those 150 commits.
- **Labels.** Claude Opus 5.5, GPT-5.5 and Gemini 3.1 Pro labelled every pair blind (no option, score or source), with
  [the benchmark guideline](benchmark.md#labelling-guideline) verbatim; the label is the majority. They were unanimous
  on 366 of 400. The 10 pairs shared with the gigaverse-ai gold set got the same label. About $9.80 through OpenRouter.
- **Judges.** Jev `reuse-v2` and Claude Sonnet 5.5 (the product's DRY prompt, through OpenRouter) judged every pair.
  Presets count a verdict as the report does: label not `separate` and score at or above the threshold. `jev` reports
  and fails at 0.8; `jev+sonnet` takes Sonnet's answer for Jev scores in [0.5, 0.91), reports from 0.6 and fails at 0.7.
- **Intervals.** 90%, from a stratified bootstrap of the labelled pairs (1,000 rounds). Judge calls are counted as
  distinct pairs, since the verdict store answers a repeated pair for free.

## Results

All four repositories, per 100 commits:

| Option | Judge calls | Real duplicates proposed | Reported by `jev+sonnet` (true / false) | Precision | Fails the check (true / false) | Reported by `jev` alone (true / false) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| rank 1 | 174 | 34 (21–49) | 18 / 0 | 100% | 16 / 0 | 15 / 3.9 |
| rank 2 | 292 | 51 (36–68) | 30 / 3 | 92% | 24 / 0 | 21 / 3.9 |
| **baseline** | **362** | **55 (38–72)** | **34 / 3** | **92% (79–100)** | **28 / 0** | **25 / 3.9** |
| + k5 | +90 | +2 (0–5) | +1 / +0.3 | | | +1 / +0.8 |
| + floor | +364 | +9 (0–18) | +4 / 0 | | | +4 / +7.6 |
| + behaviour | +153 | +4 (0–13) | 0 / 0 | | | 0 / +9.5 |
| **aggressive** | **930** | **66 (46–87)** | **39 / 3** | **93% (81–100)** | **32 / 0.2** | **30 / 14.1** |

What the wider options add together: 568 more calls per 100 commits for 11 (2–22) more real duplicates, of which
`jev+sonnet` reports 6 (0–14) with 0.3 false. Only 3 of the 240 added pairs that were labelled are both real and
reported: one under the lower floor in gigaverse-ai, and one each among neighbours four and five in the TypeScript
repositories. None of the 60 backend additions was a real duplicate.

Per repository, for the baseline, per 100 commits:

| Repository | Real duplicates proposed | Reported by `jev+sonnet` (true / false) | Share of candidates that are real |
| --- | ---: | ---: | ---: |
| gigaverse-backend | 55 (14–111) | 42 / 0 | 10% |
| gigaverse-ai | 21 (7–41) | 7 / 0 | 8% |
| gigaverse-web-app | 99 (55–143) | 55 / 11 | 22% |
| gigaverse-mobile | 44 (26–66) | 31 / 0 | 25% |

gigaverse-ai already blocks duplicates in CI, which may explain its low rate. The TypeScript repositories have two to
three times the real-duplicate share of the Python ones.

## What this means for presets

- **Default: unchanged.** Three neighbours at today's floors.
- **No conservative retrieval preset.** Keeping only the nearest one or two neighbours does not make reports more
  precise (92% either way at rank 2; rank 1's 100% rests on no false reports in a small sample). It only saves judge
  calls: rank 2 keeps about 90% of reported duplicates for 81% of the calls. Judge calls cost about $0.004 per pull
  request with `jev+sonnet`, so the saving is not worth a preset. Conservative behaviour belongs in thresholds,
  as gigaverse-ai already does with `fail_at = 0.91`.
- **No aggressive retrieval preset yet.** It would need a second judge (never Jev alone), and its gain rests on three
  real duplicates. If one is added later, it should be neighbours five with the 0.4 / 0.2 floors, tied to a
  second-judge preset, and measured with this replay on the repository that wants it. The behaviour slot does not
  belong: 153 extra calls per 100 commits and nothing reported.
- **The tool belongs in the product.** Repositories differ more than the options do (8% to 25% real candidates).
  `dry-lint bench --replay N` now replays a repository's own history with its settings and preset, showing what
  would have failed, warned and cost, and with `--label` what it would have caught and missed
  ([running it](benchmark.md#labelling-a-replay)).

## Judging presets on three more repositories

The same replay gives each repository a judge gold set like gigaverse-ai's: Jev scored all 1,757 production pairs,
and 425 were drawn by Jev band and labelled the same way. On them, the live `dry-lint bench` shows that the
`jev+sonnet` preset failing at 0.7 holds its precision (91% to 100%), that Jev alone is about 80% precise on
TypeScript against 94% on gigaverse-ai, and that recall is lower everywhere ([other repositories](benchmark.md#other-repositories)).

So when a team wants a more conservative or a more aggressive setup, these are the levers that work:

| Want | Change | Evidence |
| --- | --- | --- |
| Fewer false blocks | `fail_at` up (gigaverse-ai uses 0.91), or `jev+sonnet` instead of `jev` on TypeScript | Jev alone on TypeScript: about 80% precision at 0.8, 91–100% at 0.9 |
| More duplicates found | `jev+sonnet`, reporting from 0.6 | 70–79% recall at 0.6 against 45–56% for Jev at 0.8 |
| Fewer judge calls | nothing needed | `jev+sonnet` costs about $0.004 per pull request |

Wider retrieval is not on the list: it adds judge calls faster than it adds reported duplicates.

## Wording of the judge prompt for TypeScript

The DRY prompt begins "Two Python functions" for TypeScript pairs too. Sonnet judged the 200 TypeScript retrieval pairs
again with "Two TypeScript functions": 2 of 200 decisions changed, within Sonnet's run-to-run variation (7 of 250 on
gigaverse-ai), with the same labelled duplicates reported. Correcting the word is cosmetic; it needs no new thresholds.

## Limits

- Labels are three models' majority, not people's. They agree with the earlier gigaverse-ai labels on all 10 shared
  pairs, but share any blind spot the three vendors have in common.
- Real duplicates among the added pairs are rare, so their estimates rest on 5 labelled duplicates; the intervals are
  wide and include no gain at all.
- Sonnet ran through OpenRouter in the retrieval comparison and through the Anthropic API in `dry-lint bench`; both use
  the product's prompt and model, and its answers vary a little between runs.
- 150 commits per repository is about two to three weeks of history; the TypeScript repositories have no dry-lint
  configuration of their own, so their real-duplicate rates may fall once patterns are declared.

Labels, samples, replays and verdicts contain private code and stay out of this repository.

## Reproduce

```bash
uv run python scripts/replay_presets.py replay --root /path/to/worktree --commits 150 --out /private/repo
uv run python scripts/replay_presets.py sample --out /private/repo --gold /private/earlier-labels.jsonl
OPENROUTER_API_KEY=... uv run python scripts/replay_presets.py label --out /private/repo --budget 10
OPENROUTER_API_KEY=... TYPESAFE_AI_API_KEY=... uv run python scripts/replay_presets.py judge --out /private/repo
uv run python scripts/replay_presets.py report /private/backend /private/ai /private/web /private/mobile
```

The judge gold sets come from the same replay:

```bash
TYPESAFE_AI_API_KEY=... uv run python scripts/replay_presets.py score --out /private/repo
uv run python scripts/replay_presets.py calibrate --out /private/repo --into /private/repo-calibration
OPENROUTER_API_KEY=... uv run python scripts/replay_presets.py label --out /private/repo-calibration --budget 10
uv run python scripts/replay_presets.py export --out /private/repo-calibration --gold /private/repo-gold.jsonl
uv run dry-lint bench --gold /private/repo-gold.jsonl --preset jev+sonnet
```

`replay` checks out each commit, so give it a dedicated worktree with no tracked changes. Validate the script with:

```bash
uv run pytest tests/test_replay_presets.py --cov=scripts
uv run coverage report --include='*/replay_presets.py' --fail-under=100
```
