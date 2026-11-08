# First run: from a local scan to a required check

This tutorial takes one repository from "never ran dry-lint" to a judged check that
blocks new duplicates, with the existing debt accepted once. A coding agent can do all
of it from one prompt: `Set up dry-lint in this repository. Fetch
https://dry-lint.readthedocs.io/en/latest/agent-setup.md and follow it.` It takes about fifteen
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
uvx --no-config --python 3.13 --from 'dry-lint>=1,<2' dry-lint scan --judge none --limit 30
```

uv runs dry-lint in its own environment, so nothing is added to your project. This
lists the 30 closest look-alike pairs across the repository. With `--judge none`
nothing is judged and nothing fails, so you see the raw candidates. Most are not
duplicates; that is what the judge is for. On dry-lint's own repository it prints:

```text
dry-lint: showing the 3 closest of 75 look-alike pairs; raise --limit to see more
src/dry_lint/cpu_embedding.py:131: CpuEmbeddingComparer.for_run looks like src/dry_lint/cpu_tail.py::CpuTailRankFusionComparer.for_run (candidate)
    similarity 1.00; pair a3249c447021f117; if they are different concepts, add `# dry-lint: distinct-from src/dry_lint/cpu_tail.py::CpuTailRankFusionComparer.for_run`; if they are one concept copied on purpose, add a [[patterns]] entry with a reason
src/dry_lint/judges/http.py:49: HttpJudge.judge looks like src/dry_lint/judges/jev.py::JevJudge.judge (candidate)
    similarity 0.98; pair 8b37533910fcfe44; if they are different concepts, add `# dry-lint: distinct-from src/dry_lint/judges/jev.py::JevJudge.judge`; if they are one concept copied on purpose, add a [[patterns]] entry with a reason
src/dry_lint/judges/anthropic.py:100: AnthropicJudge.judge looks like src/dry_lint/judges/command.py::CommandJudge.judge (candidate)
    similarity 0.93; pair b7925665b26ec9e3; if they are different concepts, add `# dry-lint: distinct-from src/dry_lint/judges/command.py::CommandJudge.judge`; if they are one concept copied on purpose, add a [[patterns]] entry with a reason
dry-lint: 3 candidate pair(s), 0 skipped by rule, 0 from the store, 0 judged (no judge), 0 reported
judging: preset custom · no judge · reports and fails at 0.8 · est. $0.000 of $0.04 budget
Models: not checked in this run.
```

That was `--limit 3`. Each pair names a function, its closest look-alike in another
file, and how similar the two look. Functions in the same file are never compared.

To look only at your branch, compare it with your default branch:

```bash
uvx --no-config --python 3.13 --from 'dry-lint>=1,<2' dry-lint check --judge none --base origin/main
```

For a permanent `dry-lint` command, install it once and open a new terminal:

```bash
uv tool install --no-config --python 3.13 'dry-lint>=1,<2'
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

Write the preset you chose into `.dry-lint.toml` so CI, the hook and every contributor use the same
judge, and limit the scope to the code you ship:

```toml
# .dry-lint.toml
preset = "agent"   # Jev only, recall first; "jev" puts precision first, "jev+opus" more so
include = ["src/*"]
[budget]
usd = 0.25         # the per-pull-request cap; the one-off sweep below gets its own
```

`dry-lint config` prints the scope with a count of source files per top-level folder, so a
folder you did not mean to include shows. The baseline you write next records this preset:
everything that checks against it, CI and the hook included, must use the same one
([one preset everywhere](../judges.md#one-preset-everywhere)).

## 3. Accept the existing backlog once

A real repository already has duplicates. Accept them once, so CI only blocks new
ones, and so later cleanup can be counted:

```bash
dry-lint sweep --init --budget-usd 1 --readme README.md --repository OWNER/NAME --branch DEFAULT
```

`DEFAULT` is your default branch (`gh repo view --json defaultBranchRef -q .defaultBranchRef.name`).
`--budget-usd 1` is ample with Jev (273 pairs cost $0.010); use `5` with a Claude preset. No key
on this machine? The [bootstrap workflow](../../examples/dry-lint-bootstrap.yml) runs the same
sweep in GitHub Actions with your secret and uploads the files for you to commit
([CI route](../ci.md#no-judge-key-on-your-machine)).

This judges every candidate pair in the repository and writes:

- `.dry-lint/baseline.json`, the accepted pairs. From now on it can only shrink.
- `.dry-lint/progress.json` and a progress block under a `## Duplicate code` heading in `README.md`.
  Move or rename the heading as you like; later runs only rewrite what sits between the block's markers.

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
