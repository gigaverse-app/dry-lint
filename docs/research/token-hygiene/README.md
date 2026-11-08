**Sparse token hygiene: better ranks lost useful candidates**

Repeated naming words can make unrelated functions look alike. We tested whether cleaning those words, then limiting repeated body words, would give dry-lint more useful candidates. **Keep the current matcher: stop these recipes.** The broader weighting change improved known-positive ranks but lost four previously selected useful pairs under the unchanged default candidate policy. Its sole emitted novel report was source-unsupported: related functions, without useful duplication in the nominated bodies.

Dry-lint first shortlists function pairs using TF-IDF (term frequency–inverse document frequency): normalized token overlap weighted by how uncommon each token is in the full indexed function collection, called the background. A separate judge assesses useful shared behavior. We changed shortlisting, not that semantic decision. A higher overlap score is not a probability that two functions should share an implementation.

The first three fixed variants removed `should/given/when/then` only from word/name features, repaired splitting of syntactic getter/setter names, or combined those changes. None gained or lost a known positive selected for judging. Our source inspection of five paid-review disagreements suggested that shared project/provider vocabulary or test setup was masking different operations. That motivated one revision from the original tokens, without combining earlier changes: count each `w:` body-word feature once, in both corpus and query. A word mentioned five times previously contributed `(1 + ln 5) × IDF`; afterward it contributed `1 × IDF`, before normalization. IDF is the original background rarity weight. Vocabulary, function-name/API/attribute/key counts, original IDF, corpus order and frequency cutoff stayed fixed. This was a weighting change.

We compared each recipe with the original frozen index across **617 already-observed development/regression records and 79 exact repository/revision/scope backgrounds**. All 580 accepted function rows received raw rankings; four accepted model declarations remain unsupported. Previously accepted corpus labels, including scoped partial operations and behavioral drift, define positive and separate cases; new paid model answers do not relabel them. After deduplicating within backgrounds, the paired comparison contains 227 known-positive and 521 known-separate cases. The same pair in another background is another observation, not independent evidence. Related implementation families cluster correlated examples; uncertainty estimates resample repository/family groups, not individual queries. Missing historical source leaves some filtering and budget outcomes unknown.

“Selected” (“funded” in the machine evidence) means admitted under the unchanged estimated per-change judging budget. The default diagnostic takes up to three cross-file neighbors at score .5 (.3 for a valid or explicitly inferred query shorter than six lines). The separate balanced diagnostic permits twenty neighbors, including same-file pairs, at .35. These are offline experimental profiles, not claimed adopter deployment settings.

| Revised result | Baseline → revision | Gains / losses |
|---|---:|---:|
| Positive raw top-three ranks | 182/227 → 189/227 | 9 / 2 |
| Default positive pairs selected | 39/77 → 35/77 | **0 / 4** |
| Balanced positive pairs selected | 69/76 → 68/76 | **2 / 3** |
| Default separate pairs selected | 23/118 → 22/118 | 3 / 4 |
| Balanced separate pairs selected | 58/117 → 57/117 | 4 / 5 |

The four default losses are distinct source pairs in three families. All crossed below the fixed score floor: one useful pair stayed ranked first while its score fell **0.549→0.488**, below .5. This explains why improved ranking did not improve actual admission. Default/balanced positive selection outcomes remain unknown for 150/151 cases respectively; the table uses supported paired denominators. [The four loss records](data/evidence/default-four-losses.jsonl) retain exact scores, ranks and floors.

Full-source discovery in five pinned public repositories used the balanced diagnostic to test whether new exposure yielded useful reports. The two rounds completed judging for **32/44 and 40/44 novel pairs**, plus all four matched baseline-funded controls per round: independent comparison pairs already selected by the baseline, with unknown source labels. Round two avoided round-one modules/owners and overlapping known catalog families. Sixteen novel pairs remain unstarted and unknown. Jev and Claude were evaluated independently. Original-policy replay produced no novel report in the first feed and one Jev-only report in the second; Claude emitted none.

Root accepted the reported string-normalization/configuration-reader pair as **related, with no useful consolidation of the nominated bodies** (**TH-R2-faccb8de38d2**, Jev .80/Claude .20). The configuration reader already delegates trimming and owns optional-value/Effect configuration semantics; the other helper normalizes an arbitrary input value. Any potential sharing inside the downstream trim helper is outside this nominated pair and receives no duplicate credit. Root also accepted typed tool-call adaptation versus generic message extraction as related (**TH-R2-f111c4a60a3a**); its Jev score .69 was below the original .8 report threshold. **Neither pair becomes a binary gold negative.**

The result is **zero confirmed new useful gains and one unsupported useful report out of one source-reviewed emitted novel report**. This is a report-utility assessment, not binary false-positive accuracy. Unreviewed cases, missed-report counts and the first-round control report remain unresolved; provider answers alone do not settle them. Candidate exposure and lost funding opportunities are not automatically emitted gains or confirmed missed reports.

The causal lesson is that changing token repetition changes normalized score calibration as well as ranking. The hypothesis that repeated body words create avoidable false matches remains unproven. **Stop these four fixed recipes as default replacements; change no production code and run no third mechanism.** Root should merge this closed record. The related source decisions resolve the nominated useful-report claims without erasing the four observed default regressions. This does not reject tokenization research generally.

**Appendix — evidence, costs and reproduction.** [metrics.json](data/evidence/metrics.json) contains all denominators and paired family/repository uncertainty; [novel-outcomes.jsonl](data/evidence/novel-outcomes.jsonl) preserves returned case/request IDs and unknown answers. [source-outcomes.jsonl](data/evidence/source-outcomes.jsonl) records the two independently accepted related assessments and their bounded scope. Four additional root-accepted negative audit pairs outside the 617 snapshot were checked separately: default selected exposure 2→3; balanced 4→4. Earlier audits confirmed four exclusions only; 15 earlier triages lack independent audit.

Round one cost **$0.20808808** ($0.17449224 in its top-up feed plus $0.03359584 separately attributed by root); round two cost **$0.21569280**: **$0.42378088** fresh actual spend. Historical audit spend $0.05149316 is excluded. Physical spend is distinct from the synthetic estimated .04 budget, charged normally per arm even for cached answers. Worker provider calls: zero. The main revised run took 523s for 2,506 variant queries plus 1,280 discovery-baseline queries; setup/snapshot I/O 168s, recorded peak RSS about 0.86GiB. Timing does not establish a speedup.

Run `python3 data/evidence/verify_evidence.py` here. The standard-library verifier reproduces 96 paired metric checks and frozen 2,000-repeat uncertainty intervals from 6,920 redacted paired rows, without fitting, providers or network access. Stable opaque keys preserve background/family grouping while excluding private names, paths and code. Native corpus reruns require the original immutable inputs and shared resolver; hashes alone cannot reproduce unavailable source. This public export verifies arithmetic and grouping, not semantic gold labels or extraction.


## Run the portable study package

This publication adds exact selected-input transformation replay and recorded-answer scoring to the frozen report above. It keeps original artifacts in `data/evidence/` unchanged, including historically pending fields. [Final source interpretations](data/final-source-decisions.json) are a separate update; provider answers never substitute for them.

From this directory, using Python 3.11 or newer and only the standard library:

```sh
python3 transform.py
python3 reproduce.py replay
python3 reproduce.py audit
python3 reproduce.py inspect TH-R2-faccb8de38d2 --part prompt
python3 reproduce.py inspect TH-R2-faccb8de38d2 --part answer
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
