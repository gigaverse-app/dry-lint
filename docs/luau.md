# Luau and Roblox

dry-lint reads Luau (`.luau` and `.lua`) with the opt-in `luau` extractor. Roblox projects are where a coding agent
most often writes a second `clamp`, a second `GetService` wrapper or a second remote-event helper next to the one that
already exists, so the extractor treats the Roblox idioms as behaviour.

```bash
pip install 'dry-lint[luau]>=1,<2'
```

```toml
# .dry-lint/config.toml
extractors = ["luau"]
exclude = ["Packages/*", "ServerPackages/*", "DevPackages/*", "*/Packages/*", "*/tests/*"]
```

`extractors` takes one entry per language, so a repository that mixes languages lists them all:
`["python", "typescript", "luau"]`. Luau is not in the default list: the default scope stays Python and
TypeScript. Installing the parser alone does not enable Luau extraction.

## What it extracts

| Source | Name | Owner |
| --- | --- | --- |
| `local function f()` / `function f()` | `f` | none |
| `function Module.f()` / `function Module:f()` | `f` | `Module` |
| `local f = function() ... end` | `f` | none |
| `Module.f = function() ... end` | `f` | `Module` |
| `local t = { f = function() ... end }` | `f` | `t` |

Nested functions and callbacks (`pcall(function() ... end)`, `:Connect(function() ... end)`) stay part of the function
that contains them. Functions shorter than `min_lines` (default 2) and empty bodies are skipped.

## What counts as behaviour

- Calls, attributes, identifiers and table keys, the same way the Python and TypeScript extractors count them.
- `game:GetService("X")` adds `service:x`, and `Instance.new("X")` adds `instance:x`, so two functions that build a
  `Part` and parent it look alike even when their variable names do not.
- `pcall` and `xpcall` count as error handling (`ctl:try`); `task.wait`, `wait`, `:Wait()` and `coroutine.yield`
  count as yielding (`ctl:await`); `for`, `while` and `repeat` count as loops.
- Type annotations (including named types), casts (`::`), type aliases and comments never count, and never change
  a structure hash. Python walks the parser's grammar fields to separate types from runtime identifiers and unwraps
  casts to their runtime expression; it does not strip types with regular expressions.

The judge is also given the file's top-level `local X = require(...)` and `local X = game:GetService(...)` lines for
the names the function uses, so it can tell what `Players` or `Util` is.

## Language facts

- `local_calls` resolves `self:method()` inside a colon-declared method, `Owner.method()` and a bare call to a
  function defined in the same file. Parameters, local declarations, loop bindings and reassignments invalidate
  those bindings conservatively. Calls through complex receivers such as `config.nested.helper()` contribute
  similarity tokens but never prove a call to a file-local `helper`.
- `forward_target` is set for a `function Owner:name(...)` whose whole body is `self:other(...)` over unchanged
  parameters.
- `convention` is `luau-metamethod` only for recognized callable metamethods such as `Owner.__index` and
  `Owner.__tostring`. Ordinary helpers such as `Owner.__normalize` remain candidates.
- Structure hashes keep binding names, so a rename is judged again rather than reused.

## Comments

Prefer reviewed pair exceptions with reasons in `.dry-lint/ignore.yaml` ([configuration](configuration.md)).
Inline exceptions remain supported. Luau comments start with `--`:

```lua
-- dry-lint: distinct-from src/shared/Text.luau::shortenText
-- dry-lint: ignore
```

## Record and table model shapes

Enabling `luau` also includes `luau-models` in the automatic model pass. It uses the same parser through Python,
then sends explicit field names to the existing `model-shape` comparer. For example:

```lua
export type Receipt = { receiptId: string, amount: number }
type ReceiptCopy = { receiptId: string, amount: number }
local Defaults = { receiptId = "example", amount = 0 }
```

These three shapes share two field names and are eligible for review, including within one file. Retrieval uses
field-name overlap; a judge or coding agent checks whether they share ownership or need independent contracts.
Types, optionality, nested constraints, defaults and complete declarations remain review evidence. Editing them
changes model hashes; editing same-file usage changes context digests and reopens cached review.

| Form | Model evidence |
| --- | --- |
| Top-level `type` / `export type`, including generics | Direct named fields in object types and intersections |
| Named top-level table literals, including `Module.Options = {...}` | Explicit data fields and plain quoted string keys |
| Nested record/table literal | One outer field; its source remains evidence |
| Function-valued fields and recognized metamethod metadata | Excluded from field overlap; retained in declaration source |
| Type/value bindings with the same name | Separate identities, e.g. `models.luau::<type>.Receipt` and `models.luau::<table>.Receipt` |

The automatic pass keeps function and model comparison separate. Use `--no-models` to disable it, or configure
a standalone model scan with `extractors = ["luau-models"]` and `comparer = "model-shape"`. Do not put both Luau
extractors in one list: a file goes to the first matching extractor. See [model adoption](model-adoption.md).

Lua class libraries and dataclass-like factories have no universal record syntax. This adapter reads their
explicit table/type declarations but does not infer instance fields from constructors, `setmetatable`, `typeof`,
inheritance or imported aliases. It also skips nested declarations, arrays, type unions and computed keys.
Plain string keys are supported; escaped and interpolated keys remain unresolved. No repository code executes.

## Not covered

- `.rbxl`, `.rbxm` and `.model.json` files: they are not source. Run dry-lint on the Rojo project, not the place file.
- Requires are not resolved across files; `local_calls` stays within one file.
- Function behavior ignores Luau types, so two functions that differ only in annotations have the same structure
  hash. Model hashes preserve types because those are part of a data contract.
