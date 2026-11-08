# Can function-linked documentation improve duplicate retrieval?

**Stop these two variants; retain code-only retrieval.** Documentation did not add a useful emitted duplicate report in this experiment. Merging this record preserves a reproducible negative result, one useful but already-covered extraction opportunity, and a concrete lesson about selecting documentation. It does not establish that documentation cannot help.

Code similarity can miss implementations that use different names for the same operation. We tested the retrieval stage: could prose explicitly referencing a function improve the shortlist sent to dry-lint’s separate duplicate judge? The hypothesis required useful additions beyond baseline, without losing known successes or adding false reports.

The baseline ranked weighted code-word similarity. The variant resolved Markdown references to exact functions at the same repository commit. It compared documentation with code and other documentation, then boosted the baseline score by `0.15 × (1 − baseline) × strongest_match`. Documentation contributed at most 32 words using the unchanged background’s word weights. A control shuffled paragraphs among functions to test whether correct ownership mattered.

The first recipe took a paragraph’s first 512 characters. In 13 of 22 ownership associations, the verified reference was outside that window: ownership was right, but the scored text preceded the reference. The sole preregistered revision changed this selection:

```python
# Same paragraph and verified reference; all other settings fixed.
before = paragraph[:512]
start = max(0, min(reference_start - 256, max(0, len(paragraph) - 512)))
after = paragraph[start:start + 512]
```

We accounted for all 617 inventory records, including the original 400. Seven source-complete cohorts supplied 96 records containing 31 known duplicate pairs in 28 operation families and 51 separate pairs in 37 families. A pair is two nominated function bodies; a family groups related examples of one operation. Another 406 compatible records lacked exact source, documentation or background; 111 had unsupported languages and four were declarations. Missing material was not scored as failure.

Each available pair used identical repository, commit, scope and budgets across variants. Either retrieval direction could find a pair; directions were not independent trials. This was offline development evidence, not deployed traffic. “Funded” means selected under a simulated query budget: **default** considers up to three other-file candidates; **balanced** allows twenty, including same-file candidates. Both also apply fixed score filters.

| Outcome; higher duplicate counts and lower separate counts are better | Code only | First window | Centered window |
|---|---:|---:|---:|
| Duplicates in raw top 3 / top 20 | 26/31 / 30/31 | same | same |
| Duplicates funded: default / balanced | 9/31 / 28/31 | same | same |
| Separate pairs funded: default / balanced | 2/51 / 20/51 | 3/51 / 26/51 | 3/51 / 25/51 |

Known duplicate gains and losses were zero, including family-level comparisons. Balanced retained 26/28 positive families in every variant; shuffled documentation added no known positive either. The repair removed one extra separate exposure, leaving five more than baseline under balanced. Few repositories and correlated examples limit statistical interpretation.

The primary paid feeds completed 24 pairs in round 1 and 28 in round 2, with eight controls each. All prepared round-1 pairs were baseline-funded. Round 2 prepared two additional funding opportunities; one was judged and both providers called it separate. Provider answers were observations, not truth. [Accepted independent source review](data/evidence/portable-source-review-v1.jsonl) found:

- **Redis subscriber loops** contain a narrow reusable subscription/reconnect lifecycle, preserving a configuration-resynchronization hook (case7de6 / RR07). Baseline already funded it; the original report policy did not emit it. Partial usefulness does not make the whole functions interchangeable.
- **Metrics accumulation tests**, the sole emitted balanced report, overlap in coverage of an existing production operation rather than duplicate a new implementation (case6cb1 / RR08). `Metrics()` initializes a zero `TokenUsage` in its after-model validator, so both additions exercise the existing-accumulator branch; neither test covers a None-to-existing transition. It was baseline-funded and related, not source-positive: zero useful reports out of one emitted.
- **An agentic-plan builder versus a legacy loop entrypoint**, the additional judged candidate, was accepted as **related** after root independently verified the pair’s two native endpoints and exact source hashes (case8d68 / RRS01). The proposed common operation lies in a downstream helper outside the nominated body. This is not a useful nominated-body duplicate and receives no positive credit; its source verification is complete.

Thus there were **zero additional useful emissions and zero lost reports**; default emitted none. Unstarted requests and unaccepted source cases remain unknown.

Correct paragraph ownership did not guarantee relevant selected text. Repairing that defect was insufficient here. Source review also distinguished useful partial extraction from shared purpose, test overlap and delegation to an existing helper. Broader documentation methods remain untested; they are not conclusions of this comparison.

