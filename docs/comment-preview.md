# Sticky comment preview

Illustrative verdicts, not measured findings. Generated with the production sticky and ledger renderers: three pairs were reported on the first analyzed commit, one was cleaned up on the second, and another on the third. The remaining pair stays visible below the cleanup totals. See [the report fixture](../examples/comment-report.json) and [how the ledger counts](github-action.md#the-ledger).

<!-- dry-lint -->

### 🧹 A little less lint

| 🧼 Cleaned up | 🧶 Still tangled | 🏷️ Dismissed |
| :--: | :--: | :--: |
| **2 pairs** | **1 pair** | **0 pairs** |

Latest analyzed commit `ccccccc` · **+1 pair cleaned up** ✨

**2 duplicates kept out of the codebase** for $0 of judging, across 3 pushes. 1 duplicate still open.

![pushes: 3](https://img.shields.io/badge/pushes-3-6E7781?style=flat-square&labelColor=24292F) ![functions checked: 15](https://img.shields.io/badge/functions_checked-15-6E7781?style=flat-square&labelColor=24292F) ![judgments: 3](https://img.shields.io/badge/judgments-3-6E7781?style=flat-square&labelColor=24292F) ![spent: $0](https://img.shields.io/badge/spent-%240-2563EB?style=flat-square&labelColor=24292F)

<sub>Previously reported pairs no longer reported; dismissals do not count as cleanup. Counts reflect current outcomes across analyzed commits.</sub>

<details><summary><strong>Push by push</strong></summary>

| Push | Commit | Changed | Look-alikes | Judged | Duplicates | Cleaned here | Cost |
| --: | :-- | --: | --: | --: | --: | --: | --: |
| 1 | `aaaaaaa` | 5 | 3 | 2 <sub>+1 reused</sub> | 3 | 0 | $0 |
| 2 | `bbbbbbb` | 5 | 2 | 1 <sub>+1 reused</sub> | 2 | **+1** | $0 |
| 3 | `ccccccc` | 5 | 1 | 0 <sub>+1 reused</sub> | 1 | **+1** | $0 |
| **3** | | **15** | **6** | **3** | | **2** | **$0** |

- ✅ `clip` ≈ `shorten` · found in push 1, kept out in push 2
- ✅ `clip` ≈ `trim` · found in push 1, kept out in push 3
- 🟡 `clip` ≈ `preview` · found in push 1, still open

</details>

<!-- dry-lint-ledger {"schema":4,"pushed":3,"tally":{"runs":3,"functions":15,"codebase":0,"pairs":6,"judgments":3,"reused":3,"usd":0.0,"unpriced":false,"subscription_calls":0},"pushes":[{"head":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","tally":{"runs":1,"functions":5,"codebase":0,"pairs":3,"judgments":2,"reused":1,"usd":0.0,"unpriced":false,"subscription_calls":0},"reported":3},{"head":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","tally":{"runs":1,"functions":5,"codebase":0,"pairs":2,"judgments":1,"reused":1,"usd":0.0,"unpriced":false,"subscription_calls":0},"reported":2},{"head":"cccccccccccccccccccccccccccccccccccccccc","tally":{"runs":1,"functions":5,"codebase":0,"pairs":1,"judgments":0,"reused":1,"usd":0.0,"unpriced":false,"subscription_calls":0},"reported":1}],"pairs":{"ae55cb8ebafb5aa3":{"new":"clip","existing":"shorten","found":1,"state":"kept-out","settled":2},"17cdd473c28692c7":{"new":"clip","existing":"preview","found":1,"state":"open","settled":null},"38ffb32ac641392a":{"new":"clip","existing":"trim","found":1,"state":"kept-out","settled":3}},"runs":["1","2","3"]} -->

---

### dry-lint · 1 duplicated concept

![duplicated concepts: 1](https://img.shields.io/badge/duplicated_concepts-1-BF8700?style=flat-square&labelColor=24292F) ![changed functions: 5](https://img.shields.io/badge/changed_functions-5-6E7781?style=flat-square&labelColor=24292F) ![judge: illustrative](https://img.shields.io/badge/judge-illustrative-6E7781?style=flat-square&labelColor=24292F)

Each row is one concept implemented twice: a function this pull request changed, and code the repository already has. Reuse it, or parameterize the difference. The judge's fix for every pair listed: **extract a shared helper**.

| | Concept | Copies | Verdict |
| :-: | :-- | :-- | :-- |
| 🟡 | `clip` ≈ `preview` <sub>· 2 look-alikes</sub> | src/captions.py:8 <sub>changed</sub><br>src/previews.py:3 | **duplicate**&nbsp;0.86 |

<sub>🟡 duplicate</sub>

<details><summary><strong>Reasons, and a one-line dismissal for each</strong></summary>

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

<sub>5 changed functions · 1 pair compared · 1 from the verdict store · judge `illustrative`</sub>

<sub>[dry-lint](https://github.com/gigaverse-app/dry-lint) · commit ccccccc</sub>
