# Sticky comment preview

Illustrative verdicts, not measured findings. Generated from [the example report](../examples/comment-report.json) with the production Markdown renderer. On a pull request, function names link to their exact source revision; this local example has no repository metadata.

<!-- dry-lint -->
### dry-lint · Review findings

**2 findings across 3 functions**. Reuse the existing owner or share the common behavior.

**1 at the blocking threshold** (`fail_at`).

5 changed functions · 2 candidate pairs · 0 skipped by rule · 1 cached · 1 newly judged

| Function | Looks like | Verdict | Suggestion |
| --- | --- | --- | --- |
| src/captions.py::clip | src/text.py::shorten | **blocking drifted** 0.95 | call the existing function; Both shorten text, but one cuts through a word while the other preserves whole words. (2 look-alikes) |
| src/captions.py::clip | src/previews.py::preview | **duplicate** 0.86 | extract a shared helper both can call; Both apply the same length limit; share that policy while keeping presentation separate. (2 look-alikes) |

<details><summary>Evidence and next steps</summary>

**src/captions.py::clip** → **src/text.py::shorten**

Judge score: **0.95** · similarity: **0.71** · new verdict

These functions already behave differently; check callers before consolidating.

If they represent different concepts, add this pair-specific decision inside the changed function:

\# dry-lint: distinct-from src/text.py::shorten

**src/captions.py::clip** → **src/previews.py::preview**

Judge score: **0.86** · similarity: **0.71** · cached verdict

If they represent different concepts, add this pair-specific decision inside the changed function:

\# dry-lint: distinct-from src/previews.py::preview

</details>

<details><summary>False positive? Choose the scope of your decision</summary>

False positive? Add `# dry-lint: distinct-from <qualified name>` to the new function (this pair), `# dry-lint: ignore` to a function (that function), a `patterns` entry under `[tool.dry-lint]` (a family), or the `dry-lint: override` label to the pull request (this pull request only). For TypeScript/TSX, use `//` instead of `#`; configuration can also live in `.dry-lint.toml`.

</details>
