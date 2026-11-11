# Judging a cluster as a family finds more, and is not yet precise enough to report

**Not adopted.** Asking the judge about six look-alike functions at once, and letting it answer with groups that
should share one implementation, found slightly more of the labelled duplicates than the single-pair judge (82.1%
against 78.8% at a 0.5 line). It also reported three to four times as many labelled non-duplicates (14.9% against
4.1%). The single-pair judge stays the default. The prompt, the schema, the runner and the open follow-ups are kept
here so the work can be picked up.

## The idea

A duplicate is rarely one pair. The same operation, or the same segment inside larger functions, usually appears
several times. A pair shows the judge two of the copies; a family shows it all of them, so it can see which lines are
the contract and which are per-caller variation. The useful answer is then not a score per pair but a finding a
maintainer can act on: these functions carry out one operation, this is what must stay in sync, these differences
are deliberate and would become parameters, and these differences nothing explains.

Two points shaped the schema:

- Identical copies are not the safe case. They are drift that has not happened yet, so a group is never scored lower
  for having no differences.
- A difference between copies is either a policy choice or a change made in one copy only. The judge has to say
  which, and may say that the sources do not tell.

## What the judge is asked

[prompt.md](prompt.md) is the third version of the prompt. [judge.py](judge.py) holds the answer schema
(`FamilyVerdictPromptSchema`) and sends the rules as a cached block with the model free to think before it calls
the tool. The request carries the prompt up to its `# Output` heading; the JSON layout below that heading is what
the subagent rounds answered in, and the schema replaces it. An answer is:

- `groups`: each with the `operation`, the `decisions` all members make the same way, the `members` (with the
  `region` of each function that is the shared part, and `keep_apart` for a member such as an example script),
  `parameters` (deliberate differences), `unexplained` differences (who does what, the consequence, what has to be
  decided), an `action`, an `owner` and a `score`.
- `ungrouped`: every other function, with a kind: unrelated, shape only, already the shared implementation, or a
  caller of it.
- `suspected_copies_elsewhere` and `missing_information`.

The score is confidence that the members carry out the same operation. It is not lowered for drift, for small size
or for refactoring effort.

## How the prompt got to version three

Eight clusters of six functions from public repositories (LiteLLM, OpenHands, opencode and one more) were judged by
Claude subagents acting as the judge. Each agent judged all eight in one session, so the clusters were not isolated
from each other.

| Round | Judges | What it showed |
| --- | --- | --- |
| 1 | Three output layouts on Sonnet, Opus as reference | Every judge produced the same main groups in every cluster, whatever the layout. They disagreed on bookkeeping: copy or drifted, label, action, score. |
| 2 | Haiku, Sonnet, Opus on one revised prompt | Found drifted sync and async twins that the pairwise judge had scored 0.3, and duplicates between two existing functions that no pair call had compared. Haiku missed one group and muddled another. Answers ran 4 to 19 KB. |
| 3 | Haiku, Sonnet on a shorter prompt | Haiku matched Sonnet on the main groups in the six clusters it finished. Answers roughly halved. |

Changes that came out of the judges' own notes:

- The first definition asked for "the same outcome and failure behaviour", which excluded drifted copies. A group
  is now "the same domain steps toward the same purpose"; a behaviour difference is recorded, never a reason to
  leave a member out.
- One field mixed "whole body or segment" with "in sync or drifted". Members now only say which region is shared.
- "Keep apart" contradicted a score that meant "consolidating is right". The score now means "same operation" and
  keep-apart is a flag on a member.
- A test for a small segment against generic shape: it is an operation if it encodes a domain decision that must
  change in every copy together.
- A difference lists its sides, because "members 1, 2, 3" did not say who does what.

One drift finding was checked against the source: of four hard-budget checks in LiteLLM's `auth_checks.py`, three
block at `spend >= max_budget` and the team check blocks at `spend > max_budget`.

## Measurement

748 labelled pairs. Each cluster is the changed function, the labelled other function and the four nearest
look-alikes of the changed function by token overlap. One request per cluster to Claude Haiku 5.5 at low effort with
thinking. A labelled pair counts as reported when both functions are members of one group at or above the line. The
comparison is the shipped single-pair schema judge on the same pairs.

