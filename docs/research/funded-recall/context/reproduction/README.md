# PR110 context-study reproduction kit

This kit reproduces the recorded negative reporting result for two judging-input recipes. It includes original implementation, full licensed native Candidates and pinned Git source, exact provider inputs, sanitized answers and usage, scoped source assessments, and offline replay. It changes no experiment or production code.

**The comparison is each model before versus after.** Jev's question asks about one concept; Claude's asks about meaningful shared operations. This is not a controlled comparison of cross-model ability. At the fixed 0.80 reporting threshold, neither recipe recovered a report. On both useful novel R2 cases, Claude described a shared operation in both arms and scored 0.60 → 0.60. Mechanical window omissions are observable; they are not a demonstrated cause of the missed reports.

| Cohort | Pairing | New calls | Usage-derived cost |
|---|---|---:|---:|
| R1 source anchors | Six pairs × two models × baseline/treatment | 24 | $0.24912180 |
| R2 body coverage | Twelve novel pairs × four calls; four controls × two treatments | 56 | $0.45707392 |
| R2 control baselines | Eight exact historical answers, noncontemporaneous | 0 | Excluded from new spend |
| Total | 22 case pairs; 88 observations | 80 | $0.70619572 |

Costs use frozen study prices, not invoices. Source labels concern partial operations, not whole-function equivalence. R2 has two useful novel operations, six already-shared cases, three related cases and one separate case; controls add two positives and two separate cases. Already-shared and related cases remain nonbinary. Claude loses one historical control report, and Jev adds one positive label on a separate control below the reporting threshold. This is development evidence, not a pristine population holdout.

## Start here: offline, Python 3.11+, standard library only

Copy this directory, excluding any local-* directories. From the copied directory:

~~~bash
PYTHONDONTWRITEBYTECODE=1 python3 reproduce.py verify
PYTHONDONTWRITEBYTECODE=1 python3 reproduce.py metrics > /tmp/context-metrics.json
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -p test_kit.py -v
PYTHONDONTWRITEBYTECODE=1 python3 public_safety.py
sha256sum -c SHA256SUMS
~~~

No installation, credentials, network or target-code execution is needed. Verification recomputes verdict labels/scores, pair effects, token-derived costs, arm costs/latencies and synthetic $0.04 campaign admissions. It compares them with final scoring and the published CSV. The synthetic campaign is not an authenticated historical PR budget.

It validates 88 observation identities and 84 available rendered payloads, preserves all 22 numeric comparisons, rebuilds R2 windows and all available provider payloads, checks raw source hashes/spans, and rebuilds R1 snippet clipping/admission. Native parsing and complete R1 snippet selection are separate optional checks below. Four held Kaizen requests cannot be checked from public source-bearing payloads until hydrated.

## Inspect a case without decoding a large JSON dump

~~~bash
python3 kit.py inspect-case JCTX-R2-08b01303638b8b9d --kind claude --arm baseline --part answer
python3 kit.py inspect-case JCTX-R2-08b01303638b8b9d --kind claude --arm treatment --part answer
python3 kit.py inspect-case JCTX-R2-2f2794c9ff5b2164 --kind jev --arm treatment
~~~

The inspect-case command defaults to all details, organized as native body/signature/context, raw Git span, selected input and character maps, exact prompt/settings, and recorded answer. Use --part original|git|input|prompt|answer and --side new|existing|both. The git part prints the complete pinned file, including adjacent documentation. Jev's generated explanation is explicitly separate from its raw structured provider answers.

For exact canonical request bytes, first obtain a request ID:

~~~bash
python3 reproduce.py list
python3 reproduce.py inspect --request-id REQUEST_ID --part wire
~~~

The wire command writes stored bytes with no extra newline. Other parts give formatted JSON. Historical control wires are canonical reconstructions from the recorded request body/rendered input; their original on-wire serialization was not retained. All 80 fresh request wire hashes are retained; 76 fresh wire strings are public and four require hydration.

## Exact procedures, prompts and settings

