# Plugins

dry-lint has four plugin slots. Each is a small protocol in `src/dry_lint/plugins.py`. A plugin is any class that
implements one; nothing needs to inherit from dry-lint.

| Slot | Settings key | Built in | Entry-point group |
| --- | --- | --- | --- |
| Extractor | `extractors` (a list, one per language) | `python`, `typescript`, opt-in `luau` ([Luau and Roblox](luau.md)), `python-models`, `typescript-models`, opt-in `luau-models` | `dry_lint.extractors` |
| Comparer | `comparer` | `tfidf`, optional `dryer`, opt-in `model-shape`, `operation-blocks`, optional `cpu-embedding`, `cpu-tail-rrf` | `dry_lint.comparers` |
| Judge | `judge`, `escalate` | `jev`, opt-in `jev-models`, `command` (and `auto`, `none`) | `dry_lint.judges` |
| Store backend | `store` | `dir`, `s3` | `dry_lint.stores` |

A slot takes a name, or a table whose `use` names the plugin and whose other keys are passed to its constructor:

The Anthropic judge accepts opt-in `prompt_policy = "shared-operations"` or `"shared-operations-compact"` and
`max_tokens` constructor options. The [compact-policy experiment](four-cent-discovery.md) uses a 512-token cap.
See the [configuration and measurements](protected-exploration.md); legacy judging remains the default, and
experimental prompt answers have a distinct cache identity.

