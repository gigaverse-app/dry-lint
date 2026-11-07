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

The primary paid feeds completed 24 pairs in round 1 and 28 in round 2, with eight controls each. All prepared round-1 pairs were baseline-funded. Round 2 prepared two additional funding opportunities; one was judged and both providers called it separate. Provider answers were observations, not truth. [Accepted independent source review](portable-source-review-v1.jsonl) found:

- **Redis subscriber loops** contain a narrow reusable subscription/reconnect lifecycle, preserving a configuration-resynchronization hook (case7de6 / RR07). Baseline already funded it; the original report policy did not emit it. Partial usefulness does not make the whole functions interchangeable.
- **Metrics accumulation tests**, the sole emitted balanced report, overlap in coverage of an existing production operation rather than duplicate a new implementation (case6cb1 / RR08). `Metrics()` initializes a zero `TokenUsage` in its after-model validator, so both additions exercise the existing-accumulator branch; neither test covers a None-to-existing transition. It was baseline-funded and related, not source-positive: zero useful reports out of one emitted.
- **An agentic-plan builder versus a legacy loop entrypoint**, the additional judged candidate, was accepted as **related** after root independently verified the pair’s two native endpoints and exact source hashes (case8d68 / RRS01). The proposed common operation lies in a downstream helper outside the nominated body. This is not a useful nominated-body duplicate and receives no positive credit; its source verification is complete.

Thus there were **zero additional useful emissions and zero lost reports**; default emitted none. Unstarted requests and unaccepted source cases remain unknown.

Correct paragraph ownership did not guarantee relevant selected text. Repairing that defect was insufficient here. Source review also distinguished useful partial extraction from shared purpose, test overlap and delegation to an existing helper. Broader documentation methods remain untested; they are not conclusions of this comparison.

**Next step:** publish this recipe’s evidence; do not promote it or start a third variant. The additional judged candidate is now source-confirmed related, so it supplies no useful incremental candidate or report. The useful Redis partial extraction was already baseline-funded and cannot establish added recall. Other unaccepted or unstarted cases remain unknown; they do not change the observed zero incremental emissions.

## Evidence, reproduction and limits

[Metrics](metrics.json), [portable requests](portable-public-requests.jsonl), [accepted source decisions](portable-source-review-v1.jsonl) and [audit](PR110-AUDIT.json) contain exact denominators, public repository commits, source/body hashes, request identities and outcomes. No new evaluation or provider execution accompanied this report. Public source pins are LiteLLM `fc1e47e580d9e3d2e8b46ad05a293a58ed0b8f1f` and software-agent-sdk `344ec8a9c30dff0a4ca200fc412510aad44e1bdc` for the paid requests. Full reruns require the original exact source backgrounds and lab utilities; hashes alone cannot reconstruct them. Provider replay additionally needs the adopter’s credentials and new payment; it was not performed.

Actual attributed judging cost was **$0.21664116 + $0.23132376 = $0.44796492**, buying no incremental useful report. Round 1 includes $0.17884384 from its primary feed and $0.03779732 from twelve separately attributed current-phase requests. Cache reuse and historical pilot spend were excluded. The normal $0.04 simulated query allowance was separate. There were 48 successful/16 unknown planned provider responses in round 1 and 56 successful/8 unknown in round 2; reserves were not exhausted. Cached query/source phases took 164.68s/399 queries and 159.29s/419 queries, with peak process memory 623/651MiB. Setup and incremental overhead were not isolated. These measurements establish neither deployment performance nor full-inventory recall.

The portable files are this README, `metrics.json`, `portable-public-requests.jsonl`, `portable-public-prior-phase-attribution.jsonl`, `portable-source-review-v1.jsonl` and `PR110-AUDIT.json`. Machine evidence remains frozen at its earlier capture time: any RRS01 pending fields there are historical. The final source state is the root-verified **related** decision reported above. No historical narrative document is needed to read or publish this report.

To reproduce the paid-cost accounting locally, run beside the portable files:

```sh
python3 - <<'PYACCOUNT'
import json
from decimal import Decimal
from pathlib import Path
rows = [json.loads(x) for x in Path('portable-public-requests.jsonl').read_text().splitlines()]
prior = [json.loads(x) for x in Path('portable-public-prior-phase-attribution.jsonl').read_text().splitlines()]
for round_number in (1, 2):
    paid = sum((Decimal(str(r['actual_paid_usd'] or 0)) for r in rows if r['round'] == round_number), Decimal(0))
    if round_number == 1:
        paid += sum((Decimal(str(r['usd'])) for r in prior), Decimal(0))
    print(round_number, paid.quantize(Decimal('0.00000001')))
PYACCOUNT
```