R1 adds mechanically selected referenced imports, 12 preceding source lines, a 24-line endpoint prefix, and up to three exact-name reference sightings from at most 12 immediate-directory files. Excerpts clip at 1,200 characters and ordered whole snippets must fit a 4,000-character canonical payload per side. Jev retains its original 8,000-character prefix; Claude retains its full native body. No semantic helper-owner labels or gold operation locations enter the recipe.

R2 preserves short bodies. For bodies longer than 8,000 characters it selects four disjoint 1,600-character windows at fractions 0, 1/3, 2/3 and 1, with 200-character line-alignment slack and a 7,200-character rendered cap. Explicit markers disclose omissions. Native source context stays unchanged. Exact character/line maps are retained.

Models are jev-1.14.0 and claude-sonnet-5-5; Claude uses max_tokens=1024. Requests set no temperature, seed, tools, thinking, or other sampling fields. Jev has no output-token-cap field in the frozen typed-question request. One observation per arm, no retries or fallback. Executed study concurrency was eight (R1 one run, R2 two chunks), despite lower preparation defaults. Live playback uses concurrency one; it is not a latency reproduction.

The prompts.json file includes exact Jev questions/criteria, the complete Claude shared-operations template and Jev's mechanical reason table. Every available rendered prompt is in recordings.json.gz. Inspect original procedural implementations without executing them:

~~~bash
python3 archive.py list
python3 archive.py show lab/trace_followup.py
python3 archive.py show lab/coverage_round2.py
python3 archive.py show lab/root_trace_run.py
python3 archive.py show lab/export_final_evidence.py
python3 archive.py show lab/score_coverage_round2.py
python3 archive.py show src/dry_lint/typescript.py
python3 archive.py show uv.lock
~~~

The archive includes their local imports: extraction/cache modules, all dry_lint Python modules, parser/context implementations, request renderer, scoring code, budget harness, transport adapter and validator. Archived lab runners retain original paths and are documentation, not portable entrypoints. Portable entrypoints never import credential-reading lab top levels. Some historical Jev context strings contain inert lab paths; these remain byte-exact evidence and are never opened.

## Native extraction replay and source acquisition

Native parsing requires the exact frozen parser/model packages:

~~~bash
python3 -m venv local-env
local-env/bin/python -m pip install pydantic==2.14.2 pydantic-core==2.50.2 tree-sitter==0.25.2 tree-sitter-typescript==0.23.2
PYTHONDONTWRITEBYTECODE=1 local-env/bin/python native.py --out local-native
~~~

Installation is an explicit user action and may require network. If those packages are unavailable, the command reports the exact missing requirement; original code, lockfile, native Candidate and cached extraction-contract hashes remain archived. Do not equate stdlib request playback with full source extraction.

The native.py command parses all 42 licensed endpoints with the frozen extractor, verifies cached native-object identities where present, checks body/coordinate/declaration parity, and reproduces complete R1 anchor selection for ten licensed sides. Target code is parsed as data, never imported or executed. TypeScript extraction can omit export wrappers or synthesize a variable-declaration semicolon. Raw Git source and native Candidate remain distinct. Historical context fields and some empty structure hashes differ from re-extraction; the command reports differences and preserves original objects. Unexpected source, symbol, body or extraction identity mismatches fail visibly.

All pinned source files needed for public extraction are included, with licenses in licenses/. To acquire complete public repositories independently, print and inspect commands before running them:

~~~bash
python3 acquire.py > local-fetch.sh
cat local-fetch.sh
sh local-fetch.sh
python3 acquire.py --verify
~~~

Only the shell command fetches. Commands use public HTTPS Git URLs and immutable 40-character commits from source-pins.json, bare repositories and no checkout or target execution.

### Held Kaizen case

KZ-12db7f631134d1ce remains under the original redistribution hold. Its full source, context, rendered requests and Claude explanation prose are **not shipped**. Source-free model answers/scores/usage, source pin/path/spans, expected Candidate/function hashes and exact request hashes support all-case numeric replay.

An adopter can fetch immutable source locally and reconstruct the held requests using the public template and frozen extractor:

