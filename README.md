# dry-lint: one concept, one implementation
[![CI](https://github.com/gigaverse-app/dry-lint/actions/workflows/ci.yml/badge.svg)](https://github.com/gigaverse-app/dry-lint/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue)](pyproject.toml)
[![Apache 2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/sticky-banner-dark.svg">
  <img alt="dry-lint" src="docs/assets/sticky-banner-light.svg" width="640">
</picture>

Coding agents rarely copy and paste. They write *new* code for a job the codebase already does: a second
`truncate`, another pagination loop, a fresh Mongo query helper, each slightly different. Copy-paste detectors
(pylint's `duplicate-code`, jscpd) look for repeated lines, so they miss this. Every rewrite is also a chance to
drift: one version rounds, the other truncates, and callers get different answers to the same question.

dry-lint finds functions in a pull request that look like they re-implement something that already exists. A
judge decides whether each pair really is one concept, and the result goes back as PR annotations and one comment.

<img src="docs/assets/avatar.png" alt="Lint, the dry-lint mascot: a purple ball of dryer lint holding a lint roller covered in code" width="160" align="right">

```text
src/widgets/caption.py:1: preview_caption_text looks like src/text.py::shorten_text (drifted)
    judge 0.91; the two already behave differently; call the existing function; similarity 0.71;
    if they are different concepts, add `# dry-lint: distinct-from src/text.py::shorten_text`
```

## How it works

1. **Detector** (local, no model, about 5 s on 10,000 functions). It finds the functions the diff touched. Each one
   is compared against every function in other files by a TF-IDF fingerprint of what it *does*: the names it calls,
   the attributes it touches, the words in its identifiers, its loops, `try` blocks and `await`s. The three nearest
   above a floor become candidate pairs. Rules drop known non-duplicates: dunders, one calling the other, declared
   patterns, inline `distinct-from`.
2. **Judge** (separate and pluggable). [Jev](docs/judges.md) answers three typed questions per pair in about 0.3 s:
   - Is it one concept?
   - Do the two already behave differently?
   - Which side should own the single implementation?

   Any LLM CLI can be the judge instead.
3. **Verdict store** (a cache, not a reviewed file). Each verdict is keyed on the pair plus a *structure hash* of
   each function, which comments, formatting and renames do not change. A pair is judged again only when its logic
   changes, so most pushes cost zero judge calls. See [docs/design.md](docs/design.md).

## Quick start

```bash
uvx --from git+https://github.com/gigaverse-app/dry-lint dry-lint check            # changes since origin/main
uvx --from git+https://github.com/gigaverse-app/dry-lint dry-lint scan --limit 30  # the whole repo's backlog
```

Without a judge, dry-lint lists the candidate pairs and never fails. With `TYPESAFE_AI_API_KEY` set, Jev judges
them. To use another judge, pass `--judge command --judge-command "your-llm-cli"` (see [docs/judges.md](docs/judges.md)).

**GitHub Actions** ([examples/dry-lint.yml](examples/dry-lint.yml)):

```yaml
- uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7
  with:
    fetch-depth: 0
- uses: gigaverse-app/dry-lint@main
  with:
    typesafe-api-key: ${{ secrets.TYPESAFE_AI_API_KEY }}
```

The action caches verdicts between runs, adds annotations and keeps a single PR comment up to date. It warns by
default; set `fail-on-findings: "true"` once the team trusts it.

**pre-commit** ([examples/pre-commit-config.yaml](examples/pre-commit-config.yaml)): hook id `dry-lint` checks the
staged functions.

## When it is right not to merge them

Some look-alikes are deliberate. Silence them where the decision belongs:

- **Inline**: put `# dry-lint: distinct-from src/text.py::shorten_text` in the new function. The reason sits next
  to the code it explains, and moves or disappears with it.
- **Families**: declare a pattern of deliberate per-resource instances in `pyproject.toml`:

```toml
[tool.dry-lint]
exclude = ["*/tests/*", "tests/*", "*/migrations/*"]

[[tool.dry-lint.patterns]]
members = "src/*/api/*_api.py::create_router"
reason = "one router per resource"
```

Machine "not a duplicate" verdicts stay in the store and do not need to be checked in.

## Measured

On 120 recent gigaverse-ai pull requests, against a blind two-labeller gold set ([docs/benchmark.md](docs/benchmark.md)):

| | |
| --- | --- |
| Changed functions per commit | median 1, p90 13 |
| Judge calls per PR (uncached) | 2.5 |
| Findings per PR at the default threshold | about 0.2 |
| Jev `reuse-v2`: ranking quality | AUC 0.97 |
| at `report_at = 0.8` | 75% precision, 59% recall |
| at `drop_below = 0.6` | 100% recall |
| Known duplicates found and scored ≥ 0.8 | 11 of 13 |
| Verdict store for the whole repository | about 1,900 pairs, 0.75 MB |

## Settings

All settings live under `[tool.dry-lint]` in `pyproject.toml` or in a `.dry-lint.toml` file. The defaults are the
measured thresholds above:

| Setting | Default | |
| --- | --- | --- |
| `include` / `exclude` | `*.py` / tests, migrations, scripts | fnmatch over tracked paths |
| `neighbours` | 3 | candidates per changed function |
| `min_similarity` / `min_similarity_small` | 0.5 / 0.3 | detector floors; small means under `small_function_lines` (6) |
| `drop_below` / `report_at` / `drift_at` | 0.6 / 0.8 / 0.8 | judge thresholds |
| `reopen_margin` | 0.05 | how much closer a "separate" pair must get before it is judged again |

## Lint

<img src="docs/assets/dry-lint-mark.svg" alt="" width="48" align="left">

Lint is what is left behind when you dry things. It carries a lint roller for picking up duplicated code.
`uv run --with pillow python scripts/make_assets.py` rebuilds the avatar, the mark and the banners from
[docs/assets/lint.png](docs/assets/lint.png).

<br clear="left">

## License

Apache 2.0. See [CONTRIBUTING.md](CONTRIBUTING.md) to work on dry-lint itself.
