# Representative original answers

These are selected illustrations, not a precision sample. Labels from source review are separate from model answers. All nine pairs are in [recordings](data/recordings.json).

## Tiny file-mutation predicate: uncertain in both arms

`AJ-R2-294585ab744e5e23`; source assessment: **duplicate / narrow_actionable_extraction**.

**Corrected body-only:** separate, score 0.3, uncertainty True, reported None.

> Both treat edit/delete/move as one group, but for different purposes. NEW is a boolean mutation predicate. EXISTING is a full kind-to-canonical-item-type mapping that also covers read, execute, search and fetch. The overlap is a small literal set, and the source doesn't show that the two policies must stay in sync. A shared constant is possible but not clearly warranted.

**Source tools:** separate, score 0.3, uncertainty True, reported None.

> Both functions list edit/delete/move, but for different contracts. NEW is a boolean predicate that the policy code uses to gate workspace-write and approval decisions. EXISTING is a total mapping from ACP tool kind to canonical lifecycle item type (read, execute, search/fetch and a default). The overlap is only a small literal kind set, and the mapping would not get simpler by calling the predicate.

Inspect full source, exact prompt, citations and tool results: `python3 reproduce.py --case AJ-R2-294585ab744e5e23`.

## Test-tool factory: a useful report already covered body-only

`AJ-R2-79b342568fc7ba88`; source assessment: **duplicate / narrow_actionable_extraction**.

**Corrected body-only:** duplicate, score 0.9, uncertainty False, reported True.

> Both tools() methods independently perform the same operation: require self.cwd, raise the same ValueError if unset, register BashTool and FileEditorTool, and return identical ToolSpecs (BashTool working_dir=cwd, FileEditorTool workspace_root=cwd). A shared base-class or helper could own this, with tool lists overridable by tests.

**Source tools:** duplicate, score 0.9, uncertainty False, reported True.

> Both tools() methods are identical: require cwd, register BashTool and FileEditorTool, and return the same two ToolSpecs with working_dir/workspace_root set to cwd. The same registration lines appear in other integration tests (t03–t07). A shared base-class default or helper taking cwd and extra tools could own it. Tests that need different tools can override it.

Inspect full source, exact prompt, citations and tool results: `python3 reproduce.py --case AJ-R2-79b342568fc7ba88`.

## Plugin contexts: source resolves uncertainty to non-report

`AJ-R2-54b6abcd0f86aeb6`; source assessment: **separate / negative**.

**Corrected body-only:** separate, score 0.25, uncertainty True, reported None.

> Both are the generic "useContext, throw if provider missing" accessor. The supplied source doesn't show that they read the same PluginContext. Each has its own provider-specific error message ("PluginProvider" vs "PluginContextProvider"). It's a small idiom, not an established reusable domain operation.

**Source tools:** separate, score 0.12, uncertainty False, reported False.

> Both are tiny useContext-or-throw hooks, but each reads its own private context (different value types: host Value vs plugin Context) with different error messages. Sharing would only be a generic context-guard idiom, not a domain operation worth extracting.

Inspect full source, exact prompt, citations and tool results: `python3 reproduce.py --case AJ-R2-54b6abcd0f86aeb6`.

## Proxy URLs: distinct helper contracts

`AJ-R2-9d94b5ed1e94eaf2`; source assessment: **related / related**.

**Corrected body-only:** separate, score 0.15, uncertainty True, reported None.

> Both read the configured proxy base URL, but each already delegates to a different helper (_resolve_proxy_base_url_env vs get_custom_url). NEW returns None when unset; EXISTING falls back to the request base_url. The visible bodies don't show repeated executable policy beyond delegation, so the difference reads as legitimate caller variation.

**Source tools:** separate, score 0.12, uncertainty False, reported False.

> NEW is a thin wrapper over _resolve_proxy_base_url_env and returns only the validated PROXY_BASE_URL or None. EXISTING delegates to get_custom_url, which falls back to the request base URL and appends the request root path. These are different contracts, and neither function contains repeated executable policy.

Inspect full source, exact prompt, citations and tool results: `python3 reproduce.py --case AJ-R2-9d94b5ed1e94eaf2`.
