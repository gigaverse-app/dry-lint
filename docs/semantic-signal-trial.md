# Semantic signal trial

**Keep the production fingerprint unchanged.** Static API and argument information found some useful extra
pairs, but none of these simple additive variants reliably improved retrieval across both repositories.
The scripts are offline experiments, not registered runtime plugins.

## What was tried

Each variant adds one token family to the current `tfidf:2` tokens, with no extra weighting. The combined
variant adds all three. The index, similarity floors, cross-file restriction, three-neighbour budget,
suppression rules and mutual-nearest backlog scan are unchanged.

| Feature | Tokens | Boundaries |
| --- | --- | --- |
| API identity | `api:<canonical-import-or-local-function-path>` | Normalize lexical import aliases and relative imports. Do not infer instance types or execute imports. |
| Bound arguments | `bind:<callable>:<parameter>` and `bind:<callable>:<parameter><-<field>` | Only known, undecorated, non-variadic top-level functions in the inspected files. Bind AST argument values using `inspect.Signature`; normalize omitted defaults without evaluating them. |
| Direct field relationships | `flow:<field>->return` or `flow:<source-field>-><assigned-field>` | Direct expression dependencies only. No interprocedural analysis or propagation through local-variable assignments. Method names are not treated as data fields. |

The resolver skips common shadowing/rebinding cases, wildcard imports, invalid relative imports, unpacked
arguments and invalid bindings. It does not model Python's complete dynamic execution: monkey-patching through
other calls, runtime import hooks, re-exports and arbitrary `sys.path` layouts remain outside the trial.
Nested function bodies and annotations do not supply these extra signals. Existing baseline tokens are retained,
so this probe tests additive evidence, not complete invariance of the fingerprint to every alias or call spelling.

Each experimental comparer has a distinct `trial-<variant>-tfidf:1` identity. Its exported scores must not enter
the verdict cache under the production `tfidf:2` identity. The scripts do not write verdicts or change a repository.

## Method

- Baseline core: dry-lint `104933be3582fb26de87ccb15e1c84929b5d523a`; feature definitions frozen at `163f5ec`
  before pair judgments or per-variant retention results. Later portability fixes were checked for token equality
  over all 44,892 function/feature combinations; no corpus feature tokens changed.
- Backend: `22dfbe180c6704101658a088cc269a25fa9c82dd`, 5,057 implemented functions.
- AI: `78467d3e72508d355eb1fcf923f290a7a69980ef`, 9,907 implemented functions.
- Both worktrees were clean. Run with Python 3.14.7 and `PYTHONHASHSEED=0`; these repositories use syntax that older
  parsers may skip. Fit every index over the full repository, not just the sample.
- For each repository, take 12 pairs from the baseline scan and 8 from the union of variant scan pairs absent
  from the baseline scan. Exclude the prior 110 backend pair keys from both backend pools. Sort each pool by pair
  key, sample with `random.Random(20261105)`, then shuffle the 20 selected pairs using the same RNG.
- Codex judged the resulting 40 pairs with paths and code visible, but variant provenance, similarity scores
  and retrieval results hidden. Inspect surrounding ownership where needed. Freeze labels before scoring them.
  Backend: 6 positive / 14 negative; AI: 7 positive / 13 negative. Each novel stratum contained 2 positive pairs.
- Separately rerun the 110 old backend judgments (27 positive / 83 negative) as a regression set. Those labels
  already influenced earlier work and are not fresh validation.

A positive means at least one concrete concept or workflow should have one implementation, sometimes only a
shared portion of the two functions. Preserve caller-specific contracts during extraction. A negative includes
intentional adapters, separate domain rules and already-shared implementations.

## Results

Counts are retained known pairs. Higher positive retention and lower negative retention are better. `check`
means retrieval in either direction after filtering; `scan` means mutual nearest neighbours. Both keep the same
three-candidate budget. These are not estimates of repository-wide precision or recall.

