# Plugins

dry-lint has four plugin slots. Each is a small protocol in `src/dry_lint/plugins.py`. A plugin is any class that
implements one; nothing needs to inherit from dry-lint.

| Slot | Settings key | Built in | Entry-point group |
| --- | --- | --- | --- |
| Extractor | `extractors` (a list, one per language) | `python`, `typescript` | `dry_lint.extractors` |
| Comparer | `comparer` | `tfidf`, optional `dryer` | `dry_lint.comparers` |
| Judge | `judge`, `escalate` | `jev`, `command` (and `auto`, `none`) | `dry_lint.judges` |
| Store backend | `store` | `dir`, `s3` | `dry_lint.stores` |

A slot takes a name, or a table whose `use` names the plugin and whose other keys are passed to its constructor:

The Anthropic judge accepts opt-in `prompt_policy = "shared-operations"` and `max_tokens` constructor options.
See the [configuration and measurements](protected-exploration.md); legacy judging remains the default, and
experimental prompt answers have a distinct cache identity.

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
    files: tuple[str, ...]          # fnmatch globs over paths, e.g. ("*.ts", "*.tsx")

    def functions(self, path: str, source: str) -> list[Function]: ...
    def structure_hash(self, function: Function) -> str: ...
```

`functions` returns every function in a file, with `tokens` filled in if your comparer uses them; leave `hash`
empty. `structure_hash` must change when the logic changes and not for comments or formatting. Normalize
renames only when the language's binding rules make that safe; conservative re-judging is preferable. Core
calls it only for the functions in a candidate pair. `owner` is the enclosing class, if any.

## Comparer

```python
class Comparer(Protocol):
    name: str
    version: str                    # bump when similarities change meaning

    def index(self, functions: list[Function]) -> None: ...
    def neighbours(self, function: Function, k: int,
                   allowed: Callable[[Function], bool]) -> list[tuple[Function, float]]: ...
    def similarity(self, a: Function, b: Function) -> float: ...
```

`neighbours` returns up to `k` indexed functions for which `allowed` holds (core passes "in another file"), most
similar first and above the comparer's own floor. Similarities are only compared with stored ones of the same
`name:version`, so a new version never reuses the "not closer" rule on old numbers. Comparers can opt into that rule with
`similarity_reusable = True`; the safe default is false. Both the candidate and the stored record must permit it.
TF-IDF opts in; Dryer requires unchanged code hashes because its normalization erases literals and field names. An optional
`shared(a, b) -> list[str]` feeds `dry-lint explain`.

Measure it before switching: `dry-lint bench --gold gold.jsonl --comparer` reports how often each gold duplicate's
partner is among the proposed neighbours.

## Judge

```python
class Judge(Protocol):
    name: str                       # e.g. "jev", "command:claude"
    version: str                    # model and prompt version

    def judge(self, candidates: list[Candidate], settings: Settings) -> list[Verdict]: ...
```

One verdict per candidate, in order. Use `dry_lint.judges.label_for(score, behaves_differently, settings)` so
labels follow the configured thresholds. A judge that cannot tell drift or ownership leaves
`behaves_differently` at 0 and `owner` empty. Raise on failure rather than guessing: a missing answer is asked
again next run, while a wrong one is stored.

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
