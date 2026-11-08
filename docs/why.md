# Why dry-lint

Coding agents rarely copy and paste. They write a fresh version of something the
codebase already does, and every copy is a place where the rule can drift. dry-lint
finds those rewrites in each pull request and has a judge decide whether the two
functions are one concept. The backlog you accepted on day one can then only shrink.

## The problem it solves

An agent asked to "show a short caption" does not search for your `shorten_text`.
It writes `preview_caption_text`. Both pass their tests. A month later one rounds
and the other truncates, and two screens disagree about the same title.

Line-based copy detectors (pylint's `duplicate-code`, jscpd) look for repeated
lines, so they miss a rewrite with different names and structure. Review misses it
too: the new function looks reasonable on its own, and nobody remembers the old one.

dry-lint compares what each changed function *does* (the calls, attributes and
identifiers it uses) with every other function in the repository, then asks a judge:

- Is it one concept?
- Do the two already behave differently?
- Which side should own the single implementation?

The answer comes back on the pull request, where the author, human or agent, can act on it:

```text
src/widgets/caption.py:1: preview_caption_text looks like src/text.py::shorten_text (drifted)
    judge 0.91; the two already behave differently; call the existing function;
    similarity 0.71; if they are different concepts, add
    `# dry-lint: distinct-from src/text.py::shorten_text`
```

## What you get, with evidence

| Benefit | Example | Source |
| --- | --- | --- |
| Cleanup found real bugs | Retiring seven accepted pairs in pytest-selective fixed **four existing correctness bugs**, among them a Git helper that could inventory the wrong checkout and a path helper that reported no affected files when the scope was the repository root. The new tests failed 6 of 15 cases on the old code. | [Case study](case-studies/pytest-selective.md) |
| One owner per rule | pytest-obligation took its accepted backlog from 32 pairs to 0. Import-alias handling, a gap grammar and lost-reply counting each went from several implementations to one owner, so the next fix reaches every caller. | [Case study](case-studies/pytest-obligation-cleanup.md) |
| Findings people can trust | The `jev+opus` preset is 98% precise at 85% recall on a 250-pair gold set, for about $0.005 a pull request. The `jev` preset alone is 94% precise, 73% recall. | [Judges](judges.md), [benchmark](benchmark.md) |
| Cheap enough to run on every push | 600 gigaverse-ai pull requests averaged 2.5 judge calls each, uncached. Verdicts are cached by each function's structure, so a cosmetic push usually costs nothing. | [README](../README.md#measured), [design](design.md) |
| Agents fix it themselves | The pre-commit hook judges what an agent stages, for about $0.0002 a commit. The agent reuses the existing function, or records why the two differ, before anything is pushed. | [Judges: who reads the findings](judges.md#who-reads-the-findings-people-or-coding-agents) |
| Progress you can show | A sticky comment counts the duplicates each pull request kept out, and the README sign shows debt cleaned and remaining. | [Comment preview](comment-preview.md), [sweeps](sweeps.md) |

These figures come from the linked measurements and reviewed cleanups. They are not
a promise for every repository: the detector proposes a bounded set of candidates, so
a clean run does not prove that no semantic duplication exists ([sweeps](sweeps.md)).

## The contracts it enforces

dry-lint turns "don't duplicate" from advice into checks a pull request must pass:

| Contract | What enforces it |
| --- | --- |
| A new duplicate does not merge | The required `dry-lint` check fails at the preset's threshold. The author reuses the existing function or declares the difference. |
| Old debt is accepted once and only shrinks | `.dry-lint/baseline.json`, written by a complete judged `sweep --init`. A pull request that widens it is rejected, and the override label cannot waive that. |
| A deliberate difference is written down | `# dry-lint: distinct-from path::name` next to the code, or a reviewed `patterns` entry. Dismissals are counted separately and never as cleanup. |
| Cleanup is recorded | The weekly audit opens one `dry-lint/ratchet` pull request with only the baseline, progress file and README. It never edits application code or merges itself. |
| Forks never see your keys | A fork's pull request only proposes candidates (`dry-lint detect`). A trusted workflow judges them from the default branch. |

[How CI runs it](ci.md) shows the whole flow. To try it now, follow
[the first-run tutorial](tutorials/first-run.md).

## You bring your own keys

dry-lint never provides API keys, models or judge execution. Judges run on the
credentials your repository passes in, at your cost. Without any, it only lists
look-alikes and never fails ([design](design.md#adopters-bring-their-own-keys)).
