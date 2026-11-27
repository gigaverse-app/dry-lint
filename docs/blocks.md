# Find lines repeated inside functions

`dry-lint check` and `dry-lint scan` compare whole functions. They miss a block of lines that is repeated
inside functions whose other lines differ. `dry-lint blocks` finds those blocks. It compares source lines, needs
no judge and no API key, and reads every language dry-lint has an extractor for: Python, TypeScript, Luau
and Lean.

```bash
uvx --no-config --python 3.13 dry-lint blocks
```

On Celery's `celery/` package (about 47,000 lines) the first result is one block written eight times in
`celery/bin/amqp.py`:

```text
Found 46 repeated blocks.
Stating each once would save about 150 lines.

# 5 lines, 8 copies, saves about 25
celery/bin/amqp.py:91-95
celery/bin/amqp.py:115-119
celery/bin/amqp.py:138-142
celery/bin/amqp.py:167-171
celery/bin/amqp.py:197-201
celery/bin/amqp.py:220-224
celery/bin/amqp.py:244-248
celery/bin/amqp.py:299-303
  if amqp_context.channel is None:
      amqp_context.echo_error('Not connected to broker. Please retry...')
      amqp_context.reconnect()
  else:
      try:
```

Each of the eight commands checks the connection, calls one channel method and handles its error the same
way. The block is a candidate. Whether one helper would read better than eight copies is for a person to
decide.

## What it compares

- Lines inside functions and methods. Imports, constants and other module-level text are not compared.
- Lines are equal when their text is equal after the block's common indentation is removed.
- Blank lines and lines that hold only a comment are skipped, so two copies still match when one has a
  comment the other lacks. The reported range `path:first-last` is in source lines and includes them.
- In Python, docstrings are skipped.
- In Lean, the compared lines are the steps of tactic proofs. Use `--extractor lean` and the `lean` extra.
- A nested function is compared as part of the function around it.

## What it reports

One entry per repetition, the largest saving first. Each entry starts with a summary line:

```text
# 5 lines, 31 copies, saves about 117, 14 overlapping, see --overlaps
```

- **saves about N** is an estimate of the lines that go if the block is stated once: each copy becomes one
  call, and the shared definition costs the block's lines and two more. Two copies of a five-line block save
  one line, so they sort last. The second line of the output adds the estimates up.
- **part of a statement** marks a block that cannot be lifted out as it is: it starts inside a deeper level,
  leaves a bracket open or closes one it did not open, or ends on a comma. Such a block counts half when the
  entries are ordered.
- **N overlapping** counts the other matches of the same repetition. Ten lines repeated in thirty places also
  match as nine lines in thirty-one places and as the same lines shifted by one. A match is reported with
  an earlier entry when that entry covers at least half of its lines. `--overlaps` lists every match.

On a backend with 4,800 files the first entry was a five-line lookup written 31 times in one file. Without
the grouping, four of the first eleven entries contained that lookup.

| Option | Meaning |
| --- | --- |
| `--lines N` | The shortest block to report. Default 5; at least 3. |
| `--max-lines N` | The longest block to look for. Default 200. |
| `--min-shared-chars N` | The least shared text, without indentation. Default 70. It keeps out blocks made of brackets and short keywords. |
| `--allow-one-line-difference` | Also match blocks where one line between the first and the last differs. |
| `--lines N --max-gap-lines G` | Match the first and second half of `N` lines with up to `G` different lines between them in each copy. |
| `--include GLOB` | Scan these tracked paths. The configured `exclude` still applies. Repeat for more. |
| `--extractor NAME` | Read only this language. Repeat for more. |
| `--limit N` | Print at most `N` entries. Default 20. The first line always gives the total. |
| `--by-file` | Print the files with the most repeated lines instead of the blocks. The first copy of a block is not counted. |
| `--overlaps` | Print every match, without grouping and without the summary lines. |
| `--claimed-diff FILE` | Leave out copies that a unified diff already removes at least half of. Repeat for more. |

Tests repeat their setup on purpose. To look at product code alone, pass `--include 'src/**'`.

### Start with the largest file

`--by-file` answers where to begin:

```text
$ dry-lint blocks --include 'celery/**' --by-file --limit 3
Found 46 repeated blocks.
Stating each once would save about 150 lines.

    63  celery/bin/amqp.py
    36  celery/backends/gcs.py
    32  celery/concurrency/asynpool.py
```

### Skip what an open pull request already does

In a repository where several people or agents clean up at once, a candidate may already be taken. Save
the diffs of the open pull requests and pass them:

```bash
gh pr diff 123 > 123.diff
dry-lint blocks --claimed-diff 123.diff
```

A copy is left out when the diff removes at least half of its lines from that file. Lines are compared as
text, so every copy of a block in a file the diff edits counts as taken.

## How it relates to the other commands

| Question | Command |
| --- | --- |
| Does this pull request re-implement a function that exists? | `check` |
| Which functions in the repository do the same thing? | `scan` |
| Which lines were written more than once inside different functions? | `blocks` |
| Which Python functions contain another helper's operation, with different text? | the [operation-blocks comparer](operation-blocks.md) |

`blocks` reads text, so it finds copies and misses re-implementations that use different names. `check` and
`scan` do the opposite. Run both on a repository you are cleaning up.

## Measured

Each run used one core and the default options.

| Repository | Scope | Matches | Entries | Estimated saving | Time |
| --- | --- | ---: | ---: | ---: | ---: |
| [Celery](https://github.com/celery/celery) | `celery/**`, Python | 47 | 46 | 150 lines | 3.4 s |
| [HTTPX](https://github.com/encode/httpx) | `httpx/**`, Python | 99 | 45 | 870 lines | 1.2 s |
| [Zod](https://github.com/colinhacks/zod) | `packages/zod/src/**`, TypeScript | 172 | 127 | 2,480 lines | 4.3 s |
| [Riemann Hypothesis proof](https://github.com/leanprover-community/riemann-hypothesis) | 805 Lean files | 6 | 6 | 8 lines | 6.8 s |

"Matches" is what `--overlaps` lists and "Entries" is the default report. Measured on November 27, 2026.

HTTPX's first entry is nine parameters of a request method, in fourteen methods. Zod's is ten lines of a
format table that 57 locale files each carry. Both are deliberate designs, and both are marked "part of a
statement". The estimate says how much text repeats. It does not say that the text should be merged.

The Lean proof has six repeated blocks of five or more lines in its tactic proofs.

## For extractor authors

An extractor needs nothing new: `blocks` uses the line ranges of the functions it already returns. Two
optional attributes refine it.

- `line_comment`: the marker that starts a comment line, such as `"#"`. Lines that start with it are skipped.
- `block_runs(path, source)`: yields lists of `(line number, text)`. Each list is one run, and a block never
  spans two runs. Define it to choose the lines that are compared. The Lean extractor returns tactic steps;
  the Python extractor leaves out docstrings.
