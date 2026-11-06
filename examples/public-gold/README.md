# Public operation gold: two active families

This purposive development panel contains **four accepted rows in two families**: two duplicate-operation
positives and two real surviving negative controls. Labels concern the stated operation, not equivalence of
the enclosing functions. Independent review was by a separate model source reviewer, **not a human**;
the curator reconciled it with the mining evidence. No target code or behavioral tests were executed.
Agent authorship remains uncertain. A merge, AI product, bot comment or agent review does not establish who
wrote a change. These rows make no population precision, recall or prevalence claim.

| Row | Family / lineage | Label and scope |
| --- | --- | --- |
| `G02-01-before` | `t3code-clipboard-feedback` / T3 #1006 | Duplicate clipboard write and temporary feedback operation; timer restart, missing input and unmount differences remain explicit. |
| `G02-01-after` | same | Separate surviving PlanSidebar and MessageCopyButton operations, delegating to `useCopyToClipboard`. |
| `G04-03-before` | `G04-03` / OpenCode #57604 | Duplicate request normalization helper operation; Promise `make` as a whole is not labeled duplicate. |
| `G04-03-after-generate` | same | Separate surviving Promise generate adapter and Effect generate operation; shared normalization owner. Deleted `llmRequest` is never an after negative endpoint. |

Before uses the **actual merge first parent**. OpenCode's PR base differs from that first parent; both remain
recorded in `pins`. After uses the actual merge. The OpenCode after review cited PR head; complete endpoint
file hashes at merge equal those reviewed at head, and the selected generate spans are within the reviewed
spans. This exact transfer is recorded in the row. Before/after corpora are separate.

`contrast-controls.jsonl` retains the clipboard/download contract contrast. Its nested callbacks belong to
the same extracted component, so it is excluded from the active distinct-function panel.
`source-related.jsonl` separately retains four source-related positives:

- OpenCode decoder **bindings**, with live consumers verified, but no extracted function identity. The
  package does not substitute `parseJSON` or invent an extracted decoder function.
- SDK callback composers, where whole-tree name/import review found the factory copy unused. This is a
  dead-code source duplicate, excluded from the active panel. Dynamic or outside consumers are unproven.
- T3 settings secret materialization regions within one function.
- LiteLLM URL parameter regions within the same `run_server` function, outside `enterprise/`.

`unknown.jsonl` retains the two uncertain T3 secret-input/credential-selection cases and the OpenCode record
predicate disagreement (miner: drifted; independent reviewer: separate because arrays differ). Unknown
is not a negative. Supplemental files are not part of the four-row active benchmark.

The `t3-history-development`, `breadth-history-development` and `python-history-development` cohort names
remain distinct. Families and PR lineages must stay together in any split. No row is added to, or used to
recalibrate, the six prior legacy/mined/fresh experimental cohorts. `prior-inventory-check.json` preserves
the available prior E02 endpoint inventory and its digest; endpoint-pair comparison found no overlap.
This does not assert an exhaustive search for transitive clones.

## Portable source and review evidence

All package file references, including references inside review files, resolve **from this directory**.
No lab path is required. Each side retains its exact source coordinates, immutable GitHub URL, full-file
SHA-256, computed Git blob SHA-1 and exact snippet SHA-256. `sources/*.json.gz` preserve complete UTF-8
files without newline or indentation normalization. Their names hash the source bytes, not the gzip file.
`reviews/` contains source-review evidence and qualifications; `pin-resolution-provenance.json` retains
normalized whole-tree searches and complete source references. Normalization removes machine paths and
keeps original artifact digests separately. These are public source reviews, not private trial inputs or
external judge/provider responses.

Each row includes the MIT notice and its pinned revision. The before clipboard notice was independently
read from its **before revision**, rather than inferred from merge. Full-source archives preserve embedded
third-party notices, including partial-json's attribution. LiteLLM's retained evidence explicitly excludes
`enterprise/`. License evidence describes the inspected public sources, not a repository-wide legal finding.

## Importing without changing the label scope

`accepted-public-gold.jsonl` uses the existing `GoldPair` JSONL fields with additive maintenance metadata
(independent data schema 1). `accepted-public-gold.schema.json` describes those metadata requirements; no
production format or importer changed. The standalone file includes code, notices, labels, pins and review
qualifications; relative source/review paths provide the additional auditable context when this directory
is copied beside it.

```python
from pathlib import Path
from dry_lint.bench import load_gold

root = Path("examples/public-gold")
pairs = load_gold(root / "accepted-public-gold.jsonl")
assert len(pairs) == 4
```

