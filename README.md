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

<img src="docs/assets/avatar.png" alt="Lint, the dry-lint mascot: a purple ball of dryer lint holding a mint-green hair dryer" width="160" align="right">

```text
src/widgets/caption.py:1: preview_caption_text looks like src/text.py::shorten_text (drifted)
    judge 0.91; the two already behave differently; call the existing function; similarity 0.71;
    if they are different concepts, add `# dry-lint: distinct-from src/text.py::shorten_text`
```

## How it works

dry-lint is a fixed core (the pipeline, the file formats, the verdict store's rules and the reports) with four
plugin slots: how functions are found, how they are compared, how a pair is judged, and where verdicts are kept.
See [docs/design.md](docs/design.md) and [docs/plugins.md](docs/plugins.md).

1. **Detector** (local, no model, about 4.5 s on 10,000 functions). It finds the functions the diff touched. The
   **comparer** proposes each one's nearest look-alikes in other files; the built-in one is a TF-IDF fingerprint
   of what a function *does*: the names it calls, the attributes it touches, the words in its identifiers, its
   loops, `try` blocks and `await`s. Rules settle known non-duplicates: dunders, one calling the other, declared
   patterns, inline `distinct-from`.
2. **Judge** (separate and pluggable). [Jev](docs/judges.md) answers three typed questions per pair in about 0.3 s:
   - Is it one concept?
   - Do the two already behave differently?
   - Which side should own the single implementation?

   Any LLM CLI, or any program, can be the judge instead, and a second judge can take the scores the first is
   least sure about.
3. **Verdict store** (a cache, not a reviewed file). Each verdict is kept per pair with a *structure hash* of each
   function, which comments and formatting do not change. Python also normalizes local renames; TypeScript
   conservatively re-judges them to preserve binding semantics. Most cosmetic pushes cost zero judge calls.

## Quick start

Python, TypeScript, and TSX are supported out of the box. TypeScript repositories do not need a Python
project, `bun install`, Node, or a build step. The GitHub Action installs its own tools and parses source
without executing your code. See [TypeScript and Bun](docs/typescript.md) for monorepo configuration.

Start with a local candidate pass, then add a judge when you want duplication decisions and failing checks:

| Your next step | Run or read |
| --- | --- |
| Inspect your branch without a model or API key | `dry-lint check --judge none` |
| Understand one candidate | `dry-lint explain path/to/new.py::function path/to/existing.py::function` |
| Try structural matching as well | [Install the optional Dryer comparer](docs/detectors.md) |
| Put judged findings on pull requests | [GitHub Action setup](docs/github-action.md) |
| Find copies across related repositories | [Workspace scans and shared ownership](docs/workspaces.md) |
| See the comment before installing | [Example report](docs/comment-preview.md) |

```bash
uvx --from git+https://github.com/gigaverse-app/dry-lint dry-lint check            # changes since origin/main
uvx --from git+https://github.com/gigaverse-app/dry-lint dry-lint scan --limit 30  # the whole repo's backlog
```

| Command | Does |
| --- | --- |
| `check [--base REF \| --staged]` | detect, judge and report the functions a change touched (base: `origin/HEAD`) |
| `scan [--limit N] [--refresh] [--repo OWNER/NAME=PATH ...]` | the repository's backlog, or cross-repository pairs from a combined workspace |
| `detect --out candidates.json` | CI job 1: propose pairs; no judge, no secrets, no store |
| `judge --candidates candidates.json` | CI job 2: judge them, store the verdicts, report |
| `report --from report.json --format F` | render a report as `text`, `github`, `markdown`, `json`, `sarif` or `check-run` |
| `explain A B` | why a pair is, or is not, reported |
| `bench --gold gold.jsonl [--comparer]` | measure the judge, or the comparer, on a gold set |

`--report report.json` and `--output comment.md` write the report and the PR comment from any command that judges.

Without a judge, dry-lint lists the candidate pairs and never fails. With `TYPESAFE_AI_API_KEY` set, Jev judges
them. To use another judge, pass `--judge command --judge-command "your-llm-cli"` (see [docs/judges.md](docs/judges.md)).

**GitHub Actions** ([examples/dry-lint.yml](examples/dry-lint.yml), [docs/github-action.md](docs/github-action.md)):

```yaml
- uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7
  with:
    fetch-depth: 1
