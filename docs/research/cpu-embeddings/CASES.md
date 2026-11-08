# Representative original answers and decisions

Source usefulness is independently assessed and scoped to an operation. These selected cases are illustrations, not an unbiased precision estimate. Inspect exact source, rendered request/settings and full observations with `python3 reproduce.py --case CASE_ID`.

## CPUR2-001

The base iterator closes its optional attached HTTP response; the Responses iterator delegates closure to its existing CustomStreamWrapper. These are resource-owner/protocol layers along a closure chain, not two copied close algorithms.

Source assessment: **related**. Proposed scope and preserved behavior:

```json
{
  "extract": null,
  "negative_scope": "Retain both aclose implementations and the existing wrapper close owner. No new generic closer needed for a conditional await and one delegation.",
  "preserve": [
    "optional attached response at base iterator",
    "wrapper-owned shielding/closed state/context restoration",
    "single delegation through established ownership chain"
  ]
}
```

**jev:** separate 0.41; fixed .8 diagnostic report: False.

> The functions implement different concepts.

**claude:** separate 0.05; fixed .8 diagnostic report: False.

> The two aclose methods only share a name and an async-close shape. NEW closes the upstream HTTP response if one is attached. EXISTING forwards the close to a wrapped stream wrapper object. They have no common executable policy beyond delegating a close to a different owned resource, so there is no reusable operation to extract.

Both revised CPU and matched wider TF-IDF20 retrieve and fund this pair. A useful candidate missed by Claude is a judge/reporting miss; a related pair emitted by Claude is an unsupported projection. Neither establishes a unique useful embedding report.

## CPUR2-002

Count and item debug routes traverse the same live router/prompt-pin/user-key/key-object/proxy-usage caches. Router and pin extraction already have helpers, while the remaining nested cache dictionary/TTL inventory is repeated.

Source assessment: **useful**. Proposed scope and preserved behavior:

```json
{
  "extract": "Create a small shared live cache inventory reader returning entry/expiry mappings with their logical buckets. Reuse existing router/pin helpers. Keep count aggregation/public num_items keys separate from raw item/TTL response labels, and retain late proxy imports or explicit runtime objects at the original call boundary.",
  "negative_scope": null,
  "preserve": [
    "raw live mappings, not new snapshots/copies",
    "count includes entries and TTL maps, including key-object cache",
    "existing public response keys and grouping",
    "router None behavior and existing access dependencies/decorators",
    "late-bound proxy globals; no startup-time capture"
  ]
}
```

**jev:** drifted 0.86; fixed .8 diagnostic report: True.

> One concept may be shared, but dependency contracts need review before consolidation.

**claude:** separate 0.25; fixed .8 diagnostic report: False.

> Both endpoints import the same globals and call the existing helpers `_router_store_entries` and `_prompt_caching_pins`, so the router and pin lookups are already centralized. What remains in each function is a different projection of the cache dicts. NEW returns summed counts, and EXISTING returns the raw dicts. Both read the same attribute paths, but that is thin accessor repetition. A shared 'collect in-memory cache stores' helper is conceivable, but the source does not establish a strong policy contract. There is one small behavioral difference: NEW guards `llm_router is None` for the router count but not for the pins call, while EXISTING calls `_router_store_entries` unguarded. That is not a conflicting outcome of the same operation.

Both revised CPU and matched wider TF-IDF20 retrieve and fund this pair. A useful candidate missed by Claude is a judge/reporting miss; a related pair emitted by Claude is an unsupported projection. Neither establishes a unique useful embedding report.

## CPUR2-044

Both read model_info.id, but token-count logging accepts only an existing str and permits absent deployment input. Affinity selection accepts a Mapping and converts any non-None ID to str.

Source assessment: **related**. Proposed scope and preserved behavior:

```json
{
  "extract": null,
  "negative_scope": "Keep the different validation/coercion policies explicit. No useful helper beyond primitive nested lookup is justified unless maintainers first decide a common ID input contract.",
  "preserve": [
    "string-only logging result and optional input",
    "affinity str(non-None) normalization",
    "missing model_info/id handling and exclusion identity"
  ]
}
```

**jev:** duplicate 0.93; fixed .8 diagnostic report: True.

> One portable domain concept can share an implementation; review behavior differences before moving it.

**claude:** drifted 0.8; fixed .8 diagnostic report: True.

> Both functions extract a deployment's model id from deployment['model_info']['id'] and return None when model_info is missing or is not a mapping. That is one reusable operation, and a single shared helper (for example in router utils) could own it. The two copies conflict on comparable inputs. NEW returns the id only when it is already a str, so an int or other non-str id gives None. EXISTING returns str(id) for any non-None id, so the same id gives a string. NEW also accepts a None deployment, which EXISTING does not. A shared helper would need to settle the non-str id policy, and a None-tolerant wrapper could stay at the call site.

Both revised CPU and matched wider TF-IDF20 retrieve and fund this pair. A useful candidate missed by Claude is a judge/reporting miss; a related pair emitted by Claude is an unsupported projection. Neither establishes a unique useful embedding report.

## CPUR2-056

The standalone parser accepts string overrides, preserves non-string None/no-override, and projects accepted service aliases to DB-system names. The Pydantic validator delegates broader settings input to excluded_service_names and returns service names.

Source assessment: **related**. Proposed scope and preserved behavior:

```json
{
  "extract": null,
  "negative_scope": "Preserve override parsing versus typed-settings validation; both already reuse the service-name normalization owner. No new shared body operation in these wrappers.",
  "preserve": [
    "non-string override None versus settings empty set",
    "explicit none clears exclusions",
    "YAML/list settings input and error logging",
    "service names versus canonical redis/postgresql projection"
  ]
}
```

**jev:** drifted 0.82; fixed .8 diagnostic report: True.

> One portable domain concept can share an implementation; review behavior differences before moving it.

**claude:** separate 0.2; fixed .8 diagnostic report: False.

> EXISTING is a one-line adapter that delegates to excluded_service_names. NEW does its own handling (non-string returns None, 'none' returns an empty set) and then delegates to excluded_db_systems_from. The two use different helpers and have different return contracts (None vs. frozenset). The source does not show that excluded_service_names repeats NEW's parsing logic, so there is no established shared operation to extract.

Both revised CPU and matched wider TF-IDF20 retrieve and fund this pair. A useful candidate missed by Claude is a judge/reporting miss; a related pair emitted by Claude is an unsupported projection. Neither establishes a unique useful embedding report.
