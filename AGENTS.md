# Working on dry-lint

Follow [CONTRIBUTING.md](CONTRIBUTING.md) to set up, lint and test. Read [docs/design.md](docs/design.md) before
changing the detector, the store or a judge.

- Keep the detector stateless and model-free, and the judge separate and pluggable. Anything slow belongs behind the
  verdict store.
- A stored verdict may be reused only when the answer cannot have changed. Any rule that reuses more verdicts needs
  an argument, and a test, that the answer still holds.
- Decisions made by people go in code (`# dry-lint: distinct-from`) or in configuration (`patterns`), never in the
  verdict store.
- dry-lint should pass on its own code: run `uv run dry-lint check` before you push.
