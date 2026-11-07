# Representative original answers and decisions

Source usefulness is independently assessed and scoped to an operation. These selected cases are illustrations, not an unbiased precision estimate. Inspect exact source, rendered request/settings and full observations with `python3 reproduce.py --case CASE_ID`.

## OBR1-cd803a8002adba3e

Token-error helper reuse

Source assessment: **useful**. Proposed scope and preserved behavior:

```json
{
  "extract": "Reuse the existing token-or-error helper from both configurations, moving it to a neutral ChatGPT auth utility if needed to avoid importing chat configuration into Responses. Replace only the Responses login try/except with that call (provider chatgpt). Leave header/session/account/client-credential/configured-key selection untouched.",
  "negative_scope": null,
  "preserve": [
    "only GetAccessTokenError translated; other exceptions unchanged",
    "model/provider/message and implicit exception chaining",
    "no fetch on client/configured-key bypass",
    "session ID, account ID and caller header precedence"
  ]
}
```

**jev:** duplicate 0.76; fixed .8 diagnostic report: False.

> One portable domain concept can share an implementation; review behavior differences before moving it.

**claude:** duplicate 0.8; fixed .8 diagnostic report: True.

> Both run the same sub-operation: call authenticator.get_access_token() and convert GetAccessTokenError into AuthenticationError(model, llm_provider, message=str(e)). NEW already wraps it as _get_access_token_or_raise(authenticator, model, llm_provider). EXISTING repeats the try/except inline with llm_provider hard-coded to "chatgpt". The error-mapping policy is identical, and a shared helper (for example in the chatgpt common authenticator module) would take the provider as a parameter. EXISTING could call it, or NEW's helper could be reused there. The rest of validate_environment stays at its call site: client-credential handling, API-key shortcut, account id lookup, and header assembly. This is a small but clear repeated policy, not a duplicate of the whole function.

Original funded: True; matched baseline funded: False; residual veto retains pair: False. Original answer is reused only as the stated selector counterfactual. Native concept/Haiku outcomes are not inferred from it.

## OBR2-AUDIT-0484f22cb559

Atomic staged-file commit

Source assessment: **useful**. Proposed scope and preserved behavior:

```json
{
  "extract": "Have _replace_file reuse the existing commit_staged_json for the staged temporary path and destination (or expose the same operation under a file-oriented name). Keep its UTF-8 text staging, same-directory placement and file mode/flush behavior local; do not substitute the higher-level JSON writer.",
  "negative_scope": null,
  "preserve": [
    "os.replace atomic destination replacement",
    "only OSError triggers missing_ok staging unlink and rethrow",
    "text temporary file in destination directory and UTF-8 encoding",
    "current staging mode/flush/fsync behavior; no JSON conversion"
  ]
}
```

**jev:** duplicate 0.85; fixed .8 diagnostic report: True.

> One portable domain concept can share an implementation; review behavior differences before moving it.

**claude:** duplicate 0.8; fixed .8 diagnostic report: True.

> Both functions perform the same atomic-commit step: os.replace(staged, target), and on OSError they unlink the staged temp file with missing_ok=True and re-raise. The error handling and cleanup invariants are identical. EXISTING also creates the temp file and writes text, which NEW does not (its staging happens elsewhere), so only the commit step overlaps. A shared helper such as commit_staged_file(staged, path) could own the replace-and-cleanup logic, and _replace_file could call it after writing its temp file. The temp-file creation and writing stay in the callers. This is a small, clearly repeated policy, and the overlap is a sub-operation rather than the whole of EXISTING.

Original funded: True; matched baseline funded: False; residual veto retains pair: False. Original answer is reused only as the stated selector counterfactual. Native concept/Haiku outcomes are not inferred from it.

## OBR2-AUDIT-519d0bb0d55e

Deadline versus relay cleanup

Source assessment: **related**. Proposed scope and preserved behavior:

```json
{
  "extract": null,
  "negative_scope": "Keep distinct deadline/containment and stream-resource supervision policies. asyncio.wait/cancel scaffolding alone does not justify a new mode-driven task supervisor.",
  "preserve": [
    "guardrail context deadline, containment/result/exception behavior",
    "bounded repeated cancellation and straggler outcome handling",
    "relay outer-cancellation drain before finally close",
    "already-cancelled relay returns zero; otherwise billed_seconds"
  ]
}
```

**jev:** separate 0.25; fixed .8 diagnostic report: False.

> The functions implement different concepts.

**claude:** separate 0.12; fixed .8 diagnostic report: False.

> Both functions create a task, wait on it with asyncio.wait, and cancel it if the caller is cancelled. That is a common asyncio idiom rather than a shared domain operation. NEW is a deadline-bounded await. It copies the context, sets a deadline, wraps the awaitable in _contain, discards the outcome, and returns the result or raises ExecutionTimeoutError after a forced _cancel. EXISTING is a stream relay. It checks a cancelled flag, forwards data from an outbox, waits without a timeout, awaits the task's completion on cancellation, always closes the stream, and returns billed seconds. The timeout handling, context handling, cancellation escalation, and resource cleanup all differ, so a shared helper would have little to parameterize.

Original funded: True; matched baseline funded: False; residual veto retains pair: False. Original answer is reused only as the stated selector counterfactual. Native concept/Haiku outcomes are not inferred from it.

## OBR2-BASE-a47dd85172b0

Timeout normalization baseline control

Source assessment: **useful**. Proposed scope and preserved behavior:

```json
{
  "extract": "Share only the timeout coercion policy via a neutral lower utility, reusing/lifting the existing fine-tuning resolver where behavior matches. Pass the already chosen raw timeout and resolved provider at the original points. Keep provider inference order/failure handling, credentials, API request models, file streaming and dispatch local.",
  "negative_scope": null,
  "preserve": [
    "optional timeout then request_timeout then 600 truthy fallback",
    "supported-provider httpx.Timeout preservation and read fallback/float coercion",
    "provider inference timing, including file raw-timeout selection before inference",
    "None provider behavior where currently accepted",
    "batch metadata/async flags versus file streaming/chunk/client/request data"
  ]
}
```

**jev:** separate 0.2; fixed .8 diagnostic report: False.

> The functions implement different concepts.

**claude:** duplicate 0.8; fixed .8 diagnostic report: True.

> Both functions repeat the same timeout normalization operation. They compute `optional_params.timeout or kwargs.get('request_timeout', 600) or 600`, then apply the same policy: an `httpx.Timeout` is collapsed to its `.read` value (default 600) when `supports_httpx_timeout(provider)` is False, any non-Timeout value is converted with `float()`, and None becomes 600.0. This is a concrete reusable helper, e.g. `resolve_request_timeout(optional_params, kwargs, custom_llm_provider) -> float | httpx.Timeout`. Provider resolution, request construction, and provider dispatch stay in the callers. A second, weaker overlap is the OpenAI-compatible credential resolution. `file_content` already delegates it to `get_openai_credentials` and `get_azure_credentials`, while `cancel_batch` inlines the same fallback chains, so `cancel_batch` could reuse those existing helpers. The Vertex project, location, and credentials lookup is also repeated inline in both functions. The rest of each function is provider-routing orchestration that differs and is not part of the overlap.

Original funded: True; matched baseline funded: True; residual veto retains pair: True. Original answer is reused only as the stated selector counterfactual. Native concept/Haiku outcomes are not inferred from it.
