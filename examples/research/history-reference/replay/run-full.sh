#!/usr/bin/env bash
# One replay process per repository; each resumes from its own output file.
# Usage: ROOT=/path/to/root PY=python bash run-full.sh   (needs ANTHROPIC_API_KEY in the environment;
# ROOT holds repos/<name> clones and full/in-<name>.jsonl inputs; dry_lint must be importable by $PY)
set -euo pipefail
ROOT=${ROOT:?set ROOT to the folder holding repos/ and full/}
PY=${PY:-python}
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$ROOT/full"
declare -A CAP=([litellm]=6 [zulip]=3 [saleor]=3 [prefect]=1 [netbox]=1 [openhands]=1)
for r in litellm zulip saleor prefect netbox openhands; do
  "$PY" "$HERE/replay.py" --root "$ROOT" "$ROOT/full/in-$r.jsonl" "$ROOT/full/out-$r.jsonl" \
    --max-usd "${CAP[$r]}" > "$ROOT/full/log-$r.txt" 2>&1 &
done
wait
echo ALL DONE
