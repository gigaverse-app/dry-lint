# Working on dry-lint

Follow [CONTRIBUTING.md](CONTRIBUTING.md) to set up, lint and test. Read [docs/design.md](docs/design.md) before
changing the pipeline, a file format or the store, and [docs/plugins.md](docs/plugins.md) before adding a plugin.

- **Adopters bring their own keys, always.** dry-lint is open source and never ships, holds, proxies or pays for an
  API key, a model, or judge execution. Every judge runs on credentials the adopting repository passes in (action
  inputs, its own environment), at its own cost; with none, dry-lint judges nothing and only lists look-alikes. No
  input defaults to a credential other than the run's own `github.token`, and no code path calls a model on an
  account or endpoint dry-lint operates. The only service dry-lint runs is the opt-out counter, which receives
  anonymous counts, never credentials or code. No change that breaks this is accepted, whatever it would enable;
  `tests/test_adopter_keys.py` guards it. See [docs/design.md](docs/design.md#adopters-bring-their-own-keys).
- The pipeline, the file formats, the reuse rules and the reports are core; extractors, comparers, judges and store
  backends are plugins. A new way to compare or judge is a plugin, not a branch in core.
- Keep the detector stateless and model-free, and the judge separate. Anything slow belongs behind the verdict
  store. Change a file format only with a `schema` bump.
- A stored verdict may be reused only when the answer cannot have changed. Any rule that reuses more verdicts needs
  an argument, and a test, that the answer still holds.
- Decisions made by people go in code (`# dry-lint: distinct-from`) or in configuration (`patterns`), never in the
  verdict store.
- dry-lint should pass on its own code: run `uv run dry-lint check` before you push.
