# Luau adapters: combined review and OSS CLI probe

Keep the adapters opt-in with their explicit scope. The combined review of PRs #191 and #197 found three
correctness problems that synthetic coverage had missed: computed method keys invented bindings, whitespace in
dotted owners dropped methods, and exports of existing functions were counted as data fields. The fixes preserve
the positive copy/drift probes while removing the observed false evidence. They do not add runtime class inference.

## What was tested

The question was whether the packaged CLI extracts useful functions and declared records from ordinary library
code, then detects a copied implementation without mistaking existing reuse for a new data model. A failure to
retrieve a deliberately copied function/record, a lost declaration after a layout-only edit, or a candidate based
only on reused methods would refute that claim.

Both arms used fresh Windows/Python 3.14.7 environments installed from built wheels with the `luau` extra.
The parser was tree-sitter 0.25.2 with tree-sitter-luau 1.2.0. The before wheel came from `625ea0b`, with function
adapter version 2 and model adapter version 1. The corrected adapters are versions 3 and 2. No adopter source
executed, no judge or provider was called, and no change was pushed to either upstream repository.

| Pinned source | Included files | Source lines | Functions, both arms | Explicit models, before / after |
| --- | ---: | ---: | ---: | ---: |
| [kikito/bump.lua, 95d9e40](https://github.com/kikito/bump.lua/tree/95d9e40b8aee295fc9d9b78ca214a829d6c21555) | `bump.lua` | 773 | 48 | 3 / 1 |
| [Sleitnick/RbxUtil, 31f9120](https://github.com/Sleitnick/RbxUtil/tree/31f9120fca021e3dec275b42bc7047d626962082) | Signal, Quaternion and Spring implementations | 1,099 | 42 | 2 / 2 |

These inventories are observations, not independently measured extraction recall. The smaller bump model
inventory is the intended correction: `bump.rect` and `bump.responses` contain reused methods, while `bump` itself
contains four metadata fields. In RbxUtil, Quaternion contributes X/Y/Z/W and Connection contributes Connected.
The one-field Connection cannot meet the model comparer's two-shared-field minimum. Spring's five-field
`typeof(setmetatable(...))` type and constructor-based instance fields remain outside the declared support scope.

## Paired results

Each arm used the same four pinned implementation files, default retrieval thresholds and explicitly selected
Luau extraction. The CLI ran `detect --all`, then `detect --base` and `check --base --judge none` against local
commits containing labeled mutations. Source digests, candidates, reports and command logs were retained outside
the source PR. The two adapter identity checks below use the real parser directly on controlled transformations.

| Probe / metric | Before | After | Desired direction |
| --- | ---: | ---: | --- |
| Copied bump functions retrieved | 2 / 2 | 2 / 2 | Retain both |
| Copied Quaternion record retrieved | 1 / 1 | 1 / 1 | Retain it |
| Reused response-table model candidates | 1 | 0 | Lower |
| Functions after adding spaces to a dotted namespace | 30 / 48 | 48 / 48 | Retain all |
| Invented callable from a computed table key | 1 | 0 | Lower |
| Changed copied contracts with changed hashes | 2 / 2 | 2 / 2 | Invalidate both |
| Candidates involving the two unrelated control records | 0 | 0 | Remain zero |

The copied functions are `rect_getDiff` and `rect_isIntersecting`, placed unchanged in a second file. The copied
record retains Quaternion's complete declaration and changes its declaration name. Each intended pair has
similarity 1.0. A later arithmetic edit to the copied rectangle difference and a number-to-string edit to the
copied Quaternion field remain candidates while changing their structural hashes. Two unrelated records with
temperature/active fields provide negative controls. These few labeled mutations are not a precision/recall benchmark.

Unmodified scans yielded no pairs. That result is limited: normal function retrieval excludes same-file pairs,
and each library's methods mostly live in one file. It does not establish that those libraries have no duplication.

## Findings and enforcement

1. **Computed keys must not prove callable identities.** A table member `[key] = function(value) ... end` used
   to become `handlers.key`. A later `handlers.key(value)` then acquired a false local-call relationship and
   could suppress review through the shared caller/callee rule. The adapter now resolves only static field names
   through parser nodes. The function and model extractors share this resolver.
2. **Whitespace must not remove declarations.** In a controlled bump namespace transformation,
   `function A.World:move(...)` retained all 48 functions, but `function A . World:move(...)` lost the 18 World
   methods. `dotted()` now walks identifier/dot nodes instead of validating the receiver's source spelling.
3. **Function registries represent existing reuse.** The real bump exports are references to functions already
   defined in the file. A second view of those same functions must not become a copied data model:

   ```lua
   local responseAliases = {
       touch = touch, cross = cross, slide = slide, bounce = bounce,
   }
   ```

   Before the fix, CLI detection paired this with `bump.responses` at 1.0. The adapter now snapshots known
   callable bindings before each statement, handles simultaneous assignments using the previous snapshot, and
   excludes proven callable values. Reassignment, uninitialized shadowing, conditional writes and initializer
   calls invalidate evidence conservatively. Unresolved values remain review evidence rather than being discarded.

Five function-adapter cases and three model-binding cases were observed failing before their fixes and passing
afterward. The tests also replaced a vacuous member-hash assertion with explicit cosmetic-stability and
behavior-change controls. Adapter versions advance so earlier analysis cannot be reused under the corrected rules.

Repository CI subsequently identified duplicated structural-hash plumbing between TypeScript and Luau. Both
adapters now delegate parsing, wrapper fallback, serialization and digest construction to one Python helper.
Each adapter still supplies its own grammar, canonicalization, syntax-error predicate and hash namespace.
Three captured hash identities cover a Lua table method, a typed record and a TypeScript class method; they
remain unchanged across this consolidation. The shared helper also participates in index invalidation.
Rebuilding and reinstalling the wheel after consolidation produced an identical corrected OSS probe summary.

## Reproduce with the packaged CLI

From a checkout of the desired dry-lint revision, build its wheel and install it into a fresh environment:

```bash
uv build
uv venv /tmp/luau-probe-env
uv pip install --python /tmp/luau-probe-env/bin/python 'dist/dry_lint-1.11.0-py3-none-any.whl[luau]'
/tmp/luau-probe-env/bin/python scripts/probe_luau_oss.py --workspace /tmp/luau-oss-probe
```

Use `Scripts/python.exe` for a Windows environment. The workspace must be a new directory. The script fetches
the exact public commits, selects the documented implementation files, writes the configuration, creates local
mutation commits, invokes the installed CLI and writes `summary.json`, command logs, candidate JSON and reports.
Run the same script through the before and after interpreters with separate workspaces to repeat the comparison.
The script requires network access for Git fetch but no credentials or model provider. It deliberately does not
assert that the before arm succeeds on corrected invariants, so both observations remain inspectable.

The reusable [probe script](../../scripts/probe_luau_oss.py) is manual and outside the offline unit suite. Its
small minimized regressions are in `tests/test_luau.py`, `tests/test_luau_models.py` and `tests/test_comparison.py`.
The review comments on [#191](https://github.com/gigaverse-app/dry-lint/pull/191#issuecomment-6824354824) and
[#197](https://github.com/gigaverse-app/dry-lint/pull/197#issuecomment-6824355674) record the original findings.

## Decision and limits

The measured fixes justify retaining the parser-based Python adapters and their existing opt-in interface.
The function-adapter PR has merged; the model follow-up still requires CI. Explicit record contracts work; general Lua class/dataclass libraries,
metatable-generated layouts, cross-file aliases and runtime instance dataflow remain unresolved. The probe did
not run Roblox, the upstream applications, provider judging or a GitHub Actions installation. It establishes
packaged CLI behavior on these sources, not production-wide model ownership accuracy or general Lua-dialect support.
