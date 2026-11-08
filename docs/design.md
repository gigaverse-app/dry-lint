# Design

dry-lint is a fixed core with four plugin slots. The core is the pipeline, the file formats, the rules for reusing
a verdict, and the reports. How functions are found, how they are compared, how a pair is judged and where
verdicts are kept are plugins ([plugins.md](plugins.md)).

| Concern | Core, fixed | Plugin, chosen in settings |
| --- | --- | --- |
| Finding functions | Which functions a change touched, from the git diff; qualified names | **Extractor**, one per language: splits files into functions, hashes their structure. `python` and `typescript` are built in |
| Proposing look-alikes | The nearest few per changed function, in other files; the rules that settle a pair | **Comparer**: indexes every function, returns nearest neighbours with a 0–1 similarity. `tfidf` is built in |
| Judging a pair | Which pairs need an answer; the thresholds; escalation | **Judge**: answers whether a pair is one concept. `jev` and `command` are built in |
| Remembering | The verdict record, its key and when it is reused | **Store backend**: get and put a record by key. `dir` and `s3` are built in |
| Reporting | One report, rendered as text, annotations, a PR comment, JSON, SARIF and a check run | none |
| Measuring | The gold-set format, `dry-lint bench` and its replay of recent commits | none |

## Adopters bring their own keys

This is a core invariant, and it is never traded for a feature. dry-lint is open source: it never ships, holds,
proxies or pays for an API key, a model, or judge execution.

- **Every judge runs on the adopter's credentials and at the adopter's cost.** A judge gets its key from an action
  input or from the adopting repository's environment, never from a default, a bundled value or a dry-lint
  account. With no key, dry-lint judges nothing: it lists look-alikes in the log and does not comment or fail.
- **No input defaults to a credential** except `github-token`, which is the run's own `github.token`, scoped to the
  adopting repository's own workflow run.
