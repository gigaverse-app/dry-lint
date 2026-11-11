# Asking about five pairs in one request is cheaper and less precise

**Not adopted.** With `group = 5`, one request to the judge asks about a changed function and up to five of its
look-alikes and returns one verdict per pair. On 78 recent commits it cost 22% less than asking one pair at a time.
It also confirmed 2 fewer duplicates and added 6 reports that a stronger model rejected. Spending the saving on more
pairs bought 11 more confirmed duplicates and 19 more rejected reports. The budget is $0.04 a pull request, so the
saving is worth less than the extra false reports. The runtime asks one pair at a time and has no `group` option. The
code is kept here as a patch, with the numbers, so the work can be picked up.

## What it does

With `group = 5` on the `anthropic` judge, one request asks about a changed function and up to five of its
exploration look-alikes, and the answer has one verdict per pair. It is off by default and no preset sets it.

- Every pair keeps its own reservation, verdict and store record. The caps still count pairs.
- Baseline pairs, residual pairs and pairs with an adopter policy are always asked alone.
- A pair the answer leaves out is unfinished work, never a "no".
- The group size is part of the judge's version, so grouped answers are never reused by a judge that asks alone.

## Evidence

78 recent commits of four private repositories through the production scheduler, a fresh allowance each. Claude
Opus 5.5, asked one pair at a time, judged every report.

| Exploration | Pairs judged | Cost a commit | Reports | Opus confirms | Opus rejects |
| --- | ---: | ---: | ---: | ---: | ---: |
| One pair a request, 30 pairs a push (today) | 1,252 | $0.0065 | 133 | 108 | 25 |
| One pair a request, 48 pairs a push | 1,444 | $0.0074 | 144 | 116 | 28 |
| Five a request, 30 pairs a push | 1,266 | $0.0051 | 137 | 106 | 31 |
| Five a request, 48 pairs a push | 1,587 | $0.0060 | 163 | 119 | 44 |

More confirmed and fewer rejected are better; lower cost is better.

- **Cheaper, not better.** At the same 30 pairs, grouping costs 22% less, confirms 2 fewer duplicates and adds 6
  rejected reports.
- **Spending the saving on more pairs buys false reports.** At 48 pairs it costs 7% less than today, confirms 11
  more duplicates and adds 19 rejected reports.
- **The loss is in the grouped answers themselves.** Opus confirms 62% of grouped exploration reports against 73% of
  single ones. No score threshold separates the rejected ones.
- **The earlier 38% saving does not carry over.** That figure was per pair on labelled pairs in groups of five. On
  real commits baseline pairs are asked alone and many functions have one or two look-alikes.
- **It was reliable.** No grouped request failed and no pair was left without a verdict in 436 grouped requests.

The labelled pairs agree on direction. 750 labelled pairs, each asked together with four TF-IDF neighbours of its
changed function, judged by Claude Haiku 5.5 at low effort:

| | Recall | False reports | Cost a pair |
| --- | ---: | ---: | ---: |
| One pair a request | 87.2% | 8.2% | $0.00061 |
| Five look-alikes a request | 84.7% | 8.7% | $0.00038 |

Higher recall is better; lower false reports and cost are better. The grouped answer made the same report decision
as the pair answer on 676 of 750 pairs (90%). Five of 755 grouped answers could not be read.

Caveats:

