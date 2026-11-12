# Luau model-shape validation

Scope: a Python plugin over the existing tree-sitter Luau parser, feeding the existing model pipeline.
Dynamic class factories, metatable inheritance and cross-file type resolution remain outside this change.

- Real parser fixtures cover exported/generic records, direct intersection fields, named/multiple table bindings,
  quoted keys, casts, optional fields, methods, malformed source and unsupported dynamic shapes.
- Temporary Git repositories exercise automatic opt-in model detection, split detect/judge reports, standalone
  model scans, inline decisions and `--no-models`. Defaults retain Python/TypeScript only.
- Verdict-store tests prove changed local usage reopens review; typed/default edits change structural hashes.
- Candidate and index round trips preserve Luau declarations; old Python declarations remain readable.
- Run focused Windows tests with coverage, the full Linux suite, Ruff, build and candidate-only dry-lint.

The initial contract suite failed because `luau-models` was unregistered and the automatic profile omitted it.
Synthetic fixtures verify retrieval and integration, not real-world model-review precision or recall.