~~~bash
python3 hydrate.py
PYTHONDONTWRITEBYTECODE=1 local-env/bin/python hydrate.py --fetch --out local-kaizen
~~~

The first command only prints a plan. The second explicitly fetches and validates the commit, file hashes, native functions, Candidate and all four exact request hashes. To avoid fetching, use --git local-sources/Garsson-io--kaizen instead of --fetch. Hydrated source-bearing files remain in ignored local-* inputs; do not publish them. A failed hash check remains a failure, never an approximate reconstruction.

## Optional live playback: explicit user action only

The default is a dry run:

~~~bash
python3 live.py --case JCTX-R2-08b01303638b8b9d --max-requests 4 --budget-usd .25
~~~

After supplying your own TYPESAFE_AI_API_KEY and ANTHROPIC_API_KEY in your shell environment, this command makes four new requests:

~~~bash
python3 live.py --case JCTX-R2-08b01303638b8b9d --max-requests 4 --budget-usd .25 --execute --out local-live-new
~~~

Full original fresh-call plan, after hydration:

~~~bash
python3 live.py --round all --hydrated local-kaizen/requests.json --max-requests 80 --budget-usd 3
~~~

Add --execute --out local-live-all-new only to intentionally run it. Control baselines stay historical unless --include-historical is supplied; replaying them creates new observations, not historical evidence. No key files or shared account defaults are used.

Playback sends exact stored API bytes to fixed endpoints, disables redirects/proxy discovery, performs one attempt per request, reserves the whole selected plan before calls, bounds responses to 65,536 bytes by default, and stops on unknown usage or reservation overrun. Output directories must be new; recordings are never overwritten. Claude's server output cap is 1,024 tokens; Jev has a typed answer contract but no API output cap. Client byte limits cannot cancel server-side generation. Cost admission uses conservative UTF-8-byte token reservations at frozen rates (Jev $0.04/$0; Claude $2/$10 per million input/output tokens), not a hard invoice guarantee under changed prices. A provider-account spending limit is separate. New model answers may differ; live playback reproduces the request procedure, not a promise of identical findings.

## Files, provenance and limits

- recordings.json.gz: 88 sanitized observations; request identities; 21 complete licensed Candidates plus one held skeleton; contexts/maps; both frozen specifications; final source decisions and expected scoring.
- source-files.json.gz: 301 unique pinned source blobs, repository/path lookup and Git tree paths for exact anchor selection.
- implementation.json.gz: 74 original implementation/configuration files, each with its original SHA-256.
- prompts.json, published-paired-results.csv, source-pins.json, licenses/: readable contracts and attribution.
- SHA256SUMS, INVENTORY.json, VERIFICATION.md: complete public inventory and checks performed.

The final comparison explicitly uses scored-outcomes-independent-75ffc2e13f95a823.jsonl and its paired-results counterpart. Earlier unsuffixed independent outputs are not used. Root's reports/research-experiments/promotion/context-round2-source/coordinator-decisions.jsonl and existing-accepted-source-controls.jsonl are included with original provenance hashes and sanitized locator paths. Source adjudication remains evidence supplied to scoring, not something numerical replay can independently establish.

This reproduces selected-case extraction, transformations, exact requests and recorded scoring. It does **not** recreate the earlier whole-corpus TF-IDF nomination/selection campaign: full historical inventory, family graph, design-learning inputs and background stores are not included. Their selection rules and dependencies are preserved in original code/specifications. There is no claim that request playback alone reproduces those earlier stages, authentic PR funding, production-wide accuracy, invoices, or future model behavior.

Response export retains only model, stop reason, final answer text/typed answers and accounting token counts. Provider IDs, headers, diagnostics, thinking/reasoning blocks and unrelated usage details are excluded. Original raw-response hashes are provenance references; sanitized-response hashes bind included bytes. The safety scan inspects compressed contents and the held-source boundary, but is not a universal secret detector. Public source snippets retain repository licenses; the kit's dry-lint implementation is Apache-2.0. The build_export.py --lab-root PATH command documents the deterministic export from the original lab layout; readers do not need that layout for replay.
