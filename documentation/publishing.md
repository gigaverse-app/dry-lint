# Build and publish these docs

The repository Markdown is the source. `mkdocs.yml` explicitly lists published
guides; `documentation/hooks.py` adds them to the build without copying prose.
Research plans, raw results, work in progress and data files are not added to the
site. Links to unpublished source files remain GitHub links. Broken local links
fail the build.

```bash
uv venv .venv-docs --python 3.13
uv pip install --python .venv-docs -r documentation/requirements.txt
uv run --no-project --python .venv-docs mkdocs build --strict
uv run --no-project --python .venv-docs python documentation/check_site.py
uv run --no-project --python .venv-docs mkdocs serve
```

The **Documentation** workflow builds every PR and main revision with the same
pinned documentation dependencies as Read the Docs. Review its site artifact
before merging.

## Read the Docs setup

Import `https://github.com/gigaverse-app/dry-lint` into Read the Docs Community,
using project slug `dry-lint`, English, `main`, and `.readthedocs.yaml`.
Connect the GitHub integration so pushes rebuild automatically, and enable
pull request previews. Keep `latest` as the default until a published release
contains this configuration; then activate that release and choose `stable`.
Older tags without the configuration cannot build this site.

Verify a successful build, the homepage, search, a guide, `sitemap.xml`, and the
page's canonical URL after publishing. The canonical base comes from
`READTHEDOCS_CANONICAL_URL`; local builds fall back to the public site. Material
generates page titles, descriptions, canonical links and a sitemap. The override
adds Open Graph and social summary metadata without analytics.

## Search measurement

The override in `documentation/overrides/main.html` carries the maintainer's
public Google Search Console ownership tag, shared with the other gigaverse-app
documentation sites. After the first deploy, verify the URL-prefix property
`https://dry-lint.readthedocs.io/en/latest/` and submit its `sitemap.xml`.
Verification and sitemap submission do not guarantee indexing or ranking.

## Keep the site useful

Publish instructions, configuration and safety boundaries, and evidence that helps
a reader decide. Group pages by the reader's task: getting started before reference,
contributor maintenance in its own section. Do not publish research plans,
per-run result dumps, CSV or JSON data, or `docs/work-in-progress/`; link the raw
evidence from the guide or case study that interprets it. Keep the explicit
`published_sources` list curated, and check incoming links when removing a page.

## Branding

`scripts/make_assets.py` renders every brand file from the mascot art in
`docs/assets/lint.png`, including the 256 × 256 `icon.png` favicon;
`scripts/render_png.py` renders `social-preview.png`. `mkdocs.yml` maps the logo,
favicon, banner and social card roles to those files under their existing names
(`extra.brand`), because adopters' pull request comments hot-link the sticky banners
from `main`. Never rename or move a file in `docs/assets/`. Content hashes in the
site's image URLs refresh cached artwork after an update.