| Variant | Backend fresh positives: check / scan (of 6) | Backend fresh negatives: check / scan (of 14) | AI fresh positives: check / scan (of 7) | AI fresh negatives: check / scan (of 13) |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 6 / 4 | 14 / 8 | 6 / 5 | 11 / 7 |
| API identity | 6 / 5 | 14 / 11 | 6 / 5 | 12 / 9 |
| Bound arguments | 6 / 4 | 13 / 9 | 6 / 5 | 12 / 11 |
| Field relationships | 6 / 5 | 13 / 7 | 6 / 5 | 11 / 8 |
| Combined | 6 / 5 | 13 / 11 | 7 / 6 | 13 / 13 |

| Variant | Old backend positives: check / scan (of 27) | Old backend negatives: check / scan (of 83) |
| --- | ---: | ---: |
| Baseline | 27 / 27 | 72 / 59 |
| API identity | 27 / 27 | 73 / 59 |
| Bound arguments | 26 / 26 | 72 / 59 |
| Field relationships | 27 / 26 | 73 / 56 |
| Combined | 25 / 24 | 71 / 54 |

The combined variant retrieves one additional AI positive in PR checking: repeated custom-campaign community
selection. It also loses two old backend positives, SWR-cache logic and clip eligibility. On the fresh scan
sample, combined positives rise from 9 to 11 while negatives rise from 15 to 24.

API identity brings past-event deep-link drift into the backend scan. In AI it swaps one real positive for
another: fleet-spawn orchestration enters, while active-showcase expiry leaves. Direct field relationships
improve the fresh backend scan but displace a privilege-policy pair from the regression scan. A high score is
not enough: a different neighbour can win the same limited slot.

| Functions receiving at least one extra token | Backend (5,057) | AI (9,907) |
| --- | ---: | ---: |
| API identity | 3,183 | 6,160 |
| Bound arguments | 1,133 | 3,089 |
| Field relationships | 1,508 | 2,650 |

## Findings worth acting on

Fresh positives included account-token refresh with divergent failure/cascade behavior; past-event deep links
with different universe handling; retry-header parsing; event timezone localization; Redis optimistic updates;
simulated-chat publication; duplicated analytics-demo event batches; fleet-spawn orchestration; custom-campaign
selection; bounded persona processing; and active-showcase expiry. These are findings, not backend/AI changes.

One especially instructive negative was frozen migration constraints compared with runtime constraints. The
historical module explicitly forbids evolving with the runtime: consolidating those would break its contract.
Other negatives were adapters already using a shared operation, fake versus real providers, and independent
status/lease policies with similar vocabulary. More lexical or static similarity cannot settle those ownership
questions by itself.

This is one assistant's judgment, not an independent reviewer panel. Sampling deliberately includes novel
variant output; labels can share functions or concepts, even though backend pair keys exclude the old sample.
Only 40 fresh pairs were judged. Do not use the mixed sample's positive fraction as a population precision
estimate or tune weights against it and then call it an untouched holdout.

## Reproduce

From a dry-lint checkout, against the pinned target checkout:

```bash
PYTHONHASHSEED=0 uv run python scripts/benchmark_semantic_signals.py \
  --root ../target-repository --out /private/semantic-trial --gold /private/gold.jsonl
```

On PowerShell set `$env:PYTHONHASHSEED='0'` before running the command on one line. Omit `--gold` to generate scan
pools before labeling. Gold uses the existing `GoldPair` JSONL format; the original sample and reasons remain
private because they contain repository code. Outputs include per-variant candidate snapshots and a versioned
`results.json` with corpus revision, parser version, feature coverage and optional gold retention.

Validate the experiment scripts with:

```bash
uv run pytest tests/test_semantic_signals.py --cov=scripts
uv run coverage report --include='*/semantic_signals.py,*/benchmark_semantic_signals.py' --fail-under=100
```

The trial is useful for comparing future ideas without quietly changing production scores. Keep production
unchanged until a subsequent experiment improves newly judged examples and preserves the regression cases
at the same candidate budget. No runtime dependency, model, service or repository-code execution is required.