- uses: gigaverse-app/dry-lint@main
  with:
    typesafe-api-key: ${{ secrets.TYPESAFE_AI_API_KEY }}
```

The action annotates the changed functions, keeps one sticky PR comment up to date and caches verdicts between
runs. The comment links both functions at the analyzed commit, shows the review workload, and folds evidence and
pair-specific suppression instructions under each summary. A clean pull request gets a green sticky with what was checked (`comment-on-clean: "false"` to opt out). A reported duplicate fails the check (94% of them are real
duplicates in the benchmark; 98% with Claude Sonnet 5.5 as the second judge); set `fail-at: "0.9"` to fail only on
near-certain ones, and the `dry-lint: override` label lets one through. Pull requests from forks get no secrets, so the default `mode: auto` runs dry-lint
as two jobs for them: `detect` on the pull request, and `judge` in [a `workflow_run` job](examples/dry-lint-judge.yml)
that keeps the key away from pull request code ([docs/design.md](docs/design.md#two-jobs-in-ci)).

**pre-commit** ([examples/pre-commit-config.yaml](examples/pre-commit-config.yaml)): hook id `dry-lint` checks the
staged functions.

## When it is right not to merge them

Some look-alikes are deliberate. Silence them where the decision belongs:

- **Inline**: put `# dry-lint: distinct-from src/text.py::shorten_text` in the new function. The reason sits next
  to the code it explains, and moves or disappears with it.
- **A whole function**: put `# dry-lint: ignore` in it (generated code, a deliberate copy). It is left out of
  every pair, on either side.
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
| at `report_at = 0.8` (blocks by default) | 94% precision, 73% recall; 15% of pull requests fail |
| with Claude Sonnet 5.5 as the second judge | 98% precision, 75% recall |
| at `fail_at = 0.9`, if raised | 100% precision, 45% recall; 12% of pull requests fail |
| Known duplicates found and scored ≥ 0.8 | 11 of 13 |
| Verdict store for the whole repository | about 1,900 pairs, 0.75 MB |

## Settings

All settings live under `[tool.dry-lint]` in `pyproject.toml` or in a `.dry-lint.toml` file. The defaults are the
measured thresholds above:

| Setting | Default | |
| --- | --- | --- |
| `include` / `exclude` | everything / tests, migrations, scripts | fnmatch over tracked paths |
| `neighbours` | 3 | candidates per changed function |
| `drop_below` / `report_at` / `drift_at` | 0.6 / 0.8 / 0.8 | judge thresholds: separate below, reported at, drifted at |
| `fail_at` | 0.8 | judged duplicates at or above this fail the run (`--fail-at` overrides it); raise it above `report_at` to make the band between them warn only |
| `reopen_margin` | 0.05 | how much closer a "separate" pair must get before it is judged again |
| `max_findings` | 10 | rows in the PR comment |
| `extractors` | `["python", "typescript"]` | `.py`, `.ts`, `.tsx`, `.mts`, `.cts` |
| `comparer` | `"tfidf"` | options `min_similarity` (0.5), `min_similarity_small` (0.3) under `small_function_lines` (6) |
| `judge` / `escalate` | `"auto"` / `"auto"` | Jev when `TYPESAFE_AI_API_KEY` is set; Claude Sonnet 5.5 on first scores in `[0.6, 0.91)` when `ANTHROPIC_API_KEY` is set (about half the false blocks); `escalate = "none"` turns it off |
| `store` | `"dir"` | `.git/dry-lint/verdicts/`, or `{ use = "s3", uri = "s3://bucket/prefix" }` |

A plugin slot takes a name, or a table with `use` and the plugin's options:
`comparer = { use = "tfidf", min_similarity = 0.45 }`.

## Lint

<img src="docs/assets/dry-lint-mark.svg" alt="" width="48" align="left">

Lint is what is left behind when you dry things. It carries a lint roller for picking up duplicated code.
`uv run --with pillow python scripts/make_assets.py` rebuilds the avatar, the mark and the banners from
[docs/assets/lint.png](docs/assets/lint.png).

<br clear="left">

## License

Apache 2.0. See [CONTRIBUTING.md](CONTRIBUTING.md) to work on dry-lint itself.

## Optional Dryer comparer

Install the `dryer` extra and select `comparer = "dryer"` or pass `--detector dryer` to use structural fingerprints.
TF-IDF remains the default. See [setup](docs/detectors.md) and the [gigaverse-backend comparison](docs/dryer-comparison.md).