- **No code path calls a model on an account or endpoint dry-lint operates.** Judges call the provider the adopter
  chose (TypeSafe, Anthropic, Gemini, the adopter's own `claude` subscription or command) directly.
- **The only backend service dry-lint operates is the opt-out counter**, which receives anonymous counts (the repository
  as a hash of its name) without authentication: never credentials, code, names or paths.
- The static comparison viewer reads public GitHub source directly in the reader's browser. It has no backend,
  credential, model call or source upload. Private repositories receive GitHub links only.

Organizations that keep these keys as organization secrets are still the adopter: the secrets are theirs, passed
in by their own workflows. `tests/test_adopter_keys.py` guards the invariant.

## Pipeline

Every run goes through the same six steps, whatever plugins it uses:

1. **Extract.** The extractors turn every tracked file under `include`, and not under `exclude`, into functions:
   each a qualified name (`path::Class.name`), a line range and its code. Python and TypeScript/TSX are enabled
   by default ([TypeScript behavior and hash guarantees](typescript.md)). A file goes to the first extractor whose
   globs match it. The Python extractor leaves out declaration-only stubs (docstrings, `pass`, `...`, and a bare
   or argument-free `raise NotImplementedError`), so they do not use up neighbour or judge slots; abstract methods
   with an implementation, other exceptions, and methods that do work before raising stay in.
2. **Select.** A function is changed when the diff against the merge base with `--base` touches its lines. The
   base defaults to the remote's default branch (`origin/HEAD`), and an all-zero base, a branch's first push,
   falls back to it. Only changed functions are queried, so nothing that already existed is shown on a PR.
3. **Propose.** The comparer indexes every function and returns each changed one's `neighbours` (3) nearest in
   other files handled by the same extractor, above its own floor. Functions in the same file are excluded before the list is cut, so a file
   full of similar methods cannot crowd out neighbours elsewhere.
   Each pair also brings its **relatives**: the existing side's own neighbours, one hop away, as `lane =
   "relative"` pairs naming their `parent`. Fixing a duplicate touches the existing function, so without them
   its other copies surface one push at a time (in due#183, three copies of one recovery helper took three pushes).
   A changed existing side brings none: its look-alikes are proposed directly.
4. **Settle by rule.** Core consumes language facts from the existing extractor interface. A pair is `filtered`
   when both adapters identify the same convention in the same language (currently Python special methods),
   one is a recognized forwarding wrapper for the other in the same repository, one calls the other through a
   call the adapter resolved inside the file, both match a declared `pattern`, one carries
   `# dry-lint: distinct-from <qualified name suffix>`, or either carries `# dry-lint: ignore`.
   A forwarding body consists only of a same-owner method call with unchanged parameter arguments ("forwarding
   wrapper"). Any other resolved direct call settles as "one calls the other": both judges already label such a pair
   SEPARATE, and caller/helper pairs were the most common false report in agent review, so settling them first saves
   judge budget and keeps discovery slots for unrelated functions. Only file-local targets resolve: a method of the
   caller's own class through `self`/`cls`/`this`, or a Python module-level function the body does not rebind.
   Imports, other receivers, computed members and inherited dispatch stay with the judge, and inheritance alone never
   excludes a pair. Core does not interpret receiver names, base-module paths or naming syntax; unknown analysis
   never establishes an exemption. This one rule (`why_skipped`) serves every route: `pair()` records it as
   `filtered`, and discovery routes that ask for unseen pairs skip it before their cap, so no comparer re-implements it.
   Settled pairs remain in output with their rule. The extractor hashes both functions of every pair.
5. **Look up.** Each remaining pair's record is read from the store and kept if it still holds (below).
6. **Judge and report.** Pairs without a usable verdict go to the judge; scores in the escalation band go on to
   a second judge; every new verdict is stored; the report is built and rendered. Relatives come last, and only
   those whose parent was reported: one judge, closest first, within what the budget has left; the rest are left
   out, not counted as skipped, so a strict run stays complete.

`dry-lint check` runs all six. In CI they split into two jobs: `dry-lint detect` runs steps 1–4 and writes
`candidates.json`; `dry-lint judge` runs steps 5–6 from that file and writes `report.json`.

Discovery comparers may opt into generic resources owned by a single `Detector.candidates()` call. Core supplies construction/index hooks only; plugin code owns validation, exact keys and encoding. Prepared resources may be reused while mutable query state remains private. Concurrent calls have independent scopes, and no scope survives the call. See [plugin resource ownership](plugins.md#optional-run-resources).

## Two jobs in CI

The detect job checks out and reads the pull request's code. It needs no secrets and touches no store, so it is
safe on pull requests from forks. The judge job holds the judge's keys and the store, and reads the pull request's
functions only as text from `candidates.json`; it never checks out or runs them.

| Job | Trigger | Runs | Needs |
| --- | --- | --- | --- |
| detect | `pull_request` | `dry-lint detect --base $BASE --out candidates.json`, uploaded as an artifact | `contents: read` |
| judge | `workflow_run` of detect | `dry-lint judge --candidates candidates.json --report report.json`, then the comment and check run | the judge's key, `pull-requests: write`, `checks: write` |

- The judge job runs in the default branch's context, so it reads the settings and installs the plugins of the
  default branch, never ones a pull request names. A pull request's own `patterns` and `distinct-from` comments
  do apply in detect; they are in its diff and reviewed like code.
- `candidates.json` carries the run: repository, pull request and head commit. If the pull request has moved on
  by the time the judge finishes, its verdicts are still stored (they are keyed by structure hashes) and the newer
  run posts.
- Only a blocking finding (a judged duplicate at or above `fail_at`) fails: the check run is `failure` for one,
  `neutral` for findings that only warn, and `success` without findings. `--warn-only` makes it `neutral`.
- A repository without outside contributors can run `dry-lint check` in one job instead. The files are the same.

## File formats

Schema 15 adds optional operation-family findings and exclusion reasons to the main report. Family proposals
remain separate advisory assessments, never a clique of pair verdicts. Unknown members and excluded source
remain visible; applicable human-rule exclusions remain settled. Older reports load with empty family lists.
See [operation-family judging](operation-family-judging.md#native-campaign-configuration).

Campaign schema 3 adds exact source evidence independent of judge identity and a subscription marker to each
attempt. When either attempt is recovery, changing judge policy cannot charge the same source twice on a revision.
Older campaigns remain readable with their existing charges and failure barriers. Optional recovery judges use
policy-specific verdict key namespaces, leaving original pair keys and verdict record payloads unchanged.
The original judge owns the complete protected pass; only subsequently funded recovery work selects the optional
plugin. See [recovery judge configuration](production-discovery.md#optional-recovery-judge).

Schema 14 adds optional candidate `residual` scheduling metadata, defaulting to false for older files. It marks
recovery candidates after the complete adopter-configured discovery pass. It does not enter pair/context/exact
verdict identity: the question and source are unchanged. The independent campaign schema becomes 2, recording
which attempts borrowed residual capacity so their settlements cannot refill protected exploration credit.
See [experimental residual recovery](production-discovery.md#experimental-residual-recovery) for scope and the
tradeoff against future baseline evidence.

Schema 12 separates model ownership reviews from confirmed function duplicates in hook journals, commit trailers,
PR ledgers and backlog cleanup. Model reviews have their own resolved/dismissed counts and never enter the
anonymous prevention counter. A skipped model pass cannot settle those reviews or erase earlier model debt
retirement. Tallies include model coverage and spending; unknown prices remain unknown while known spending is
retained. Older ledgers and trailers remain readable as function findings; they did not track model source-review
tasks. Historical cost and coverage are not backfilled.

Schema 11 adds the independent model inventory to split detect/judge artifacts and model coverage, judging,
reviewed-debt counts and explicit source-review tasks to reports. Old artifacts remain readable; an action
requesting models rejects an artifact without a model inventory instead of silently claiming coverage.
Reviewed feedback writes independent schema 2, adding `accept` for source-reviewed model debt; schema 1
dismissals remain readable. Baselines retain schema 1 and the existing immutable exact-pair contract.

Schema 10 adds optional `Candidate.policies` and `Verdict.model_assessment`. Matched adopter rules carry
their definition digest, reason, priority, action and declared roles. They participate in `context_hash`;
changing a matched rule invalidates cached verdicts and source-bound dismissals. Empty policy lists preserve
legacy hashes. Model assessments retain independent atomic scores as coding-agent review evidence; a raw
score alone neither confirms duplication nor clears the candidate. See [model discovery](model-duplication.md).

Schema 9 adds optional `Function.analysis` (`LanguageAnalysis`: language, adapter version, method convention,
forwarding target and explicit override marker) and serializes the existing `bases` field. Earlier files remain
readable with unknown analysis. These facts participate in `Candidate.context_hash`, so stored verdicts and reviewed
evidence cannot survive a changed analysis contract or base reference. Extractors do not inspect imported bodies;
there are no hidden cross-file semantic dependencies to invalidate. Adding project-wide resolution must include
those dependency digests before its evidence can influence reuse. See [language adapter contracts](plugins.md#language-analysis).

Repository adoption baselines use an independent schema 1 and are reviewed policy, not cached verdicts.
They bind exact pairs and their structure/context hashes to a fixed detection and judging contract. Strict
checks accept only unchanged remaining entries; sweeps revisit all existing allowances before shrinking them.
See [sweeps and ratchets](sweeps.md) for the CLI, progress accounting and failure behavior.

Peer extraction snapshots use an independent schema and invalidation contract; see
[versioned function indexes](function-indexes.md). They preserve extraction data while candidate ranking and
verdict reuse stay in the consumer's existing pipeline.

New files carry `"schema": 14`. Findings deferred for cost carry `budget_deferred` and warn on PR checks. Baseline creation and advancement still require complete evidence. Schemas 1 through 13 remain readable with conservative cache defaults. Schema 9 adds
optional declaration kind/fields for the [model extractors](model-duplication.md); old function records default
to no declaration. Function indexes write independent schema 2 and preserve this metadata; schema 1 remains
readable subject to extraction-contract validation. Schema 8 adds
the report's optional `backlog`, the accepted baseline pairs a baselined check saw the change clean up, and the
sticky ledger's matching `backlog`. The report's is `null` when no baseline was checked, which makes no claim and
leaves the ledger's as it was; older ledgers read it as empty. Schema 7 adds the `relative` lane (below). Schema 6 adds
optional pair evidence to the sticky ledger: immutable source coordinates and the last reported judgment, never
function bodies. Old ledgers keep their counts but have no historical comparison until a pair is reported again.
The static viewer has its own schema 2 URL envelope (schema 1 remains readable). Schema 2 adds bounded same-file
helper references alongside the surviving function. It consumes source references and existing verdicts only;
it is not part of detection, judging or verdict reuse. See [comparison links](github-action.md#comparison-links).
Schema 3 adds
optional function `origin` using the existing `Run` contract. Workspace function identities include the repository,
while their paths remain repository-relative and their links use the source commit. Single-repository identities
and pair keys stay unchanged. Schema 4 adds bounded function `context`, a full-source `context_digest`, candidate
`consolidation` destinations, verdict-store `context_hash`, and finding `deferred` state. Old records default to
empty context, so they cannot satisfy a new contextual request. The models are in `models.py`, `store.py`, `report.py` and `ledger.py`.

| File | Written by | Holds |
| --- | --- | --- |
| `.dry-lint.toml` or `[tool.dry-lint]` | people | settings and declared patterns; committed |
| `# dry-lint: distinct-from …` | people | a decision on one pair, next to the code it explains |
| `candidates.json` | `detect` | `run`, `changed` (how many functions the change touched), `candidates` |
| `<key>.json` in the store | the judge step | one verdict record |
| `report.json` | `judge`, `check` | `run`, `judge`, `findings`, `filtered` |
| `<!-- dry-lint-ledger {…} -->` in the sticky | `python -m dry_lint.sticky --report` | a pull request's ledger: its tally, its last pushes and every pair a push reported, with what became of it ([ledger](github-action.md#the-ledger)) |
| `ledger/repository.json` in the store folder | the action, on a push to the default branch | the repository's ledger: its runs and its merged pull requests' ledgers, and since when it counts |
| `gold.jsonl` | people and labellers | one labelled pair per line ([benchmark.md](benchmark.md)) |

A **candidate** is both functions (name, owner, path, lines, code and structure hash), the `similarity`, the
`comparer` that measured it (`tfidf:1`), `similarity_reusable` (the metric's permission to reuse verdicts after a logic change), and `filtered`: the rule that settled it, or null.

A **verdict record** is named by the pair's key, the first 16 hex digits of the SHA-256 of both qualified names,
sorted, so a pair keeps its key whichever side changes:

```json
{"schema": 2, "key": "3c9a51f0d2e84b17",
 "pair": ["src/text.py::shorten_text", "src/widgets/caption.py::preview_caption_text"],
 "hashes": ["a41f0c2e9b7d1355", "77c0e1d2f3a4b5c6"],
 "comparer": "tfidf:1", "similarity": 0.71, "similarity_reusable": true,
 "verdict": {"label": "drifted", "score": 0.91, "behaves_differently": 0.86, "owner": "existing",
             "why": "both truncate at a word boundary; one appends an ellipsis", "judge": "jev",
             "judge_version": "reuse-v2", "second_opinion": null},
 "judged_at": "2026-11-03T10:12:00+00:00",
 "source": {"repository": "octo/repo", "pull_request": 1234, "head": "9f2c1e7", "base": "origin/main"}}
```

It holds hashes, never code. A **report** lists each proposed pair as a finding with its verdict (or none), whether
it came from the store, how many look-alikes its changed function has (`family`) and whether it is `reported`.

## Verdict store

The store is a cache of machine answers, not a reviewed file. Each record is its own object, so concurrent judge
jobs never conflict and a run reads only the records of the pairs it has. A record is reused when the answer
cannot have changed. Context and destination hashes must match before either rule below applies:

- **both structure hashes match**: nothing that matters changed; or
- **the verdict was `separate`, both records permit similarity reuse, the similarity comes from the same comparer version,
  and the pair is not more than
  `reopen_margin` (0.05) closer than when it was judged.** Changes that move two concepts apart cannot make them
  one.

The optional comparer attribute `similarity_reusable` defaults to false, and no built-in comparer sets it: TF-IDF
tokens and Dryer's normalization both leave out literals, so an edit such as `status == 'disabled'` to
`status == 'active'` can make two functions one concept without moving their score. Schema 1 records still load, but
only exact hashes reuse a verdict until a new record declares the policy. See [Dryer setup](detectors.md).

A `duplicate` or `drifted` verdict reopens on any logic change, because that change might be the fix, or more
drift. A verdict from another judge is never reused, and neither is one that this judging would not have given: a
second opinion from another second judge (or another version of it), or a first answer in the escalation band of a
run that escalates. Adding a second judge therefore re-judges the cached answers it would have seen, and pairs whose
escalation the budget could not afford are asked again on a later run. Until a run can afford to ask, the cached first
answer stays visible as provisional evidence in a coding-agent review task. The agent can repair the
duplication or record a source-bound dismissal without spending more judge budget. One from an older version of the same judge is, until
`dry-lint scan --refresh` asks again. Contextual judges always require the exact model/prompt version, even without
`--refresh`. Renaming or moving a function changes its key, so its pairs are judged again.

`dry-lint explain A B` shows all of this for one pair: the similarity and the tokens behind it, whether the
comparer proposes it, the rule that settles it, the stored verdict and why it is or is not reused.

Where it lives:

- **`dir`** (default): `.git/dry-lint/verdicts/` locally, never committed. In GitHub Actions, the judge job caches
  that folder; because the job runs in the default branch's context, every pull request shares its cache.
- **`s3`**: `store = { use = "s3", uri = "s3://bucket/prefix" }`, with `pip install dry-lint[s3]`.

Losing it only costs re-judging. For all of gigaverse-ai it would hold about 1,900 pairs in 0.75 MB.

Human decisions are different: they belong in the code (`distinct-from`) or in configuration (`patterns`), where
they are reviewed, versioned and visible to the next reader.

## Judging and escalation

A judge returns a verdict per pair: `label` (`duplicate`, `drifted` or `separate`), `score` (0–1, one concept),
`behaves_differently` (0–1), `owner` and `why`. The thresholds are core: below `drop_below` a pair is separate, at
`report_at` it is reported, at `fail_at` (`--fail-at` on the command line) it fails the run, and at `drift_at`
(0.8) on `behaves_differently` it is drifted.

A threshold means something only for the judges it was measured with, so the judges and the thresholds are chosen
together as a **preset** (`presets.py`, [judges.md](judges.md)): `jev+opus` (Jev, then Claude Opus 5.5 on Jev
scores in `[0.5, 0.91)`, failing at 0.55, and Jev's unescalated answers at its own 0.8: 98% precision, 85% recall
within $0.04 a pull request), its subscription twin `jev+claude-code`, the cheaper `jev+sonnet` and
`jev+claude-code-sonnet`, `jev+codex`, `sonnet`, `claude-code`, `jev` (failing at 0.8: 94%, 73%) and `none`.
`preset = "auto"` picks by the credentials present; explicit settings win over the preset's. `escalate` sends
first scores in its band to the second judge, whose answer replaces the first; the record stays under the first
judge's name with `second_opinion` set, and is reused only by runs with that same second judge. Each run's judging is bounded by a budget
(`budget.usd` for priced judges, `budget.subscription_calls` for subscriptions; riskiest pairs first) and every
report states the preset, the judges, the thresholds and the estimated cost (`costs.py`).

## Reports

Every view renders the same `report.json`, so the terminal, the annotations, the PR comment, SARIF and the check
run list the same findings in the same order: drifted first, then by score.

- `text` for the terminal, `github` for workflow annotations, `markdown` for the one PR comment (marked
  `<!-- dry-lint -->`, at most `max_findings` rows, settled pairs folded), `json` for scripts and agents, `sarif`
  for code scanning, and `check-run` for the body of a check run that fails only for a blocking finding.
- Blocking findings come first and are labelled. Comments link both functions to the analyzed revision, count
  findings separately from changed functions, and fold score evidence and pair-specific suppression guidance.
  The Action's effective blocking/override note precedes the findings; a clean result means no pair met the
  configured report threshold, not proof that the repository has no duplication.
- A relative judged a duplicate at `report_at` is shown on its parent ("fixing this touches X, which also looks
  like Y: consolidate them in the same change"), never as a finding of its own. It never blocks, an accepted
  baseline does not hide it, and the pull request ledger does not count it.
- Without a judge, the comment does not list unjudged pairs; it says no judge is configured. Annotations and the
  terminal still show them.
- A judge's reason is untrusted text: an LLM judge read code from the pull request. It is flattened to one line,
  capped at 300 characters and escaped wherever markdown shows it.

## Why TF-IDF is the default comparer

The spike compared this fingerprint with two code-embedding models on 7,195 functions
([benchmark](benchmark.md#detector-tf-idf-and-embeddings)):

- **Both find candidates.** Their top pairs overlap only about 40%, and each found real duplicates the other missed.
- **Embeddings rank better.** They separated real duplicates from false alarms better (AUC 0.86 against 0.66), but
  their candidate lists were no cleaner.
- **Embeddings cost more.** TF-IDF needs no model and indexes the repository in seconds on a CPU. The smaller
  embedding model is 311 MB and takes about 80 minutes on a CPU, or a GPU.

TF-IDF keeps the detector stateless and fast enough for pre-commit, and leaves ranking to the judge, which reads
the code. An embedding comparer is a plugin away; `dry-lint bench --comparer` measures it on the same gold set.

### The built-in fingerprint

The Python extractor gives each function **behaviour tokens**, a bag of what it does:

- `call:` for each name it calls;
- `attr:` for each attribute it touches;
- `w:` for each word in its identifiers, split from snake_case, camelCase and acronym boundaries (`parseHTTPHeader`), with generic words dropped;
- `key:` for keyword arguments, literal mapping keys and command option names;
- `fn:` for the words in its own name, counted twice;
- `ctl:` for loops, `try` blocks and `await`s.

Annotations, arbitrary string prose and enclosing class names do not contribute tokens. Class names used in
executable code do: `HTTPInvoiceClient()` contributes `http`, `invoice` and `client`. These choices were measured
against judged backend candidates; adding every available signal lost real duplicates ([results](benchmark.md)).
The built-in extractor and comparer are version 2 so cached similarities from version 1 are not compared after
logic changes. Unchanged-logic verdicts remain reusable.

Its **structure hash** is the syntax tree with docstrings, annotations, decorators and the function's own name
removed, and every name the function binds itself renumbered in order of first use (`v0`, `v1`, …). Comments,
formatting and renames do not change it; any change to the logic does. Only the functions in a pair are hashed.

`comparers.py` is TF-IDF over those tokens in plain Python, with an inverted index: sublinear term frequency,
smoothed IDF and L2 normalisation, dropping tokens found in more than 30% of all functions. Its floor is 0.5, or
0.3 for functions shorter than six lines, because tiny helpers share few tokens and their real twins score lower.
On gigaverse-ai (about 10,000 functions) a whole `check` takes about 4.4 s.

## Production discovery and reviewed feedback

Schema 7 adds the `relative` lane and a candidate's `parent`; files from schema 6 read unchanged.
Schema 5 adds candidate lane, run session/tree identity, exact-source record evidence and campaign reporting.
`balanced` adds a stateless exploration index to the baseline detector and a transactional SQLite admission ledger
beside verdicts. Model verdicts remain in the existing cache; reviewed fix/dismiss decisions live separately in
`.dry-lint-feedback.json`. Source changes reopen reviewed dismissals. See [production discovery](production-discovery.md)
for accounting, failure, local/CI storage and feedback contracts.