- Opus is a stronger model reading the pair question, not a human label.
- The first row has 133 reports where an earlier run (#182) published 135 for the same commits and cached answers.
  The two were not traced.
- A replay gives every commit a fresh allowance. Multi-push pull requests were not replayed.

## Design notes

These are the documentation changes the patch makes to `docs/design.md`, `docs/benchmark.md` and `docs/judges.md`.
They are not merged into the repository's docs, so this section is their home.

**Why a changed function is asked about together with its look-alikes.** A changed function usually has several
exploration look-alikes, and each pair question repeats the rules and the changed function's source. A judge with
`group` above 1 (an option of the `anthropic` judge) is asked about one changed function and up to that many of its
look-alikes in one request, and answers with one verdict per pair.

**What stays per pair.**

- The verdict. The request tells the judge to decide every pair on its own evidence. Each pair gets its own verdict,
  its own store record and its own finding. Nothing is reported about the group.
- The reservation. Every pair is reserved before the request is sent, and the caps count pairs, not requests. The
  reservations of one request sum to its conservative bound; its measured cost is shared between them.
- Failure. A pair that the answer leaves out, or answers twice, has no verdict: it is unfinished work, asked again by
  a later push, never a "no". A request that fails as a whole fails every pair in it.

**What is never grouped.** Baseline pairs, residual pairs, pairs of different changed functions, and a pair an
adopter policy applies to, whose question carries that policy.

**Why a grouped answer may be reused.** A stored verdict may be reused only when the answer cannot have changed. A
grouped answer is the answer to another question than a pair's, so the group size is part of the judge's version
(`...:group-1x5`). A judge that asks alone, or in another group size, never reuses it, and it never reuses theirs.
Within one version, the scheduler reuses a verdict only for the same two exact sources. That leaves one thing a pair
question does not have: the companions the pair was asked with can differ between pushes. The rule treats them like
the model's own sampling. On 750 labelled pairs the grouped answer made the same report decision as the pair answer
90% of the time; pair answers at two effort settings agree 94% of the time.

**It is off by default.** Grouping is cheaper, and on real commits it reports more pairs that a stronger model
rejects. No preset uses it.

**Benchmark note.** The patch adds a "Grouped pair questions" section to `docs/benchmark.md`. The labelled pairs were
measured in November 2026 with `balanced`'s text judge, Claude Haiku 5.5 at low effort. The section holds the two
tables above, labels Opus as a stricter judge and not ground truth, and ends with the decision that `group` stays an
opt-in option of the `anthropic` judge and no preset sets it.

**Judges note.** In `docs/judges.md` the `anthropic` row lists `group` next to `effort` as an option.

## Applying the patch

[runtime.patch](runtime.patch) is the whole change of draft pull request #185 (source, tests and docs), 884 lines in
10 files. It is the output of `git diff origin/claude/balanced-low-effort...origin/claude/grouped-pair-judging`, so
it does not include the commit of pull request #183 that #185 was stacked on.

The base is commit `fae7367b5a68000fad20d29b31602f8578a31336`, the tip of that #183 branch. From a checkout of that
commit:

```bash
git apply examples/research/grouped-pair-judging/runtime.patch
```

**It does not apply to current `main`.** `git apply --check` on `main` at `4fd79af` fails on three files:
`docs/benchmark.md`, `docs/judges.md` and `tests/test_discovery.py`. Since the base, `main` changed the `balanced`
judge and the files around it, including `src/dry_lint/judges/langchain.py`, `src/dry_lint/presets.py` and the
tests of both. The other files in the patch (`discovery.py`, `judges/anthropic.py`, `judges/command.py`,
`judging.py`, `design.md` and `tests/conftest.py`) did not fail the check, but they were not applied or run against
`main`, so treat the port as unfinished work.

How the base was checked: the base is the merge base of the two branches, and the two-dot diff
`git diff origin/claude/balanced-low-effort origin/claude/grouped-pair-judging` has the same blob hash as this file
(`40bc7a922abf2bde25e92ddbdb8a19e6f1c1296e`). So the patch is exactly the change from the base to the head of #185.
It was not applied in a checkout of the base here.

## Tests

The patch adds `tests/test_grouped_judging.py` with 18 tests. They cover:

- the grouped question being the pair question with another opening, and refusing two changed functions or an
  adopter policy;
- the answer parser: objects read by the number each names, a pair answered twice or out of range getting no
  verdict, an unreadable score leaving only its own pair unknown, and unnumbered answers read by position only when
  none is missing;
- the group size being part of the judge's version;
- the scheduler: look-alikes of one changed function sharing a request with their own verdicts, baseline pairs and
  other changed functions never grouped, an adopter-policy pair asked alone, the group size limit, and the pair cap
  counting every pair of a group;
- failure: a pair the answer omits failing alone, and a failed request failing every pair and storing nothing;
- reuse: grouped answers reused for the same pairs and never by another group size, a stored look-alike not asked
  again inside a group, a look-alike already asked about this revision neither joining nor blocking a group, and a
  judge that cannot group asked one pair at a time.

The tests live in the patch. They are not in the repository and CI here does not run them. On the #185 branch the
suite passed except `tests/test_research_mining.py::test_concurrent_cold_writers`, which fails on Windows on `main`
as well.

## Related

The study in [../family-judging/](../family-judging/) (pull request #188) tested a different question on the same
clusters: judging a cluster as a family.
