# Contributing

Install Python 3.11+ and [uv](https://docs.astral.sh/uv/), then:

```bash
uv sync --locked
uvx pre-commit install
uv run ruff check .
uv run ruff format .
uv run pytest -q --cov
uv build
```

When changing the action installer, also run `uv run python scripts/test_action_install.py` with Bash and uv
on PATH. It performs real installs in temporary Python and Node repositories; CI runs it on Linux, macOS and
Windows. The ordinary pytest suite stays offline.

- **Tests use real objects.** A temporary git repository stands in for a pull request; judges run as real
  subprocesses, or against `httpx.MockTransport`. New code needs full coverage, and a bug fix needs a test of the
  invariant it broke.
- **Thresholds and judge wording come from measurements.** If you change them, re-measure and update
  [docs/benchmark.md](docs/benchmark.md). If you change the Jev questions, bump `PROMPT_VERSION`.
- **Stateful rules are locked by model-based contracts.** `contracts/campaign/campaign.qnt` is the specification of
  the discovery campaign ledger (admission, settlement, revisions). [pytest-quint-connect](https://github.com/gigaverse-app/pytest-quint-connect)
  replays histories Quint generates from it against the real `CampaignStore`, and planted mutants prove the check can
  fail. Run it with `uv sync --group quint` then `uv run pytest -c contracts/quint.ini contracts --quint-require-complete`
  (needs Node.js 22+). After editing the model, run `uv run pytest-quint-connect codegen contracts/campaign/quint-connect.json`
  and commit the regenerated driver base. Change the model only when the ledger's intended rules change.
- **CI runs only what a change can affect.** [pytest-selective](https://github.com/gigaverse-app/pytest-selective)
  plans whole lanes from [.github/test-lanes.json](.github/test-lanes.json) before any runner starts: `tests`,
  `counter`, `viewer`, `contracts`, `package` (consumer installs) and `dogfood`. A documentation-only pull request runs the
  workflow lint and the required `Validation gate`, and no tests. A lane's inputs are the files its jobs execute
  or read; when a test starts reading a new non-Python file, add it there. Lockfiles, `pyproject.toml` and the
  lane file run every lane; manual runs and pull requests labelled `test:full` run everything. The gate accepts a
  skipped job only when the plan succeeded and said its lane was unaffected, and `ci-esta check-workflow` in
  `lint-ci` keeps the job conditions, the gate and the lane file in agreement. The optional Dryer comparer runs in
  its own `dryer.yml` workflow, outside the gate.
- **Assets.** Regenerate them from `docs/assets/lint.png` with `uv run --with pillow python scripts/make_assets.py`, then
  `uv run --with playwright==1.58.0 python scripts/render_png.py`.
