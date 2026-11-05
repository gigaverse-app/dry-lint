# Language analysis and shared DRY policy

Keep one detector and judge pipeline. Existing extractors own language syntax and provide serializable facts;
core owns exclusions. Inheritance and calls alone are evidence, not proof that executable policy is already shared.
Only a conservatively recognized forwarding body may settle a delegation pair. Unknown facts never suppress it.

- [ ] Python/TypeScript extraction parity: forwarding wrappers versus wrappers with additional executable policy.
- [ ] Overrides retain repeated implementations; declarations without bodies remain excluded.
- [ ] Python special-method classification does not exempt TypeScript names beginning with double underscores.
- [ ] Same-named targets, shadowing, dynamic receivers, nested callbacks and unresolved imports do not invent delegation.
- [ ] Extraction facts survive candidate and function-index serialization; changing analysis facts invalidates verdicts.
- [ ] Detector/check/scan exercise the shared policy, with existing inline decisions and configured patterns preserved.
- [ ] Run extraction and detector comparisons against committed web and mobile adopter sources; report each separately.
- [ ] Full offline tests, lint, build and dry-lint self-check.

Adopter patterns inspected: chat search-source subclasses in web/mobile (getters, arrow fields, `super.query` with
additional work); web logger inheritance; mobile React error boundary (static methods, arrow field, render method).
Use reduced synthetic examples in public regression tests; keep private adopter source out of this repository.
