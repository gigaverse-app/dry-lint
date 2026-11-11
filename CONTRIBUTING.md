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
- **CI runs only what a change can affect.** [CI-esta](https://github.com/gigaverse-app/ci-esta)'s `plan-work`
  plans whole lanes before any runner starts: `tests`, `counter`, `viewer`, `contracts`, `package` (consumer
  installs) and `dogfood`, the names the jobs' conditions read. A change selects a lane through what its jobs run:
  the tests that import it ([pytest-selective](https://github.com/gigaverse-app/pytest-selective) for Python, Bun's
  module graph for `counter` and `viewer`), and the scripts and actions the job executes. A documentation-only
  pull request runs the workflow lint and the required `Validation gate`, and no tests. When a test or a script
  starts reading a file by path, declare it next to the reader (a `<test>.gv-dependency.yaml` sidecar, which
  `pytest-selective audit --write-declarations` writes, a scoped `.gv-dependencies.yaml` shared rule,
  or a `# gv:test-dependency: PATH` comment). `tests/.gv-dependencies.yaml` owns the repeated extractor
  imports: add a reader to the matching rule instead of copying the module list. Keep script-specific
  inputs scoped to their actual readers and preserve `content` versus `import`; a broad test glob would
  silently add dependencies to unrelated tests. `ci-esta lanes
  --base origin/main` shows what a change would run and why. [.github/test-lanes.json](.github/test-lanes.json)
  holds the one rule the graphs cannot see: `dogfood` judges every changed source file. Lockfiles and
  `pyproject.toml` run every lane; manual runs and pull requests labelled `test:full` run everything. The gate accepts a
  skipped job only when the plan succeeded and said its lane was unaffected, and `ci-esta check-workflow` in
  `lint-ci` keeps the job conditions, the gate and the lane file in agreement. The optional Dryer comparer runs in
  its own `dryer.yml` workflow, outside the gate.
- **Assets.** Regenerate them from `docs/assets/lint.png` with `uv run --with pillow python scripts/make_assets.py`, then
  `uv run --with playwright==1.58.0 python scripts/render_png.py`.
