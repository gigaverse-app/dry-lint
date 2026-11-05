# Language analysis and shared DRY policy

Keep one detector and judge pipeline. Existing extractors own language syntax and provide serializable facts;
core owns exclusions. Inheritance and calls alone are evidence, not proof that executable policy is already shared.
Only a conservatively recognized forwarding body may settle a delegation pair. Unknown facts never suppress it.

- [x] Python/TypeScript extraction parity: forwarding wrappers versus wrappers with additional executable policy.
- [x] Overrides retain repeated implementations; declarations without bodies remain excluded.
- [x] Python special-method classification does not exempt TypeScript names beginning with double underscores.
- [x] Same-named targets, shadowing, dynamic receivers, nested callbacks and unresolved imports do not invent delegation.
- [x] Extraction facts survive candidate and function-index serialization; changing analysis facts invalidates verdicts.
- [x] Detector/check/scan exercise the shared policy, with existing inline decisions and configured patterns preserved.
- [x] Run extraction and detector comparisons against committed web and mobile adopter sources; report each separately.
- [x] Full offline tests, lint, build and dry-lint self-check.

Adopter patterns inspected: chat search-source subclasses in web/mobile (getters, arrow fields, `super.query` with
additional work); web logger inheritance; mobile React error boundary (static methods, arrow field, render method).
Use reduced synthetic examples in public regression tests; keep private adopter source out of this repository.

Validation: 55 new regression cases pass; CI on Python 3.11/3.13 passes the full suite at 100% coverage.
Both adopter snapshots retain all extracted functions and candidate pairs. Strict validation still finds the
same pre-existing parser gaps (four web files, one mobile file); these runs make no accuracy claim.
Detailed measured counts and source revisions are in PR #73.
