#!/usr/bin/env bash
set -eo pipefail

# Ignore the caller's uv configuration; publishers and consumers share our locked extraction versions.
uv venv --quiet --no-config --allow-existing --python "${DRY_LINT_PYTHON_VERSION:-3.13}" "$RUNNER_TEMP/dry-lint-venv"
locked="$RUNNER_TEMP/dry-lint-requirements.txt"
# The anthropic extra too: balanced, the recommended preset, judges with the Anthropic SDK, at its locked version.
uv export --quiet --no-config --project "$GITHUB_ACTION_PATH" --frozen --no-dev --no-emit-project --no-hashes \
  --extra anthropic -o "$locked"
# Bash 3.2 (macOS) has no mapfile. Accept pasted Windows line endings and blank lines too.
extra=()
while IFS= read -r package; do
  package="${package%$'\r'}"
  if [[ ! "$package" =~ ^[[:space:]]*$ ]]; then
    extra+=("$package")
  fi
done <<< "${PLUGINS:-}"
uv pip install --quiet --no-config --python "$RUNNER_TEMP/dry-lint-venv" -r "$locked" --constraint "$locked" \
  "$GITHUB_ACTION_PATH" "${extra[@]}"
bin="$RUNNER_TEMP/dry-lint-venv/bin"
if [[ -d "$RUNNER_TEMP/dry-lint-venv/Scripts" ]]; then
  bin="$RUNNER_TEMP/dry-lint-venv/Scripts"
fi
echo "$bin" >> "$GITHUB_PATH"
