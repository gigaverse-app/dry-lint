# Sticky comment preview

Illustrative verdicts, not measured findings. Generated from [the example report](../examples/comment-report.json) with the production Markdown renderer. On a pull request, function names link to their exact source revision; this local example has no repository metadata.

<!-- dry-lint -->
### dry-lint · 2 duplicated concepts

![duplicated concepts: 2](https://img.shields.io/badge/duplicated_concepts-2-CF222E?style=flat-square&labelColor=24292F) ![blocking: 1](https://img.shields.io/badge/blocking-1-CF222E?style=flat-square&labelColor=24292F) ![drifted: 1](https://img.shields.io/badge/drifted-1-EA580C?style=flat-square&labelColor=24292F) ![changed functions: 5](https://img.shields.io/badge/changed_functions-5-6E7781?style=flat-square&labelColor=24292F) ![judge: illustrative](https://img.shields.io/badge/judge-illustrative-6E7781?style=flat-square&labelColor=24292F)

<!-- dry-lint note -->

Each row is one concept implemented twice: a function this pull request changed, and code the repository already has. Reuse it, or parameterize the difference.

| | Concept | Copies | Verdict |
| :-: | :-- | :-- | :-- |
| 🔴 | `clip` ≈ `shorten` <sub>· 2 look-alikes</sub> | src/captions.py:8 <sub>changed</sub><br>src/text.py:3 | **drifted**&nbsp;0.95<br><sub>blocks · call the existing one</sub> |
| 🟡 | `clip` ≈ `preview` <sub>· 2 look-alikes</sub> | src/captions.py:8 <sub>changed</sub><br>src/previews.py:3 | **duplicate**&nbsp;0.86<br><sub>extract a shared helper</sub> |

<sub>🔴 fails the check · 🟡 duplicate</sub>

<details><summary><strong>Reasons, and a one-line dismissal for each</strong></summary>

🔴 **`clip` ≈ `shorten` <sub>· 2 look-alikes</sub>** · drifted 0.95 · similarity 0.71 · new verdict · the copies already behave differently

> Both shorten text, but one cuts through a word while the other preserves whole words.

Different concepts? Add to captions.py:

```python
# dry-lint: distinct-from src/text.py::shorten
```

🟡 **`clip` ≈ `preview` <sub>· 2 look-alikes</sub>** · duplicate 0.86 · similarity 0.71 · from the verdict store

> Both apply the same length limit; share that policy while keeping presentation separate.

Different concepts? Add to captions.py:

```python
# dry-lint: distinct-from src/previews.py::preview
```

</details>

<details><summary><strong>False positive? Choose the scope of your decision</strong></summary>

| Scope | Decision |
| :-- | :-- |
| this pair | `# dry-lint: distinct-from <qualified name>` in the changed function |
| one function | `# dry-lint: ignore` in that function |
| a family of look-alikes | a `patterns` entry under `[tool.dry-lint]`, or in `.dry-lint.toml` |
| this pull request only | the `dry-lint: override` label |

</details>

<sub>5 changed functions · 2 pairs compared · 1 from the verdict store · judge `illustrative`</sub>
