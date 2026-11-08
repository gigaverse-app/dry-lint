---
title: dry-lint documentation
description: Find code that re-implements what your codebase already does, judge it, and say so on the pull request.
---

![dry-lint: one concept, one implementation](../docs/assets/readme-hero-light.svg)

# One concept, one implementation

Coding agents rarely copy and paste. They write *new* code for a job the codebase
already does: a second `truncate`, another pagination loop, each slightly different.
Line-based copy detectors miss these rewrites, and every rewrite is a chance to drift.

dry-lint finds functions in a pull request that look like they re-implement
something that already exists. A judge decides whether each pair really is one
concept, and the result goes back as PR annotations and one comment.

[Adopt it in a repository](../docs/adoption-playbook.md){ .md-button .md-button--primary }
[Add the GitHub Action](../docs/github-action.md){ .md-button }

```text
src/widgets/caption.py:1: preview_caption_text looks like src/text.py::shorten_text (drifted)
    judge 0.91; the two already behave differently; call the existing function;
    similarity 0.71; if they are different concepts, add
    `# dry-lint: distinct-from src/text.py::shorten_text`
```

## Try it locally, without an API key

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), open a
terminal in your Git repository, and run:

```bash
uvx --no-config --python 3.13 --from git+https://github.com/gigaverse-app/dry-lint dry-lint scan --judge none --limit 30
```

This lists look-alikes without calling a model or failing on findings. Python,
TypeScript and TSX work out of the box; see [TypeScript and Bun](../docs/typescript.md)
for monorepos.

**You bring your own keys.** dry-lint never provides API keys, models or judge
execution: judges run on the credentials your repository passes in, at your cost,
and without any it only lists look-alikes ([design](../docs/design.md)).

## Find your way

| You want to | Read |
| --- | --- |
| Block new duplicates on every pull request | [GitHub Action](../docs/github-action.md) |
| Accept existing debt once and track its cleanup | [Sweeps and the ratchet](../docs/sweeps.md) |
| Choose a judge, its cost and its thresholds | [Judges and presets](../docs/judges.md) |
| Find duplicated data models, not only functions | [Model duplication](../docs/model-duplication.md) |
| Compare against other repositories | [Workspaces](../docs/workspaces.md) |
| See what the measurements do and do not show | [Benchmark](../docs/benchmark.md) |