**Next step:** publish this recipe’s evidence; do not promote it or start a third variant. The additional judged candidate is now source-confirmed related, so it supplies no useful incremental candidate or report. The useful Redis partial extraction was already baseline-funded and cannot establish added recall. Other unaccepted or unstarted cases remain unknown; they do not change the observed zero incremental emissions.

## Evidence, reproduction and limits

[Metrics](data/evidence/metrics.json), [portable requests](data/evidence/portable-public-requests.jsonl), [accepted source decisions](data/evidence/portable-source-review-v1.jsonl) and [audit](data/evidence/PR110-AUDIT.json) contain exact denominators, public repository commits, source/body hashes, request identities and outcomes. No new evaluation or provider execution accompanied this report. Public source pins are LiteLLM `fc1e47e580d9e3d2e8b46ad05a293a58ed0b8f1f` and software-agent-sdk `344ec8a9c30dff0a4ca200fc412510aad44e1bdc` for the paid requests. Full reruns require the original exact source backgrounds and lab utilities; hashes alone cannot reconstruct them. Provider replay additionally needs the adopter’s credentials and new payment; it was not performed.

Actual attributed judging cost was **$0.21664116 + $0.23132376 = $0.44796492**, buying no incremental useful report. Round 1 includes $0.17884384 from its primary feed and $0.03779732 from twelve separately attributed current-phase requests. Cache reuse and historical pilot spend were excluded. The normal $0.04 simulated query allowance was separate. There were 48 successful/16 unknown planned provider responses in round 1 and 56 successful/8 unknown in round 2; reserves were not exhausted. Cached query/source phases took 164.68s/399 queries and 159.29s/419 queries, with peak process memory 623/651MiB. Setup and incremental overhead were not isolated. These measurements establish neither deployment performance nor full-inventory recall.

The portable files are this README, `metrics.json`, `portable-public-requests.jsonl`, `portable-public-prior-phase-attribution.jsonl`, `portable-source-review-v1.jsonl` and `PR110-AUDIT.json`. Machine evidence remains frozen at its earlier capture time: any RRS01 pending fields there are historical. The final source state is the root-verified **related** decision reported above. No historical narrative document is needed to read or publish this report.

To reproduce the paid-cost accounting locally, run beside the portable files:

```sh
python3 - <<'PYACCOUNT'
import json
from decimal import Decimal
from pathlib import Path
rows = [json.loads(x) for x in Path('data/evidence/portable-public-requests.jsonl').read_text().splitlines()]
prior = [json.loads(x) for x in Path('data/evidence/portable-public-prior-phase-attribution.jsonl').read_text().splitlines()]
for round_number in (1, 2):
    paid = sum((Decimal(str(r['actual_paid_usd'] or 0)) for r in rows if r['round'] == round_number), Decimal(0))
    if round_number == 1:
        paid += sum((Decimal(str(r['usd'])) for r in prior), Decimal(0))
    print(round_number, paid.quantize(Decimal('0.00000001')))
PYACCOUNT
```


## Run the portable study package

This publication adds exact selected-input transformation replay and recorded-answer scoring to the frozen report above. It keeps original artifacts in `data/evidence/` unchanged, including historically pending fields. [Final source interpretations](data/final-source-decisions.json) are a separate update; provider answers never substitute for them.

From this directory, using Python 3.11 or newer and only the standard library:

```sh
python3 transform.py
python3 reproduce.py replay
python3 reproduce.py audit
python3 reproduce.py inspect LINKED-R2-7de6eddfae2d5c02be41 --part prompt
python3 reproduce.py inspect LINKED-R2-7de6eddfae2d5c02be41 --part answer
python3 reproduce.py archive
```

`transform.py` reruns the selected transformation, checks its recorded output and prints the before/after result. `reproduce.py replay` reparses sanitized original answers for the representative cases and recomputes fixed-policy emissions and primary-feed costs. The full primary feeds retain all unstarted answers as unknown in [observations](data/observations.jsonl). Admission decisions are frozen inputs in [policy admissions](data/policy-admissions.jsonl); replay is not a fresh candidate search or a new source adjudication. The historical full-corpus comparisons remain scoped to their supported denominators.