The frozen `shared-operations-grounded-claim-v1` policy is also selectable on the existing Anthropic plugin.
Use `discovery.residual_judge` to apply it only to newly funded recovery questions while retaining the original
protected judge. See [recovery configuration and exact identity](production-discovery.md#optional-recovery-judge).
This optional slot uses the same name/table constructor contract as `judge`; it does not add a plugin group.

The [model duplication profile](model-duplication.md) adds mechanical field retrieval and an optional
`model-contracts` prompt. Model declarations allow same-file neighbours; function defaults are unchanged.
Run function and model extraction of the same language in separate invocations.

```toml
[tool.dry-lint]
extractors = ["python", "typescript"]
comparer = { use = "embedding", model = "jinaai/jina-embeddings-v2-base-code" }
judge = "jev"
escalate = { use = "command", command = "claude -p --model sonnet", version = "sonnet-1", between = [0.6, 0.8] }
store = { use = "s3", uri = "s3://my-bucket/dry-lint/my-repo" }
```

## Registering one

Publish the class under the slot's entry-point group:

```toml
# your package's pyproject.toml
[project.entry-points."dry_lint.comparers"]
embedding = "my_package.comparer:EmbeddingComparer"
```

Install it next to dry-lint (`uvx --from dry-lint --with my-package dry-lint check`) and name it in the settings.
In CI, install plugins in the judge job from the workflow, not from settings a pull request could change.

## Extractor

```python
class Extractor(Protocol):
    name: str
    version: str
    files: tuple[str, ...]  # fnmatch globs over paths, e.g. ("*.ts", "*.tsx")

    def functions(self, path: str, source: str) -> list[Function]: ...
    def structure_hash(self, function: Function) -> str: ...
```

`functions` returns every function in a file, with `tokens` filled in if your comparer uses them; leave `hash`
empty. `structure_hash` must change when the logic changes and not for comments or formatting. Normalize
renames only when the language's binding rules make that safe; conservative re-judging is preferable. Core
calls it only for the functions in a candidate pair. `owner` is the enclosing class, if any.

### Language integration capabilities

An extractor can declare its integrations once, on the class. Core consumes these capabilities without checking
language names or suffixes. No base class is required; existing protocol-only plugins continue to work.

```python
from dry_lint.extractor_capabilities import ExtractorCapabilities


class ExampleExtractor:
    name, version = "example", "1"
    files = ("*.example",)
    capabilities = ExtractorCapabilities(
        language_name="Example",
        comment_prefix="//",
        model_extractor="example-records",
        index_modules=("my_package.syntax",),
        index_distributions=("my-parser-package",),
    )
    # Implement functions(), structure_hash(), and validate_source() as above.
```

Register both extractors in `dry_lint.extractors`. `model_extractor` names a companion plugin; that companion
sets `is_model=True` and `model_extractor=None`. It can use any plugin name, without a `-models` suffix. The
automatic model pass retains the default languages' model coverage and adds companions of configured extractors,
deduplicating names. Companion construction uses its own defaults; function-only options such as `min_lines`
are not passed to it. Explicit model-only configurations retain their options and never trigger a second pass.

`language_name` and `comment_prefix` supply inline-suppression instructions and directive recognition.
The comment prefix describes a line-comment marker; it does not parse the language's syntax. Plugins without
capabilities keep `#`, no automatic companion and the legacy `-models` convention.
Previously accepted built-in comment markers remain recognized in inline decisions, including across file types.

The extraction index fingerprints each configured extractor's Python implementation, its base classes, declared
`index_modules`, and installed `index_distributions` versions. Dependencies declared by base classes are included
even when a subclass replaces the descriptor. Declare helper modules and parser distributions whose changes can
change extraction. Unconfigured optional adapters contribute no parser dependency. This invalidates indexes;
plugin versions and structure/context hashes still own verdict reuse.

The public comparison viewer discovers installed extractors by `files`, constructs the matching adapter and its
companion with default options, and resolves functions and records from one source read. It never reads or installs
plugins from adopter settings. Missing dependencies, required constructor options or missing strict validation mean
the survivor is unknown, not deleted. An optional `comparison_helpers(source, caller) -> list[Function]` hook can
provide bounded same-file helper references; Python supplies this hook.

Model plugins use a nonempty, stable `Declaration.kind` string of their own, such as `go-struct`; core does not
enumerate language families. Adding a future Go plugin requires its parser adapter, capability descriptor and
entry-point registration. This interface does not itself implement Go parsing.

### Language analysis

The extractor is also the language adapter: return optional `Function.analysis` using the canonical
`LanguageAnalysis` model. No new engine or plugin slot is required. Core owns comparison, exclusions, ranking,
judging, budgets, caching and reports; adapters own syntax and binding conventions.

| Fact | Adapter contract | Shared policy |
| --- | --- | --- |
| `language`, `version` | Identify the analysis contract; bump version when facts change | Included in cache evidence |
| `convention` | A recognized language convention; Python emits `python-special-method` for class dunders | Only matching conventions in the same language settle a pair |
| `forward_target` | `path::Owner.method` for a same-owner forwarding body with no additional policy | Settle only against that exact declaration in the same repository |
| `local_calls` | `path::qualified` targets of direct calls that bind inside the file (own-class methods via `self`/`cls`/`this`; unshadowed Python module functions) | Settle "one calls the other" against those exact declarations; never verdict evidence, so excluded from `context_hash` |
| `declared_override` | Explicit override syntax, without claiming a resolved runtime target | Evidence, never an automatic exclusion |
| `Function.bases` | Syntactically named direct base references; unresolved imports may be absent | Evidence, never an automatic exclusion |

`forward_target = None` means unestablished, not proof that no call exists. The built-ins conservatively recognize
single receiver calls with unchanged parameter arguments, including awaited calls and direct TypeScript class arrow
fields. Computed arguments, nested callbacks, decorators, parameter initializers, constructors and wrapped arrows
(such as debounced fields) do not qualify. Bare/imported
calls, inherited dispatch and TypeScript package/path aliases are not resolved. Function-valued object fields
are not assumed to bind `this` like class arrow fields. No project dependencies are installed or executed.

`local_calls = ()` likewise means unresolved. It is consulted only to settle a pair before lookup, so it stays out of
`Candidate.context_hash`: adding or changing it never voids a stored verdict or an accepted baseline entry, and a
changed call reopens or settles the pair through the rule instead.

Legacy extractors keep working without analysis; their candidates reach the judge instead of core guessing
relationships with regular expressions. `calls` remains syntax data for inspection. Candidate/report schema 9 and
function-index schema 2 preserve analysis and bases. Changing either invalidates contextual verdict reuse.
An adapter should emit facts through `functions()`, never implement its own `should_skip_pair()` policy.

To support strict checks and repository sweeps, also implement `validate_source(path: str, source: str) -> None`.
Raise `ValueError` on invalid or incompletely parsed source. Strict scans reject extractors without this optional
capability; ordinary candidate-only scans retain their previous plugin behavior. Both built-in extractors support it.

## Comparer

```python
class Comparer(Protocol):
    name: str
    version: str  # bump when similarities change meaning

    def index(self, functions: list[Function]) -> None: ...
    def neighbours(
        self, function: Function, k: int, allowed: Callable[[Function], bool]
    ) -> list[tuple[Function, float]]: ...
    def similarity(self, a: Function, b: Function) -> float: ...
```

`neighbours` returns up to `k` indexed functions for which `allowed` holds (core passes "in another file"), most
similar first and above the comparer's own floor. Similarities are only compared with stored ones of the same
`name:version`, so a new version never reuses the "not closer" rule on old numbers. Comparers can opt into that rule with
`similarity_reusable = True`; the safe default is false. Both the candidate and the stored record must permit it.
The built-in comparers do not opt in: TF-IDF tokens and Dryer's normalization both leave out literals, so a changed
literal can make two functions one concept without moving the score. An optional
`shared(a, b) -> list[str]` feeds `dry-lint explain`.

Measure it before switching: `dry-lint bench --gold gold.jsonl --comparer` reports how often each gold duplicate's
partner is among the proposed neighbours.

`discovery.comparers` accepts a list of comparer choices, each with an optional `neighbours` limit. Other
options go to the comparer constructor. With discovery enabled, independent indexes add previously unseen
pairs to the exploration lane without replacing baseline pairs. The first route to retrieve a pair owns its
score and comparer identity; scores from different comparers are not averaged. An empty list preserves legacy
TF-IDF exploration. See the [model configuration](model-duplication.md) for bounded TF-IDF and wider Dice routes.

A comparer may set `discovery_unseen = True` to apply its discovery cap after excluding pairs already owned by
earlier routes and pairs settled by core rules. Core supplies these exclusions through `allowed`; the comparer
must apply it before taking `k`. Without this opt-in, existing raw-neighbour caps remain unchanged. Neither route
can replace protected baseline candidates or transfer its score to an earlier route.

### Bounded Python operation blocks

Start with the [worked operation-block example](operation-blocks.md) for why this method can find a helper inside
a larger workflow, when to use it, and the measured limits. The [comparer selection guide](discovery-comparers.md)
explains route ordering and how to run a fair repository trial. This section specifies the plugin contract.

`operation-blocks:3` retrieves complete native Python functions by shared operation regions. It supports Python
functions with parseable source and valid source coordinates, not model declarations or other languages. Candidates
retain their complete signature, documentation, source, hashes and context. Region cosine is a retrieval score,
not a duplication verdict, and cannot authorize reuse of stored verdicts.

This opt-in configuration preserves the evaluated route order: the normal three-neighbour baseline, existing
TF-IDF exploration at .35 with a raw cap of 20, then at most one unseen, unsettled block pair per changed function:

```toml
[discovery]
enabled = true
comparers = [
  { use = "tfidf", min_similarity = 0.35, min_similarity_small = 0.35, neighbours = 20 },
  { use = "operation-blocks", neighbours = 1 },
]
```

An explicit comparer list replaces implicit TF-IDF exploration, so retain the first entry when adding blocks to
that policy. Discovery permits same-file pairs. This example changes no budget or admission defaults; actual
funding still depends on the adopter's ledger, pricing and configuration. Frozen synthetic budget diagnostics
do not establish deployment report gains. Provider answers and source adjudication remain separate.

Regions are whole compound statements or maximal consecutive straight runs of at least two statements. Nested
functions/classes and string-expression boundaries split runs; no region includes a nested owner. Compound suites
are visited through depth three. Regions must span 4–80 lines and 20–400 executable AST nodes, contain at least
eight distinct behavior tokens and two distinct nongeneric calls. Oversized regions are rejected, never split into
windows. At most 12 regions survive in source order. If this original route finds no eligible winner, a second
index adds at most one whole helper body, subject to the same guards and excluding its docstring and nested
owners. Independent postings preserve the first route; this fallback keeps at most 13 regions.

The complete indexed function-token background supplies TF-IDF (max document frequency .3) and anchor frequencies;
blocks and standalone queries never refit it. Each region keeps at most eight concrete call/attribute/key anchors
whose function frequency is at most `min(128, max(2, floor(.01 * functions)))`. An anchor with more than 64 region
postings is dropped entirely. At most 6,144 posting visits in the original route, or 6,656 in the fallback,
select 64 parents. The fallback compares at most 64 × 13 × 13 region pairs. A region pair needs three shared
concrete operations, two shared nongeneric calls and a retained shared anchor. Region cosine must reach .65 and
whole-function cosine .1. Results deduplicate native parent identities and break score ties by qualified name,
then original position. `similarity(a, b)` applies the same guards and floors directly; neighbour retrieval also
requires membership in the bounded anchor pool. These scores have their own comparer identity and are never
substituted for TF-IDF scores.

### Offline CPU embeddings

The optional [`cpu-embedding` comparer](cpu-embedding.md) uses adopter-supplied pinned MiniLM artifacts and an
optional local vector cache. It retrieves complete functions, requires the `cpu-embedding` installation extra,
and never downloads weights or judges candidates. Cold indexing is expensive; the measured benefit depends on
the preceding retrieval routes. See the [measured profile comparison](benchmark.md#offline-cpu-discovery).

### Optional run resources

The detector creates a `ComparerResources` scope for the discovery routes in each `candidates()` call. A comparer may implement `for_run(resources, **options)` for construction and `index_for_run(functions, resources)` for indexing. Existing plugins need neither hook. `resources.get(key, factory)` publishes only successfully constructed values; core never inspects a value or calls an encoder itself.

Plugins own exact reuse keys and must preserve source edits, native identity/order, validation and transactional reindex behavior. Share prepared resources only; query caches must stay private. The scope is confined to one synchronous detection call, never shared by concurrent calls. A plugin must not retain the scope globally or export it to concurrent query workers. This API does not make a comparer instance thread-safe. Built-in CPU recovery revalidates model files on each constructor and shares vectors only when the explicit cache path and complete encoder contract match. No file schema or verdict reuse rule changes.

The [CPU recovery setting](cpu-recovery.md) supplies the evaluated stack without exposing its route limits as setup choices.

## Judge

```python
class Judge(Protocol):
    name: str  # e.g. "jev", "command:claude"
    version: str  # model and prompt version

    def judge(self, candidates: list[Candidate], settings: Settings) -> list[Verdict]: ...
```

One verdict per candidate, in order. Use `dry_lint.judges.label_for(score, behaves_differently, settings)` so
labels follow the configured thresholds. A judge that cannot tell drift or ownership leaves
`behaves_differently` at 0 and `owner` empty. Raise on failure rather than guessing: a missing answer is asked
again next run, while a wrong one is stored.

An optional `input_text(candidate) -> str` exposes the actual serialized request for budget estimation. Jev
implements it so typed questions and policies are counted. Scheduled discovery reserves a conservative input
byte bound and requires either a finite output ceiling or a zero output-token price. Actual token usage settles
the reservation when the provider supplies it; missing usage retains the reservation charge.

`jev-models` returns `Verdict.model_assessment` with six independent facts. The report keeps these pairs in the
coding-agent review queue regardless of score. It uses strict prompt/model version reuse. Explicitly configure
`escalate = "none"` for this workflow; a deliberately configured second judge replaces the first verdict under
the ordinary escalation contract. Local context is optional and does not resolve cross-file types or callers.

For a judge written in another language, the built-in `command` judge runs any program with
`input = "candidate"`: one candidate as a JSON line on stdin, one JSON verdict on stdout. See
[judges.md](judges.md).

## Store backend

```python
class StoreBackend(Protocol):
    def get(self, key: str) -> bytes | None: ...
    def put(self, key: str, data: bytes) -> None: ...
    def keys(self) -> Iterator[str]: ...
```

Opaque bytes by key. The record format and the reuse rules stay in core (`store.py`), so a backend never decides
whether a verdict holds.

## Offline signal experiments

Before changing a comparer, try the [semantic signal trial](semantic-signal-trial.md). Its standalone scripts
exercise the existing comparer/detector contracts without registering a runtime plugin or changing defaults.
The report includes fresh judgments from two repositories and regressions that prevented default adoption.

## Dryer

The optional [Dryer comparer](detectors.md) uses upstream structural normalization and Jaccard similarity.
See its [backend comparison](dryer-comparison.md) before selecting it as a default.
