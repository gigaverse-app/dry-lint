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

## The running account

Every sticky ends with the pull request's ledger, here after four pushes, and the repository's line once its default branch has folded a merged pull request. Illustrative figures, rendered with the production ledger renderer.

#### 🛡️ This pull request so far

**2 duplicates kept out of the codebase** for $0.007 of judging, across 4 pushes.

![kept out: 2](https://img.shields.io/badge/kept_out-2-2EA043?style=flat-square&labelColor=24292F) ![pushes: 4](https://img.shields.io/badge/pushes-4-6E7781?style=flat-square&labelColor=24292F) ![functions checked: 60](https://img.shields.io/badge/functions_checked-60-6E7781?style=flat-square&labelColor=24292F) ![judgments: 3](https://img.shields.io/badge/judgments-3-6E7781?style=flat-square&labelColor=24292F) ![spent: $0.007](https://img.shields.io/badge/spent-%240.007-2563EB?style=flat-square&labelColor=24292F)

<details><summary><strong>Push by push</strong></summary>

| Push | Commit | Changed | Look-alikes | Judged | Duplicates | Cost |
| --: | :-- | --: | --: | --: | --: | --: |
| 1 | `3f9a1c2` | 14 | 3 | 3 | 3 | $0.004 |
| 2 | `8be41d0` | 15 | 1 | 0 <sub>+1 reused</sub> | 1 | $0.001 |
| 3 | `c01d7e9` | 15 | 1 | 0 | 0 | under $0.001 |
| 4 | `e5a0b37` | 16 | 0 | 0 | 0 | under $0.001 |
| **4** | | **60** | **5** | **3** | | **$0.007** |

✅ `clip` ≈ `shorten` · found in push 1, kept out in push 2  
✅ `clip` ≈ `trim` · found in push 1, kept out in push 3  
⚪ `clip` ≈ `cut` · found in push 1, dismissed by a person's decision in push 3  

</details>

<sub>🏆 `acme/shop` since Oct 6, 2026: **31 duplicates kept out of the codebase** across 58 merged pull requests, for $0.84 of judging.</sub>