The exact contextual Jev request uses `jev-1.14.0`; Claude uses `claude-sonnet-5-5`, shared-operations prompt, 1,024 output tokens, no effort override, no malformed-answer retry, and the recorded default server fallback option. Exact per-request options, scope, full rendered prompts and source hashes are in [selected cases](data/selected-cases.json.gz), inspectable with the commands above. No temperature or seed is set in these requests. Jev scores same-concept probability, capped by a concrete separation reason; score below .6 is separate, behavior difference at least .8 is drifted, and non-separate score at least .8 is reportable. Jev and Claude remain independent observations. These are recorded outcomes, not a claim that a future model would answer identically.

[Readable key implementation files](implementation/README.md) and the complete archived study scripts, dry-lint modules and lockfile are available through `reproduce.py archive NAME`. Archived runners preserve their original dependency paths and are data, never imported at module startup. The portable adapters execute only explicitly selected pure algorithm definitions or their documented bounded application; they never import provider runners. Original and public hashes disclose any static private-routing redaction.

## Inputs, acquisition and limits

The selected native function bodies and full files are shipped under their original [licenses](licenses/), with Git pins and hashes in [source files](data/source-files.json.gz) and the [source manifest](data/source-manifest.json). They are parsed or inspected as data, never imported or executed. Full corpus inputs stay in the separate goldens repository. Print the pinned acquisition plan, review it, then run it explicitly:

```sh
python3 acquire.py > local-acquire.sh
cat local-acquire.sh
sh local-acquire.sh
```

[CORPUS.json](CORPUS.json) maps all 79 study-background hashes against `gigaverse-app/dry-lint-goldens` at `bb29c4b71987008d06c2381a68b6833b6d542e3e`: **8 exact matches, 19 public backgrounds absent from that catalog, and 52 private backgrounds excluded from public distribution**. It records exact dataset/materialization paths for matches. A same-repository background with another hash is not a replacement. The manifest is an input inventory, not an evaluated denominator. Public source pins, configured/diagnostic scopes, parser and extraction versions, original row mappings, family lineage, per-query candidate exclusions and budget ledgers are all needed for full-campaign reruns. Their location contract is explicit; a hash cannot reconstruct an absent input. Original scripts and specifications preserve the protocol without copying large backgrounds into this repository.

The included source-free held-request templates, if any, have no source or model explanation prose. `python3 hydrate.py` prints the exact local plan. Hydration requires an explicitly supplied Git checkout, checks full source hashes, applies the frozen extraction character map and validates both rendered-request and request-identity hashes. It is cached-extraction reconstruction, not a fresh parser validation. Keep hydrated output local. The current publication makes no provider calls and provides no executable live judge runner; a new live study would require separate authorization, adopter-owned credentials and budget, the original archived procedure and a new output directory.

[PROVENANCE.json](PROVENANCE.json), [feed hashes](data/feed-provenance.json), per-file archive hashes and `SHA256SUMS` distinguish original evidence from publication adapters. [CHECKS.json](CHECKS.json) records the clean-copy commands, source/license checks and decompressed archive scan. These checks verify the stated selected replay and arithmetic, not full-corpus extraction, production deployment, semantic gold labels, invoices or broad recall.


The selected transform runs the **original `AnchorWindowSnapshot.inventory` method**, with the original paragraph parser, Markdown cleanup and word splitter, against three pinned ownership associations and complete Markdown files. For the Redis subscriber, its reference starts at character 915; the initial 512-character head misses it and the centered window contains it. The other examples cover a partially clipped usage-calculation reference and an already-visible database reference. It verifies the recorded windows and 32-word fields exactly. This begins from frozen ownership associations: it does not claim to rerun whole-repository link ownership discovery.

`python3 aggregate.py` recomputes all twenty original/centered, positive/separate ranking and funding comparisons from 224 anonymized paired records, preserving 31 positive pairs/28 families and 51 separate pairs/37 families. None of those records enlarges the supported denominator to 617. The selected cases reproduce the actual original answers: the useful Redis loop gets Jev `duplicate`, `.64` and Claude `duplicate`, `.80`; under the tested Jev policy it is not emitted, and it was already baseline-funded. The metrics tests get Jev `.87` and Claude `.80`, both `duplicate`, yet independent source review retains them as **related coverage of an existing operation**. This emitted control is not a useful new report. The builder/legacy entrypoint is now source-confirmed related; its proposed shared operation is downstream of the nominated body.

`reproduce.py replay` also adds the twelve separately attributed current-phase round-one requests ($0.03779732) to the primary feed ($0.17884384), reproducing **$0.21664116**. Together with round two's **$0.23132376**, this gives **$0.44796492** actual attributed spend. This accounting excludes older pilot spend and cache credit and remains distinct from the simulated $.04 allowance.