| | Family | Single pair | Better is |
| --- | ---: | ---: | --- |
| Ranking quality (AUC, 95% interval) | 0.861 (0.834 to 0.890) | 0.965 (0.952 to 0.974) | higher |
| Labelled duplicates reported at 0.5 | 82.1% | 78.8% | higher |
| Labelled non-duplicates reported at 0.5 | 14.9% | 4.1% | lower |
| Labelled duplicates reported at 0.6 | 75.0% | 64.1% | higher |
| Labelled non-duplicates reported at 0.6 | 10.1% | 1.4% | lower |
| Cost for one changed function against five others | $0.0018 | $0.0026 | lower |
| Seconds per request | 8.7 | about 2.6 per pair | lower |

- 746 of 748 requests gave a valid answer; 43 needed a second request with the tool call forced.
- 68 groups had a single member, and 11 answers did not account for all six functions.
- 0.75 unexplained differences per group.

## Why it reports more non-duplicates

A sample of the 65 labelled non-duplicates grouped at 0.5 or above was read. Most had scored 0.1 to 0.3 with the
single-pair judge. Three causes:

1. **Delegation missed.** Two functions that both only call the same helper were grouped as whole-body copies. The
   prompt has the delegation rule; with six functions to read, the judge applies it less carefully than with two.
2. **A rule this prompt added.** It says sync and async versions are "usually one operation written twice". Some of
   those pairs are labelled separate by a person.
3. **Field-by-field mapping.** Adapters that map different records into one shared shape were grouped. The labels
   treat that as shape.

Filtering does not repair it. Counting only groups in which both functions are whole-body members cuts reported
non-duplicates to 6.9% and reported duplicates to 28.8%.

## Earlier result: several pairs in one request

Before the family schema, the same clusters were sent with a different question: one verdict per pair, each "on its
own evidence". That is batching, not family judging, and it also lost precision.

| Five pairs a request, schema judge without thinking | Batched | Single pair |
| --- | ---: | ---: |
| AUC | 0.916 | 0.962 |
| Labelled non-duplicates reported at 0.3 | 15.4% | 7.8% |
| Labelled non-duplicates reported at 0.4 | 6.2% | 2.5% |

Of 39 non-duplicates that crossed 0.3 only when batched, 26 scored exactly 0.30 and 33 were still labelled
"separate": the model ranks the candidates against each other and the closest lands on the line. The same question on
real commits through the production scheduler is in pull request #185, with the same conclusion: cheaper, and less
precise.

## Follow-ups

None of these has been run.

1. **Make delegation explicit per member.** A field naming the helper each member calls for the operation, and the
   rule that members who all call the same helper are not a group.
2. **Soften the sync and async rule** to "compare them step by step", without the prior that they are one operation.
3. **Two steps.** The family request proposes groups; the single-pair judge confirms each pair of a group before it
   is reported. This keeps the pair judge's precision and uses the family for discovery and for the differences.
4. **Build real families.** These clusters are one function's neighbours. A family should be functions linked to
   each other by the detector, which is where a group of four or five copies would show its value.
5. **Score what the labels cannot.** Groups among the unlabelled functions, and the unexplained differences, were
   not refereed. A stronger model or a person should judge a sample.
6. **Verdict reuse.** A family answer depends on which other functions were in the request. Storing it needs a key
   on the member set, and the argument and test that `AGENTS.md` asks for.
7. **Stability of small segments.** A three-line shared decision appears in some answers and not in others.

## Limits

- The labels are pair labels for "actionable duplication". The family score means "same operation", so some of the
  gap is a difference in the question, not only in accuracy. It was not separated.
- The subagent rounds had no labels and eight clusters. They guided the wording; they measure nothing.
- One run per configuration. Run-to-run variation was not measured.
- The clusters include private repositories, so the jobs and answers are not in this directory.

## Running it

```bash
python judge.py jobs.jsonl family-answers.jsonl
python score.py jobs.jsonl family-answers.jsonl single-answers.jsonl
```

A job is one JSON line with `id`, `slot`, `label` and `functions` (`name` and `code` each); function 1 is the
changed function and function `slot + 2` is the other half of the labelled pair. `judge.py` needs
`ANTHROPIC_API_KEY` and the `langchain-anthropic` package, and a full run cost about $1.40.
