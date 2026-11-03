# Contributing

Install Python 3.11+ and [uv](https://docs.astral.sh/uv/), then:

```bash
uv sync --locked
uv run ruff check .
uv run pytest -q --cov
uv build
```

- **Tests use real objects.** A temporary git repository stands in for a pull request; judges run as real
  subprocesses, or against `httpx.MockTransport`. New code needs full coverage, and a bug fix needs a test of the
  invariant it broke.
- **Thresholds and judge wording come from measurements.** If you change them, re-measure and update
  [docs/benchmark.md](docs/benchmark.md). If you change the Jev questions, bump `PROMPT_VERSION`.
- **Assets.** Regenerate them from `docs/assets/lint.png` with `uv run --with pillow python scripts/make_assets.py`, then
  `uv run --with playwright==1.58.0 python scripts/render_png.py`.
