# Reproduction, acquisition and limits

Run `python3 reproduce.py`, `python3 native.py` (dependency below), and `python3 audit.py` from this directory. `reproduce.py --output /tmp/recorded-results-NEW` writes CSV decisions and machine metrics into a fresh directory. Source code is data: no nominated target code executes. `--case CASE_ID` prints the complete representative source, rendered inputs and sanitized observations. The selected replay is portable outside the lab and does not rebuild rankings from a small replacement corpus.


`native.py` needs only Python 3.11+. It compiles the unchanged original region/tokenizer AST definitions, with a small source-record adapter, without importing the experiment's top-level code. It verifies all 25 frozen regions. The baseline IDF and neighbor competition are not recomputed on a small subset; use the exact full background for a full retrieval replay.

Every selected answer retains model, prompt version, output cap, request settings, exact rendered input, original response hash, observable answer and usage. Claude uses `claude-sonnet-5-5`, shared-operations, max 1024, reporting threshold .8; Jev uses `jev-1.14.0` and reuse-context-v3 for diagnostic comparison. Temperature/effort are omitted, retries are recorded as zero in the central request options. Provider answers are observations, not truth. Parsed verdicts are recomputed from sanitized responses; hidden reasoning and transport identifiers are omitted, without claiming the sanitized response hash equals the original.

The selected full source files already ship with license notices. To independently hydrate exact source from Git:

```bash
git clone https://github.com/BerriAI/litellm.git /tmp/litellm-source
git -C /tmp/litellm-source fetch origin fc1e47e580d9e3d2e8b46ad05a293a58ed0b8f1f
python3 hydrate.py --repository BerriAI/litellm --git /tmp/litellm-source --output /tmp/litellm-selected-NEW
```

All other allowed repository URLs and exact pins are in [source-pins.json](data/source-pins.json). `hydrate.py` makes no network call and fails on mismatched file hashes. For the source-free historical hold, independently authorized local hydration is explicit:

```bash
python3 hydrate.py --repository Garsson-io/kaizen --git /your/authorized/local-repository --output /tmp/held-local-NEW
```

That local-only export uses commit `4941b4a8928054910b5053255a99c84ac32bf3c2`; it is not included in the selected case replay and must not be redistributed. [Hold records](data/holds.json) exclude source-bearing prompts and answers. Private historical inputs remain local-only and are represented publicly only by anonymous aggregate/outcome data.

Public sparse backgrounds are separately available through [pinned exact-hash corpus acquisition](CORPUS.md). Preserve each extraction scope and source order; do not treat a different public revision as a replacement. A matching sparse background supplies document frequencies/competitors, not necessarily native source, historical labels or vector caches.

Restore original runnable code and configuration without executing it:

```bash
python3 materialize.py --output /tmp/original-NEW --lab-root /tmp/study-lab-NEW
```

Place restored `lab/` files under `.lab-results/` and product `src/`, `pyproject.toml`, `uv.lock` into an isolated study copy. The original programs refer to `LAB_ROOT/jobs/...` and `LAB_ROOT/reports/...`; materialization replaces that prefix with your explicit root. Restore the [full manifest](FULL-RERUN.json) inputs in that layout before using the original full-evaluation commands. Do not execute archived acquisition/provider commands implicitly, and never point mutation-producing evaluation programs at the frozen experiment directories.

Original full-evaluation commands (external inputs required; **not** equivalent to portable selected replay):

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src" python .lab-results/operation_blocks_capture_v1.py --repo litellm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src" python .lab-results/operation_blocks_capture_v1.py --repo openhands
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src" python .lab-results/funded-rounds/round2/full_source_audit.py
python .lab-results/funded-rounds/verify_report.py

```

The original locked package and experiment runtime specifications provide the dependency inventory: CPython 3.14 in the lab, dry-lint's locked Pydantic/parser environment, Git, and for CPU NumPy/ONNX Runtime/tokenizers at the recorded versions. Python 3.11+ suffices for the standard-library recorded-answer replay. Original provider request implementations are archived for audit; new physical judge execution would require separately authorized adopter-owned credentials and a new experiment/output location. No provider execution or refitting is needed to inspect these results.
