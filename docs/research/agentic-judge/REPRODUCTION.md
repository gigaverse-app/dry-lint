# Recorded replay and full-run boundary

From this directory, run `python3 reproduce.py`, `python3 native.py`, and `python3 audit.py`. The first recomputes the corrected nine-pair comparison from recorded submissions, source citations and policy; the second runs the original submission parser; the third checks integrity, links and public payload patterns. These are separate checks. `--output /tmp/agentic-results-NEW` writes CSV decisions and machine metrics without modifying the package. They require only Python 3.11+.

The original model is `claude-sonnet-5-5`, output cap 1024 per round, temperature and effort omitted (provider defaults), automatic tool choice, maximum six rounds and $0.15 per case. The original teacher may use pinned source tools; corrected v3 registers only `submit_verdict` and explicitly limits evidence to supplied source. It is not an identical-prompt ablation. Full rendered request objects and tool schemas are in [recordings](data/recordings.json). The exact initial requests are preserved; later teacher transcripts export only observable source calls/results and final submissions. Original event hashes identify the unexported transport archive, not a claim that sanitized bytes have the same hash.

Exact source acquisition, performed separately by a reader if desired:

```bash
git clone https://github.com/OpenHands/software-agent-sdk.git /tmp/sdk-source
git -C /tmp/sdk-source fetch origin 344ec8a9c30dff0a4ca200fc412510aad44e1bdc
python3 hydrate.py --repository OpenHands/software-agent-sdk --git /tmp/sdk-source --output /tmp/sdk-selected-NEW
```

Repeat with each URL and exact revision in [source pins](data/source-pins.json). `hydrate.py` does no network access: it verifies exact Git file bytes against the published source hashes. It never substitutes a nearby commit. The selected licensed source files already ship in compressed form, so acquisition is unnecessary for recorded replay.

A historical redistribution hold has a source-free [record](data/holds.json). For a reader who independently has permission and a local repository containing the exact commit:

```bash
python3 hydrate.py --repository Garsson-io/kaizen --git /your/authorized/local-repository --output /tmp/held-local-NEW
```

That exports the exact held snapshot to a local-only archive. It does not supply missing historical labels or authorize redistribution. This held corpus is not part of the nine-case selected replay.

Restore original runnable implementation/configuration into a new location:

```bash
python3 materialize.py --output /tmp/agentic-original-NEW --lab-root /tmp/agentic-lab-NEW
```

`product/` contains the original package and its `pyproject.toml`/`uv.lock`; `lab/` contains all experiment programs. The original full-evaluation commands, to run **only in a separately hydrated copy**, were:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src" python .lab-results/funded-rounds/analyze_funded.py --round 1
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src" python .lab-results/funded-rounds/round2/paired-baselines-repair-v3/analyze.py
```

Restore `lab/` to `.lab-results/` and product sources to `src/` in that isolated copy, and map `LAB_ROOT` with `materialize.py` to a root containing the original `jobs/` and `reports/` layout. The [full rerun manifest](FULL-RERUN.json) lists mandatory external inputs and exact location contracts. Complete source scopes and native inventories must match their original identities. The selected files alone cannot reproduce search omissions, discovery selection, round-one source joins or full teacher traces.

The dependency inventory is the archived lockfile plus the [original environment/specification](data/original/lab/EXPERIMENT.json.txt): Python 3.14 in the lab; Python 3.11+ for this portable replay; Git for pinned source access; the original dry-lint package (Pydantic and parser dependencies); Anthropic SDK only for separately authorized live execution. No live wrapper is exposed by this publication. Historical provider commands remain data in the archive. Any future live experiment needs caller-owned credentials, independent funding and a new output directory; it cannot reproduce a stochastic historical answer deterministically.

Public sparse study backgrounds are available by exact hash from the separate corpus repository: [pinned acquisition commands and limits](CORPUS.md). They are not missing simply because this kit does not duplicate them.
