# Judges

A judge is a plugin ([plugins.md](plugins.md)), chosen with `judge = ...` in the settings or `--judge` on the
command line:

| Judge | What it is | Cost |
| --- | --- | --- |
| `auto` (default) | Jev when `TYPESAFE_AI_API_KEY` is set, otherwise `none` | |
| `jev` | TypeSafe's System One decision model, prompt `reuse-v2` | about 0.3 s per pair, 8 pairs in parallel |
| `command` | Any program: the prompt (or the candidate as JSON) on stdin, a JSON verdict on stdout; 4 at once | whatever your model costs |
| `anthropic` | Claude over the Messages API with the same DRY prompt; needs `ANTHROPIC_API_KEY`, no CLI. Default model `claude-sonnet-5-5`: the default second judge | about 3 s per pair, 4 in parallel |
| `gemini` | Gemini over its REST API with the same DRY prompt; needs `GEMINI_API_KEY`, no CLI. Default model `gemini-3.1-pro-preview` | about 12 s per pair, 4 in parallel |
| `none` | Lists candidate pairs unjudged; never fails the build | free |
| anything installed | A package registering `dry_lint.judges` | |

## Jev

`judges/jev.py` sends the two functions as typed state, each with its name, module and code:

```json
{"new_function": {"name": ..., "module": ..., "code": ...}, "existing_function": {...}}
```

It asks three questions:

| Question | Type | Asks |
| --- | --- | --- |
| `same_concept` | noul | One concept that should have a single implementation, parameterized where they differ? |
| `behaves_differently` | noul | Would a caller notice a different result for some input? |
| `owner` | choice | `existing`, `new`, `shared` or `none` |

The score is `same_concept × (1 − p(owner = none))`. Jev must think the two are one concept *and* that they should
become one implementation. A pair is
`drifted` when `behaves_differently ≥ drift_at`.

The question wording was tuned against a gold set, and the [benchmark](benchmark.md) numbers belong to that
wording. If you change it, bump `PROMPT_VERSION`; the store then knows the old verdicts came from another prompt.
Then re-measure. Adding call counts and the family of look-alikes to the state did not improve the results, so the
state is only the two functions.

## Any LLM, or any program

```bash
dry-lint check --judge command --judge-command "claude -p --model haiku"
dry-lint check --judge command --judge-command "llm -m gpt-4o-mini"
```

or in the settings, with a `version` so the store knows when its answers change meaning:

```toml
judge = { use = "command", command = "claude -p --model haiku", version = "haiku-dry-1" }
```

By default the command receives the prompt in `judges/command.py`, which uses the same DRY framing as the Jev
questions. With `input = "candidate"` it receives the candidate as one line of JSON instead, the same shape as in
`candidates.json`, for judges written as programs. Either way it must print one JSON object, and any text around
the object is ignored:

```json
{"label": "duplicate", "score": 0.9, "behaves_differently": 0.1, "owner": "existing",
 "why": "both truncate at a word boundary with an ellipsis"}
```

The judge's name is `command:<program>` unless you set `name`. A verdict is only reused by the judge that gave
it, so changing the program means judging again.

[examples/fake_judge.py](../examples/fake_judge.py) is a judge that needs no model, for trying the pipeline.

## A second opinion

`escalate` sends the first judge's scores in a band to a second judge, whose answer replaces the first. The
default is `escalate = "auto"`: Claude Sonnet 5.5 on `[0.6, 0.91)` when `ANTHROPIC_API_KEY` is set, otherwise no
escalation.

```toml
judge = "jev"
escalate = { use = "anthropic", model = "claude-sonnet-5-5", between = [0.6, 0.91] }    # the default, spelled out
escalate = { use = "gemini", model = "gemini-3.1-pro-preview" }                         # another vendor
escalate = { use = "command", command = "llm -m my-model", version = "my-model-1" }     # any CLI
escalate = "none"                                                                       # off
```

Measured live on the 250-pair gold set ([benchmark](benchmark.md#escalation)): at 0.8, precision from 94-95% to
98%, so roughly half the false blocks, and recall from 71-73% to 75-76% (within the intervals), for about 0.8
Sonnet calls per pull request. Among five second judges compared on the same pairs, Sonnet 5.5 changed its mind
least between runs and was the fastest; avoid Gemini 2.5 Pro. With the key set in a developer's environment, code
in the pairs goes to Anthropic; set `escalate = "none"` to keep it local. The stored verdict keeps the first
judge's name and records the second in `second_opinion`, so it is reused like any other.

## Writing a judge

See [plugins.md](plugins.md#judge). Measure it with `dry-lint bench --gold gold.jsonl --judge your-judge`, on the
same gold set as the judge it replaces.
