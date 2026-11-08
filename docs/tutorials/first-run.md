# First run: from a local scan to a required check

This tutorial takes one repository from "never ran dry-lint" to a judged check that
blocks new duplicates, with the existing debt accepted once. It takes about fifteen
minutes. You need [uv](https://docs.astral.sh/uv/getting-started/installation/) and a
Git repository with Python, JavaScript or TypeScript.

```text
1. scan, no key      ──► see the look-alikes it would propose; nothing fails
2. judge locally     ──► a key turns look-alikes into judged findings
3. accept the backlog ──► sweep --init writes .dry-lint/baseline.json once
4. resolve a finding ──► reuse the existing function, or declare the difference
5. turn on CI        ──► the required dry-lint check guards every pull request
```

## 1. See what it proposes, without a key

From the repository root:

```bash
uvx --no-config --python 3.13 --from git+https://github.com/gigaverse-app/dry-lint@v1 dry-lint scan --judge none --limit 30
```

uv runs dry-lint in its own environment, so nothing is added to your project. This
lists the 30 closest look-alike pairs across the repository. With `--judge none`
nothing is judged and nothing fails, so you see the raw candidates. Most are not
duplicates; that is what the judge is for.

To look only at your branch, compare it with your default branch:

```bash
uvx --no-config --python 3.13 --from git+https://github.com/gigaverse-app/dry-lint@v1 dry-lint check --judge none --base origin/main
```

For a permanent `dry-lint` command, install it once and open a new terminal:

```bash
uv tool install --no-config --python 3.13 git+https://github.com/gigaverse-app/dry-lint@v1
uv tool update-shell
```

## 2. Judge the candidates

Pass a judge credential and dry-lint picks a preset from the keys it finds
([judges](../judges.md)). With a TypeSafe key, Jev judges each pair in about 0.3 seconds:

```bash
export TYPESAFE_AI_API_KEY=...   # or put it in an untracked .env
dry-lint config                  # which preset would run, its thresholds and its cost
dry-lint check --base origin/main
```

Each finding names both functions, the judge's score, whether they already behave
differently and which side should own the code. `dry-lint explain` tells you why
a particular pair was or was not reported.

Write the preset you chose into `.dry-lint.toml` so CI and every contributor use the same judge:

```toml
# .dry-lint.toml
preset = "agent"   # Jev only, recall first; "jev+opus" or "sonnet" put precision first
[budget]
usd = 0.25         # the per-pull-request cap; the one-off sweep below gets its own
```

## 3. Accept the existing backlog once

A real repository already has duplicates. Accept them once, so CI only blocks new
ones, and so later cleanup can be counted:

```bash
dry-lint sweep --init --budget-usd 5 --readme README.md --repository OWNER/NAME
```

This judges every candidate pair in the repository and writes:

- `.dry-lint/baseline.json`, the accepted pairs. From now on it can only shrink.
- `.dry-lint/progress.json` and a progress block in `README.md`.

Read the accepted pairs before committing them; each is a refactoring opportunity.
`--init` refuses to overwrite an existing baseline, and every pair must be judged
before it writes anything ([sweeps](../sweeps.md)).

## 4. Resolve a finding

When a check reports a pair, open both functions and decide.

**They are one concept: reuse the existing one.** Delete the new function, call the
existing owner, and run your tests. If the two had drifted (the finding says
`drifted`), check which behavior the callers actually need first.

**They are different concepts: say so next to the code.**

```python
def preview_caption_text(text: str) -> str:
    # dry-lint: distinct-from src/text.py::shorten_text
    # Captions cut at a word boundary for display; shorten_text is a byte limit for storage.
    ...
```

The comment moves or disappears with the code it explains, and the pair is never
proposed again. For a family of deliberate look-alikes, such as one router per
resource, add a reviewed `patterns` entry instead ([README](../../README.md#when-it-is-right-not-to-merge-them)).

Check the result locally the same way CI will:

```bash
dry-lint check --base origin/main --baseline .dry-lint/baseline.json --baseline-ref origin/main --require-complete
```

`--baseline-ref` proves your branch did not widen the accepted backlog.

## 5. Turn on CI

Commit `.dry-lint.toml`, `.dry-lint/` and the README change. Then add the workflows and
make the `dry-lint` check required, as described in [how CI runs dry-lint](../ci.md).

For coding agents, also install the pre-commit hook. It judges what an agent stages
before the commit, so most duplicates are fixed before a pull request exists
([adoption playbook, step 3](../adoption-playbook.md#3-install-both-local-hooks)).

## Next

- Clean up the backlog deliberately and record the progress: [sweeps](../sweeps.md).
- Choose between precision and recall, and see what each costs: [judges](../judges.md).
- Adopt everything, including model duplication and the weekly ratchet: [adoption playbook](../adoption-playbook.md).
