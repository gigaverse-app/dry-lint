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
Found 43 repeated blocks.

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

Blocks are ranked by reuse: shared lines times the number of extra copies. A block is hidden when a longer
block covers every copy of it, so each repetition appears once, at its longest.

| Option | Meaning |
| --- | --- |
| `--lines N` | The shortest block to report. Default 5; at least 3. |
| `--max-lines N` | The longest block to look for. Default 200. |
| `--min-shared-chars N` | The least shared text, without indentation. Default 70. It keeps out blocks made of brackets and short keywords. |
| `--allow-one-line-difference` | Also match blocks where one line between the first and the last differs. |
| `--lines N --max-gap-lines G` | Match the first and second half of `N` lines with up to `G` different lines between them in each copy. Copies with nothing between the halves are reported too. |
| `--include GLOB` | Scan these tracked paths. The configured `exclude` still applies. Repeat for more. |
| `--extractor NAME` | Read only this language. Repeat for more. |
| `--limit N` | Print at most `N` blocks. Default 20. The first line always gives the total. |

Tests repeat their setup on purpose. To look at product code alone, pass `--include 'src/**'`.

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

| Repository | Scope | Blocks | Time |
| --- | --- | ---: | ---: |
| [Celery](https://github.com/celery/celery) | `celery/**`, 47,000 lines of Python | 43 | 3.5 s |
| [HTTPX](https://github.com/encode/httpx) | `httpx/**`, 8,800 lines of Python | 99 | 1.2 s |
| [Zod](https://github.com/colinhacks/zod) | `packages/zod/src/**`, 90,000 lines of TypeScript | 172 | 4.9 s |
| [Riemann Hypothesis proof](https://github.com/leanprover-community/riemann-hypothesis) | 805 Lean files, 479,000 lines | 6 | 7.1 s |

In HTTPX, 36 of the 99 blocks are parameter lists, repeated in up to sixteen request methods. In Zod, 59 of
the 172 blocks are in locale files, where one function body appears in up to 61 files. Both are deliberate
designs. The count says where repeated text is. It does not say that the text should be merged.

The Lean proof has six repeated blocks of five or more lines in its tactic proofs. With
`--lines 3 --max-lines 12` the same scan reports 107.

## For extractor authors

An extractor needs nothing new: `blocks` uses the line ranges of the functions it already returns. Two
optional attributes refine it.

- `line_comment`: the marker that starts a comment line, such as `"#"`. Lines that start with it are skipped.
- `block_runs(path, source)`: yields lists of `(line number, text)`. Each list is one run, and a block never
  spans two runs. Define it to choose the lines that are compared. The Lean extractor returns tactic steps;
  the Python extractor leaves out docstrings.
