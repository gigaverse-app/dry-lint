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

## Not covered

- Data-model duplication: record fields, table schemas and Luau type aliases are not extracted as models. Methods
  attached to tables are compared as functions; there is no `luau-models` extractor in this release.
- `.rbxl`, `.rbxm` and `.model.json` files: they are not source. Run dry-lint on the Rojo project, not the place file.
- Requires are not resolved across files; `local_calls` stays within one file.
- Luau types are ignored, so two functions that differ only in their annotations are one function.
