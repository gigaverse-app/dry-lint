# Offline mining audit tools

These opt-in research scripts cache exact native extraction and prepare source audits.
They do not run providers, read credentials, accept gold, change production behavior or
choose a paid shortlist. All datasets, source repositories, observations and output
paths are supplied by the caller. Private data can live in a separate checkout such
as `dry-lint-goldens`; nothing from it is bundled here.

From a dry-lint checkout with the ordinary development environment installed:

```sh
PYTHONPATH=scripts:src uv run python -m research_mining.demo --out-dir /tmp/mining-demo
```

Choose a fresh output directory. The demo creates two tiny synthetic functions in a
local Git repository, complete `packets.jsonl`, `requests.jsonl`,
`observations.jsonl`, and a relative-path `repositories.json`. Its two invented
reviewer observations disagree; no model runs. It invokes the real CLI cold and
warm and checks equal audit rows and complete observation matching. Inspect those
files for a complete runnable example of the independent schema-1 research formats.

Run directly on external inputs:

```sh
PYTHONPATH=scripts:src uv run python -m research_mining \
  --packets /tmp/mining-demo/packets.jsonl \
  --repositories /tmp/mining-demo/repositories.json \
  --requests /tmp/mining-demo/requests.jsonl \
  --observations /tmp/mining-demo/observations.jsonl \
  --reviewers alpha beta --hints --cache /tmp/mining-demo/cache \
  --out /tmp/mining-demo/another-audit.json
```

On Windows use `;` instead of `:` in `PYTHONPATH`, setting the environment variable
with your shell's syntax. An existing interpreter with dry-lint's dependencies also
works; `uv` is not part of the tool. Repository paths in the mapping resolve relative
to the mapping file. Outputs must be new paths. Requests and observations are
optional; without them observations remain unknown. Malformed JSONL fails the
command rather than silently losing records. Valid JSON values with invalid packet
envelopes (including scalar/null rows, missing/non-string/duplicate IDs), candidates,
or source-proof lists remain intact in failed source-validation rows with errors.
Final evidence output uses an exclusive atomic hard link to complete temporary
bytes; concurrent publishers cannot overwrite the winner. The output filesystem
must support same-directory hard links; unsupported filesystems fail instead of
falling back to replacement. Run the synthetic tests with:

```sh
uv run pytest -q tests/test_research_mining.py
```

## Source and extraction contract

Each packet supplies an ID, repository, full 40-hex SHA-1 commit, production-shaped
`candidate`, and exactly one `source_proofs` entry per endpoint identifying its
`source_id` and complete `file_sha256`. The tool reads blobs from that exact commit
in the supplied local Git repository, with replace objects disabled. It never
executes repository code, follows branch names, fetches data or substitutes a nearby
function. Both full files must parse, both native IDs must be unique, and bodies,
coordinates, supplied structure hashes, bases, declarations and supplied language
analysis must agree. Missing legacy structure hashes remain missing. Cross-repo
endpoint origins are unsupported and remain failed/unknown.

The disposable trusted-local cache binds repository, pin, path, full-file SHA256,
all installed dry-lint Python source, all these tooling modules, extractor versions
and defaults, exact Python runtime/platform, and tree-sitter, TypeScript grammar,
Pydantic and Pydantic Core versions. The format has its own schema; changing it
requires a bump. Tokens and calls survive replay even though production artifact
serialization excludes them. Reconstructed objects isolate caller mutation.
Unique temporary files, flush/fsync and atomic replacement let concurrent exact
writers converge. Truncation, identity/checksum mismatch and invalid payloads cause
re-extraction; readers never delete a potentially repaired concurrent entry. A
crash may leave an ignored `.tmp` file. The cache is neither an adversarial artifact
format nor an authenticity proof: a malicious writer can recompute a checksum.
Keep it local, disposable and writable only by trusted users. Source reads and
endpoint checks still happen on warm runs.

This tool does not rebuild frozen backgrounds, validate background token counts or
change retrieval. An existing verifier integrating `ExactCache.extract` must retain
all its background digest/pin/unique-ID/native-token/body/context checks. This audit
CLI checks endpoint provenance only. Candidate context may contain composite or
multi-file digests: it is preserved in request identity, never replaced with an
owning-file hash, and dependency closure remains an explicit audit limitation.

## Expected requests and observations

A request-manifest row is `{"id": packet_id, "identity": {...}, "request_key": ...}`.
The identity contains `schema: 1`, a `kind` matching an explicit reviewer, and every
field returned by `source_binding(packet, candidate, validated_source_checks)`.
Those bind repository, revision, full serialized candidate (including orientation
and similarity), source evidence, context hash and both exact source files. It also
requires `judge`, `version`, `model`, `prompt_version`, exact `rendered_input`,
`max_output_tokens` (positive integer or explicit null) and `request_options`.
Put every other request-affecting option, endpoint identity, tool definition and
sampling setting in `request_options`; never include secrets. Any extra identity
fields also participate in exact matching.

`request_key` is SHA256 of `canonical(identity)` from `exact_cache.py` (sorted ASCII
JSON with default separators, NaN disallowed). Observation rows carry the same full
identity and key plus `verdict: {"label": "separate|duplicate|drifted", "why": "..."}`
and optionally `error`. Missing requests, duplicate reviewer requests, missing or
duplicate observations, errors and unequal identities stay unknown. All raw
manifest and observation records are preserved, including unjoined records. Each
queue observation points to input indices for inspection. No automatic retry or
provider action follows an unknown result.

The caller supplies the expected request manifest from its actual runner. These
scripts do not render canonical judge prompts or verify that a declared prompt
matches a provider's request. Importers must preserve the complete request contract
and explicitly version request-affecting changes. This independent format is not a
drop-in reader for production or historical prototype judge caches. Exact packet
or source evidence alone is **not canonical judge-cache validation**, and a matched
research observation is not confirmation that a runner reused it or a model stayed
immutable upstream. Costs, usage and spend accounting are outside this tool.

## Retention and navigation

One row remains for every input packet, in input order, including duplicates,
negative labels, unknown, deferred, filtered and disputed states. The complete
original packet is retained verbatim as JSON data. New `audit_status` is always
unknown, `gold_label` null and `accepted_gold` false. Original acceptance claims
remain only inside the original packet. Agreement on separate requires a source
contract audit; subtype disagreement remains visible too. Operation ranges,
ownership and caller decisions stay empty for a human source audit.

Priority 0 marks complete boundary disagreements, 1 other complete positive
observations, 2 complete separate agreement and 3 incomplete evidence. This is a
review navigation field, never an acceptance/exclusion gate or a paid selection
rule. Optional lexical hints locate stripped-line matches inside source-checked
endpoints. They can be boilerplate, comments or unrelated policy. No match is not a
negative, and no match establishes a semantic operation, owner or caller contract.

## Measurement limits

The upstream selected-development experiment measured about **17.5x warm
extraction-stage** improvement; cold caching was slower. That timing excluded Git
reads, frozen-background decoding/indexing and caller-context assembly. It is not
a benchmark of this portable patch and establishes no recall, provider-cost or
end-to-end gain. A Jev >= 0.5 gate lost 11 of 20 accepted development positives;
no score or lexical gate is implemented. The synthetic demo verifies equality and
cache hits, not performance, recall, statistical independence or gold quality.
