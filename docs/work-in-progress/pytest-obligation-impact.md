# pytest-obligation cleanup: impact and regression examples

Evaluate merged pytest-obligation PR #206 against its exact parent. Distinguish
measured structural changes, preserved behavior, demonstrated bug fixes and
performance claims. Carry the useful lessons into the adoption playbook and a
permanent case study; preserve difficult before/after pairs as public gold data.

- [ ] Count source changes and inspect the shared owners and their callers.
- [ ] Check behavior-change claims against the diff and existing real-system CI.
- [ ] Freeze representative positive, delegated and semantically distinct pairs
  with source revision, rationale and honest label provenance.
- [ ] Validate the examples through the existing gold loader/extractor and run
  the real judge as an explicitly limited diagnostic, without changing thresholds.
- [ ] Run the appropriate offline suite and inspect current-head CI.

No PR template was found. This work does not change detection policy or equate
baseline pair counts with bugs fixed, lines removed or production speedups.
