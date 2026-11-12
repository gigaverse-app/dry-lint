# Repository configuration and reviewed exceptions

Keep dry-lint's project files together under the repository-root `.dry-lint/` directory.
**Commit this directory. Do not add it to `.gitignore`.**

```text
.dry-lint/
  config.toml       # Settings and repository-wide policy
  ignore.yaml       # Reviewed, durable pair exceptions
  feedback.json     # Review decisions tied to exact source evidence
  baseline.json     # Accepted function duplication debt, when initialized
  models.json       # Accepted model duplication debt, when initialized
  progress.json     # Generated progress metadata
```

Only create the files you need. Configuration is global: subdirectory configurations and ignore files
are not discovered. Paths in settings and exceptions are relative to the repository root, even though
their files live inside `.dry-lint/`. Verdict caches and temporary reports stay in their existing separate
locations; they do not belong in this committed directory.

## Settings

Put settings in `.dry-lint/config.toml` using the existing top-level keys, `[budget]`, `[[patterns]]`
and `[[policies]]`. For example:

```toml
preset = "jev"
include = ["packages/**/*.ts", "packages/**/*.tsx"]

[budget]
usd = 0.04
```

Legacy `.dry-lint.toml` remains readable. Keeping both it and `.dry-lint/config.toml` is an error,
even when their contents are identical. Either dedicated file takes precedence over `[tool.dry-lint]`
in `pyproject.toml`; existing pyproject-only configurations continue to work.

## Keep pair decisions out of source code

After reviewing both declarations, record independently owned concepts in `.dry-lint/ignore.yaml`:

```yaml
schema: 1

distinct:
  - symbol: packages/features/live/components/live-side-panel/LivePaneSwitcher.tsx::LivePaneOption
    from:
      - packages/components/designSystem/Badge/LiveRoleBadge.tsx::RoleVisuals
      - packages/components/designSystem/ColorSchemeToggle/ColorSchemeToggle.tsx::ColorSchemeOption
      - packages/components/designSystem/Dialog/Dialog.tsx::DialogScrollHint
    reason: >-
      A live panel destination; the others describe a role badge,
      theme choice and scroll hint.
```

Write `schema: 1` and `distinct:` once, then add entries to the `distinct` list.
Every entry needs a nonempty reason and exact
`path::Qualified.name` identities. Copy identities from the report; they are case-sensitive and are
not suffixes or glob patterns. Workspace reports include the repository prefix in their identities.

This example settles three symmetric pairs. It does not exempt any declaration from other comparisons,
and does not settle pairs among the three `from` targets. Exceptions apply to functions and model declarations
through the same detector rule, before judging. Filtered candidates retain the reason in reports.

These are durable decisions: they survive implementation edits, like inline `distinct-from`.
Use `dry-lint feedback dismiss` for a decision that must reopen when source evidence changes.
Use `[[patterns]]` in configuration for deliberate families, remembering that a family settles every
pair among its matched members. Inline `distinct-from` remains supported when the explanation belongs
beside the code.

Only `.dry-lint/ignore.yaml` is supported. Root-level `.dry-lint-ignore.*` names, `ignore.toml`
and `ignore.yml` are rejected with the supported destination instead of silently ignoring decisions.

Keep each decision in its own entry, with one target per line and a folded multiline reason when useful.
Preserve existing entry and target order. Agents should edit only the relevant entry, retaining comments
and avoiding whole-file rewrites or sorting. This keeps diffs small and reduces unrelated Git conflicts;
concurrent edits to the same entry can still need a manual merge. Duplicate YAML keys are rejected so a
merge cannot silently replace the `distinct` list or an entry's targets.

To migrate inline exceptions, add the same exact pairs and their explanation to the ignore file, then
remove the migrated directives from source. Stage both changes together and run the check. Do not move
unreviewed findings into the ignore file or broaden exact pairs to whole-file exclusions.

Staged checks read staged exceptions; an unstaged ignore cannot clear staged source. Changing the set
of declared pairs rechecks their endpoints, even without source edits. Deleting the file reopens those
endpoints. Ordinary detector limits still apply; use a repository scan for a wider audit.
The pre-commit hook also runs for metadata-only commits, including deletions. With no affected source or
changed pair declarations, staged checks remain idle and do not call a judge.

## Move existing files

Move each file that exists, preserving its contents. For example, in Bash:

```bash
mkdir -p .dry-lint
git mv .dry-lint.toml .dry-lint/config.toml
git mv .dry-lint-feedback.json .dry-lint/feedback.json
dry-lint config
dry-lint check --staged
```

Skip a move when its source does not exist. If a destination already exists, reconcile the contents first;
dry-lint rejects duplicate legacy/canonical locations instead of picking one. A move does not change path
resolution, pair evidence or accepted debt. Baseline, models and progress files already use this directory.
For settings in `pyproject.toml`, move just the dry-lint table contents, removing the `tool.dry-lint` prefix
from table headers. Leave unrelated project configuration in place.

New feedback is written to `.dry-lint/feedback.json`. Until migrated, an existing legacy feedback file
continues to receive updates, so its decisions are preserved. Both feedback locations together are an error.

Update any repository-specific workflow path filters or file-copy scripts to include the new locations.
The supplied bootstrap example watches both legacy and current configuration locations and ships only
generated baseline/progress files. Never delete `.dry-lint/` to reset an adoption experiment: preserve
configuration, ignore rules and feedback, and remove only the intended uncommitted generated files.
