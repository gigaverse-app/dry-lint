# Recall within the existing PR budget

Normal operation retains the cumulative $0.04 per-PR allowance. Experimental
judgments are accounted separately. The cleanup panels from PRs #90 and #91 are
development regressions, not independent validation or population estimates.

- [ ] Reproduce retrieval and judge misses separately on both cleanup panels.
- [ ] Check the existing shared-operation policies before introducing another policy.
- [ ] Preserve repaired-delegation negatives and independently different contracts.
- [ ] Compare the selected change against broader frozen labels and the shipping
  judge cascade; count lost findings, false reports, unresolved answers and cost.
- [ ] Replay candidate ordering with the same $0.04 allowance, including exhausted
  budgets. More unbudgeted recall alone does not justify changing the defaults.
- [ ] Add a failing regression before implementation, run focused tests, then the
  full suite and coverage gate. Preserve versioned verdict-cache identities.

Keep raw source packets, provider responses and execution evidence outside the
repository. Publish the method, measured results and limitations with the change.
