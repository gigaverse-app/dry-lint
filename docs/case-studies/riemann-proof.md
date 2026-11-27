# Mathematical engineering: what a proof of the Riemann Hypothesis taught a duplication linter

Lean's kernel has accepted a proof of the Riemann Hypothesis. The community edition is 805 Lean files and
about 300,000 lines of code, and its maintainers ask contributors for one thing: make it easier to read.
[Repository and goals](https://github.com/leanprover-community/riemann-hypothesis#riemann-hypothesis)

A text of that size that many people change is a codebase. It has the same maintenance problem as any
codebase: the same argument gets written more than once, and nobody can hold all of it in their head to
notice. We call the work of keeping such a proof readable *mathematical engineering*.

dry-lint finds code that repeats what a codebase already has. We pointed it at the proof for two days.
This page reports what it found, what it got wrong, and what changed in dry-lint as a result. Every one of
those changes also applies to Python and TypeScript.

## Results

As of November 27, 2026:

| | |
| --- | ---: |
| Refactoring pull requests opened on the proof | 30 |
| Of those, found with dry-lint, as their descriptions say | 27 |
| Open | 28 |
| Rated ready by the project's review agent | 27 |
| Withdrawn after review | 2 |
| Merged | 0 |
| Lines the open pull requests remove | 2,226 |
| Lines they add | 562 |

A maintainer still has to approve each one, and none has been merged yet. One pull request accounts for
1,299 of the removed lines: it deletes a route through the proof that nothing uses.
[The pull requests](https://github.com/leanprover-community/riemann-hypothesis/pulls?q=is%3Apr+author%3Aaviadr1+refactor)

## Three kinds of repetition

### A declaration that restates another

`dry-lint scan` compares every declaration with every other and lists the closest pairs. In the proof it
surfaced a private lemma that proved a finite sum of continuous functions is continuous. Mathlib already
has that lemma, `continuous_finsetSum`. The fix deletes the private proof and calls Mathlib's lemma at the
seven places that used it. [Pull request](https://github.com/leanprover-community/riemann-hypothesis/pull/9442)

This is the case dry-lint was built for in software. A coding agent asked for a short caption does not
search for the existing `shorten_text`; it writes a new function. In pytest-selective, retiring seven such
pairs fixed four correctness bugs, because the copies had drifted apart.
[Case study](pytest-selective.md)

### Lines repeated inside different proofs

Two theorems can differ and still share six lines in the middle. Whole-declaration comparison misses that.
We wrote a matcher for it, `lean-proof-blocks`, which reads the steps of each tactic proof and reports
blocks of lines that occur more than once. Several of the open pull requests state such a block once, as a
lemma, and use it in both places.
[Example](https://github.com/leanprover-community/riemann-hypothesis/pull/8856)

Nothing in that matcher is specific to Lean, so it is now `dry-lint blocks` and reads every language
dry-lint supports. On Celery it reports one connection check written eight times in a single file.
[Guide and measurements](../blocks.md)

The first repository we ran it on was dry-lint. It found the nested-comment scan of the Lean extractor
written twice in one file. We had written the second copy the day before.
[Pull request](https://github.com/gigaverse-app/dry-lint/pull/233)

### One argument used by a family of proofs

After a build, Lean records which lemmas each proof refers to. `lean-proof-families` reads those records
and groups three or more declarations whose proofs cite the same lemmas in the same order. This one does
depend on the compiler, and has no counterpart for other languages yet.

## What the proof taught the tool

### Measure what the tool cannot see

A scan that reports nothing is reassuring only if it read everything. Lean records where every declaration
is, so we compared dry-lint's Lean extractor with the compiler.

| Extractor version | Declarations found | Share |
| --- | ---: | ---: |
| First release | 8,690 of 21,842 | 39.8% |
| Grammar with recovery | 16,859 of 21,952 | 76.8% |
| Command boundaries read from the source text | 21,948 of 21,952 | 99.98% |

For the first version, "no duplicates found" covered four declarations in ten. The last version runs on
Mathlib unchanged and finds 241,301 of 241,397.
[Coverage audit](https://github.com/gigaverse-app/dry-lint/pull/208) ·
[Command scanner](https://github.com/gigaverse-app/dry-lint/pull/219)

The same question applies to any language: when a file does not parse, does the tool say so? `--require-complete`
makes a scan fail on a file its extractor cannot read. For Lean it used to reject 799 of 801 files, because
the grammar did not know the proof's notation, so nobody could turn it on. It now rejects a file only when
a comment or string is never closed or a command's brackets do not balance, and rejects none of the proof's
files.
[Strict validation](https://github.com/gigaverse-app/dry-lint/pull/230)

### Size finds the slow paths

The proof has 21,952 declarations. A full scan took 15 minutes 12 seconds. Most of that went to the nearest-neighbour index, which walked the posting
lists of common tokens that could never lift a pair above the reporting floor. The index now stops once the
remaining tokens cannot reach the floor. The scan takes 5 minutes 48 seconds and prints the same pairs with
the same scores. The index is shared by every language, so Python and TypeScript scans got the same change.
[Index pruning](https://github.com/gigaverse-app/dry-lint/pull/228)

Moving the block matcher out of the Lean module had a similar effect. The shared loop drops a proof from
the search once it has no match of the current length. On the Riemann proof, in the mode that allows one
differing line, it prints byte-identical output in 7.8 seconds where the old loop took 48.2.

### A candidate is a question

In software, a judge model answers "are these one concept?" well enough to gate a pull request. For a proof
we did not use a judge. Each candidate went to a person, then to the project's reviewers. Two results stand
out.

- **The shared version was longer.** Two counting lemmas had the same three-line proof by induction. We
  derived one from the other by reindexing the sum. The reviewer answered: "The new proof is longer and
  harder to follow than the one it replaces." We withdrew it. The duplication was real, and removing it made
  the text worse. [Withdrawn pull request](https://github.com/leanprover-community/riemann-hypothesis/pull/8836)
- **The explanations went missing.** Several refactorings merged two cases and dropped the comment that
  listed the cases. Reviewers asked for the comments back each time. A reader needs the list of cases more
  than the saved lines. [Example review](https://github.com/leanprover-community/riemann-hypothesis/pull/8908)

dry-lint's own documentation says the same about code: some look-alikes should stay separate, and the tool
has a way to record that decision so it is not raised again.
[When it is right not to merge them](https://github.com/gigaverse-app/dry-lint#when-it-is-right-not-to-merge-them)

There is also a rule about volume. The project asks contributors who want to make one kind of change in
many places to open one pull request and wait for a maintainer's answer before opening the rest. We opened
thirty in two days. A tool that produces candidates quickly makes that rule matter more.

## Proofs and programs differ in one way that matters here

In a program, two copies of a rule drift. One gets the fix and the other does not, and the bug ships. That
is why duplicated code is a correctness problem, and why the pytest-selective cleanup found four bugs.

In a checked proof, a copy cannot be wrong: the kernel accepts both or the build fails. Duplication there
costs readers instead. Someone studying the proof reads the same calculation twice and has to check for
themselves that it is the same. Someone changing a definition repairs every copy.

The kernel also changes what a refactoring risks. A refactoring that compiles has not broken the theorem.
It can still make the text harder to read, and no checker catches that.

## Try it

On any repository, without a key:

```sh
# Functions that look alike
uvx --no-config --python 3.13 dry-lint scan --judge none --limit 30

# Lines repeated inside different functions
uvx --no-config --python 3.13 dry-lint blocks --include 'src/**'
```

On a Lean project:

```sh
uvx --from 'dry-lint[lean]>=1,<2' dry-lint scan --extractor lean --judge none --limit 30
uvx --from 'dry-lint[lean]>=1,<2' dry-lint blocks --extractor lean --lines 4
```

Then read each candidate as a question: is this the same thing, and would stating it once read better?

The CI side of the same week, with queue measurements and build-retry tooling, is in
[CI-esta's essay](https://ci-esta.readthedocs.io/en/latest/mathematical-engineering/).
