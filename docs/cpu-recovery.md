# Enable offline CPU recovery

CPU recovery is a supported opt-in discovery profile for operations that lexical matching or a function's embedding prefix misses. It preserves the evaluated route order, native function prompts and budget rules. The selected development campaigns support three useful added operation families; this is not evidence for enabling it in every repository. See the [tail recovery measurements](cpu-tail-rrf.md).

Install the optional `dry-lint[cpu-embedding]` dependencies. Supply the exact pinned local model and tokenizer described in [offline model setup](cpu-embedding.md#install-and-configure), then add this to `.dry-lint.toml`:

```toml
preset = "balanced"

[discovery.cpu_recovery]
model_dir = ".dry-lint-local/minilm"
cache_dir = ".dry-lint-local/vectors"
```

In `pyproject.toml`, put `preset = "balanced"` under `[tool.dry-lint]` and the paths under `[tool.dry-lint.discovery.cpu_recovery]`. Keep `.dry-lint-local/` out of version control. Paths are relative to the process working directory; use absolute paths when invoking from elsewhere.

```bash
dry-lint detect --root . --base origin/main --out candidates.json
```

The setting enables discovery and expands to TF-IDF20 at .35, operation-blocks/top1, CPU prefix/top1 at .65, and CPU tail rank fusion/top1, in that order. The normal baseline stays first. The CPU setting itself does not change a judge, a threshold, a budget, a prompt, or ranking. The example explicitly selects the `balanced` judging preset used in the useful-report measurements: Haiku/shared-operations, a .50 reporting threshold and a $0.04 PR budget. You can combine the retrieval setting with another judging preset, but its report quality and budget results need separate measurement. Advanced configurations can still use `discovery.comparers`; specifying both forms is rejected. An explicit `discovery.enabled = false` disables the profile. The optional `threads` field accepts 1 or 2 (default 2).

The enablement boundary is explicit: this setting requires installed CPU dependencies and adopter-supplied model files. dry-lint never downloads missing weights, obtains credentials or calls a provider during detection. A missing or mismatched artifact fails with its path and expected model revision. Judging still requires the adopter's separately configured credentials. With no judge, candidates remain look-alikes.

Persist the vector cache before using the profile repeatedly. Cold whole-corpus CPU inference remains expensive. Vector cache entries bind the complete source and encoder contract, validate shape, dtype, finiteness and unit norm, and use atomic replacement. Corrupt entries are misses. It is a representation cache, never a verdict store.

Within one `Detector.candidates()` call, compatible routes reuse one validated encoder, cached prefix vectors and prepared operation-block state. Each constructor still verifies the supplied files. Statement extraction clones its tokenizer, query caches remain private, and resources are released with that call, including failures. Independent or concurrent calls do not retain each other's resources. No weights or full-source matrices live in a process-global cache. Without an explicit disk cache, vector batches remain independent to preserve exact inference behavior.

Compare the profile with the existing configuration on the same base/head and budget. Inspect actual additions and losses, complete functions and shared-campaign admissions before adopting. The resource optimization adds no recall claim and does not remove the profile's cold cost or its possible budget displacement.

## Complete-stack cost after resource sharing

The optimization is automatic for compatible routes; it requires no performance flag. Before/after runs use
the same four routes, 15 fixed queries per snapshot, local model files, and full candidate/prompt hash checks.
Warm figures are medians of three fresh-process runs with validated vectors cached; extraction is excluded.

| Snapshot | Warm detection before → after | Warm peak memory before → after | Cold before → after |
| --- | --- | --- | --- |
| T3, 1,601 functions | 8.47s → 7.65s | 390 → 299 MiB | 117.34s → 123.61s |
| OpenHands, 2,349 functions | 13.57s → 10.00s | 411 → 323 MiB | 183.26s → 181.41s |

Warm time falls 9.7% and 26.3%; warm peak memory falls 23.4% and 21.4%. Both routes now share one encoder
session and one prepared block index. Cold runs still encode the same 1,842/2,714 inputs. Cold timing is one
shared-host observation per arm, with other lab work running; it does not establish a cold speedup. Candidate
and prompt hashes match in every measured pair. The [enablement study](enablement-results.md) separates these
engineering improvements from the earlier three-family recall result and provides reproduction instructions.
