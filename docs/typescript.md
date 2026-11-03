# TypeScript and Bun

Use the same GitHub Action in a Bun, npm, pnpm, or Yarn repository. It installs Python and dry-lint itself;
it does not install or execute the application's dependencies. No `pyproject.toml` is needed.

```yaml
name: dry-lint
on: [pull_request]
permissions:
  contents: read
  pull-requests: write
jobs:
  duplication:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7
        with:
          fetch-depth: 0
      - uses: gigaverse-app/dry-lint@main # pin a reviewed commit in production
        with:
          typesafe-api-key: ${{ secrets.TYPESAFE_AI_API_KEY }}
          warn-only: "true"
```

The sticky comment links each finding to both implementations at the scanned commit. Subsequent pushes
update the same comment; fixing the duplicates resolves it. For fork pull requests, also install the
[separate judge workflow](../examples/dry-lint-judge.yml), which reads candidate text without running fork code.

Without a judge key, candidates appear in annotations but are not claimed as confirmed duplicates. Start
with warnings while reviewing relevance in your repository. The published Python benchmark does not establish
TypeScript precision or recall.

## Configuration

Commit `.dry-lint.toml` at the git repository root. Paths are relative to that root, including in monorepos:

```toml
extractors = ["typescript"]
include = ["src/*", "packages/*", "apps/*"]
exclude = ["*.d.ts", "*.gen.ts", "*/generated/*", "*/dist/*", "*/node_modules/*",
           "*.test.ts", "*.test.tsx", "*.spec.ts", "*.spec.tsx", "*.stories.tsx"]
max_findings = 8
```

Patterns use Python `fnmatch`: `*` also matches directory separators. Both languages are enabled by default;
set `extractors` explicitly to restrict a mixed repository. `.d.ts`, `.d.mts`, and `.d.cts` declarations are
always skipped. Only git-tracked files are read.
Candidates stay within the same extractor, so a mixed Python/TypeScript repository is not told to call a
Python function from TypeScript. TS and TSX implementations can be compared with each other.

For intentional families, add `[[patterns]]` entries to this file. For an individual pair, put a real
TypeScript comment inside the function body:

```ts
export function formatPreview(text: string) {
  // dry-lint: distinct-from src/format.ts::formatTitle
  return text.trim();
}
```

## What is detected

The built-in `typescript` extractor uses Tree-sitter's TypeScript and TSX grammars. It supports named
functions, async functions, generators, variable-bound arrows and function expressions, class methods and
arrow fields, object methods, accessors, namespaces, anonymous default-export functions, and functions wrapped
in `memo`, `forwardRef`, `debounce`, or `throttle`. One-line helpers count. Nested functions remain part of their
parent. Arbitrary anonymous callbacks and empty implementations are not independent candidates.

Fingerprints retain calls, properties, object keys, identifier words, JSX tags, loops, `try`, and `await`.
Type annotations, comments, and arbitrary prose do not contribute similarity. A syntax error skips the affected
implementation; valid siblings still participate. This is syntax-based analysis, not TypeScript type checking
or import resolution. Framework boilerplate can still look similar; the judge and explicit patterns settle it.

Structure hashes ignore comments, spacing, semicolons, and type annotations while retaining operators, literals,
runtime modifiers, properties, and binding names. TypeScript renames deliberately invalidate verdicts:
shadowed bindings and shorthand property keys make naive identifier normalization unsafe. The Python
extractor's existing rename normalization is unchanged. TypeScript hashes carry a language/version prefix.

## Local use and audits

```bash
uvx --from git+https://github.com/gigaverse-app/dry-lint dry-lint check
uvx --from git+https://github.com/gigaverse-app/dry-lint dry-lint scan --limit 20 --warn-only
```

`check` reports changed functions against existing code. `scan` reviews the repository backlog; keep it separate
from the PR check so existing debt does not appear to have been introduced by the current change.