**Import compatibility is not whole-function or retrieval compatibility.** `load_gold` ignores additive
metadata. Consumers must also read the original JSON row's `label_scope`, `granularity`, and
`whole_function_label` (always null). `new.code` and `existing.code` are exact reviewed operation snippets;
some are not standalone function declarations. The generic `as_function` path may parse a fragment or fall
back to text and does not enforce operation scope. Native snippet comparer runs are therefore not a claim
about full-corpus candidate recall, and generic judge runs cannot discard these qualifications.

For full-background analysis, explicitly select the side's repository/revision, then use
`side.extraction.source_id` and `source_sha256` to find the **enclosing extracted function** in that snapshot.
Check `scope_mismatch` before evaluating: true means the reviewed snippet occupies only part of that
function. It must remain flagged in results. Never replace that frozen document's tokens with snippet
tokens, quietly relabel the full function, index just these four rows, or combine revisions.
For example, `promise.ts::make.llmRequest` is the reviewed operation identity while
`promise.ts::make` is its production extraction identity. Neither is interchangeable with the other.
The snapshot does not apply detector filtering, forwarding rules, changed-function selection or budgets.

## Full pinned diagnostic backgrounds

`backgrounds/manifest.json` references production `BenchBackground` schema 1 gzip snapshots. They contain
all functions extracted from the full tracked supported-language source corpus at each exact pin, with
explicit diagnostic `include = ["*"]`, `exclude = ["*/migrations/*"]`, default Python/TypeScript extractors,
and `max_df = 0.3`. This intentionally includes tests/scripts; **it is not adopter-configured scope**.
The pinned configuration is not used to infer scope or cutoff. Unsupported languages, nonregular Git
entries, declaration-only stubs, and functions the production adapters do not extract are not documents.
Source inventories include parser-supported blobs and configuration blobs read by `tree_blobs`; they do
not claim every repository blob is indexed. Token document frequencies count extracted functions.

| Corpus | Revision | Functions | Source files read | Source bytes | Snapshot bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| T3 before | `ac0d1f52a087c63819b2b032ac4535d18d3c23af` | 1,597 | 409 | 3,264,220 | 248,916 |
| T3 merge | `876bbd715ae6aa8e1d663455747e17c92e0a287c` | 1,601 | 410 | 3,267,274 | 249,343 |
| OpenCode before | `51626eee903ea31fde7f41deb6a3430c939d9d90` | 13,895 | 5,110 | 37,079,324 | 2,075,643 |
| OpenCode merge | `cc996eece172fc69e35662657ea6cea9c2c7db88` | 13,893 | 5,110 | 37,078,688 | 2,075,475 |
| SDK before, related only | `cfae94d00e7addaa592ee7c9a92ebb4939b13034` | 2,349 | 361 | 2,109,803 | 284,018 |
| SDK merge, related only | `344ec8a9c30dff0a4ca200fc412510aad44e1bdc` | 2,348 | 361 | 2,109,953 | 284,030 |

Capture used Python 3.14.4, production `Detector.for_tree`, and `BenchBackground.capture/encode`.
Manifest entries preserve extractor choices, implementation-contract fingerprint, Python version, scope,
gzip hashes, source inventories and gold-to-function mappings. Full source inventories preserve each
file's Git identity, SHA-256 and byte count. No tiny golden-only corpus stands in for repository IDF.
SDK snapshots are explicitly supplementary dead-code evidence, not additional accepted families.

The coordinator acquired bare repositories with exact-pin `git fetch --depth=1` from public GitHub;
unset HEAD was never used. Git objects and source were read only as text. An independent GitHub connector
tree/blob acquisition also verified the 417 unique supported-source/license blobs across both T3 pins;
it is research acquisition output and is not required by this portable package. No target installs,
imports, execution, enterprise source, external judges or provider credentials were used.

To recapture, use the production `scripts/freeze_bench_background.py` with `--diagnostic`, the exact
repository/revision and the same parser environment. Keep all revision outputs separate. Compare the
extraction contract and inventories before treating a new capture as the same baseline. Do not overwrite
these counts after changing tokenization.

## Validation

`SHA256SUMS` covers every package file except itself; run `sha256sum -c SHA256SUMS` here after relocation.
The shipped `validate.py` offline regression validator checks native import,
all gzip envelopes and frequencies, full inventories against pinned Git, every source/function/snippet
digest and span, per-row license revisions, recursively resolved references and portable relocation.
It also rejects missing source/review files, a before row using an after license pin, a suppressed
scope-mismatch flag, and a whole-function label added to an operation row. No production code or CI
changes are needed to use these data. From the repository root, run it using the installed project environment:

```sh
uv run python examples/public-gold/validate.py
```

This command requires no source checkout or network. Optional `--audit-git-root /path/to/pinned-bare-repos`
also compares every inventory entry with the exact pinned Git blobs; that directory must contain
`t3code.git`, `opencode.git` and `software-agent-sdk.git`. `--report` writes a requested report path;
by default results go only to stdout. The validator also verifies relocation to a temporary directory.
