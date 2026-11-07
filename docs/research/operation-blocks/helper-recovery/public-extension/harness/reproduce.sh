#!/usr/bin/env bash
set -euo pipefail
cd /home/researcher/dry-lint-round/jobs/public-pin-regressions
.lab-results/run-python .lab-results/freeze_inputs.py
.lab-results/run-python .lab-results/materialize.py
.lab-results/run-python .lab-results/checks.py
.lab-results/run-python .lab-results/verify_contract.py
.lab-results/run-python .lab-results/blocks.py
.lab-results/run-python .lab-results/cpu.py
.lab-results/run-python .lab-results/final_check.py
.lab-results/run-python .lab-results/summarize.py
