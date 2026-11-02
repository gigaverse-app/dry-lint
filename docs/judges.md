# Judges

| `--judge` | What it is | Cost |
| --- | --- | --- |
| `auto` (default) | Jev when `TYPESAFE_AI_API_KEY` is set, otherwise `none` | |
| `jev` | TypeSafe's System One decision model, prompt `reuse-v2` | about 0.3 s per pair, 8 pairs in parallel |
| `command` | Any command: the prompt on stdin, a JSON verdict on stdout | whatever your model costs |
| `none` | Lists candidate pairs unjudged; never fails the build | free |

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

## Any LLM

```bash
dry-lint check --judge command --judge-command "claude -p --model haiku"
dry-lint check --judge command --judge-command "llm -m gpt-4o-mini"
```

The command receives the prompt in `judges/command.py`, which uses the same DRY framing as the Jev questions. It must
print one JSON object, and any text around the object is ignored:

```json
{"label": "duplicate", "score": 0.9, "owner": "existing", "why": "both truncate at a word boundary with an ellipsis"}
```

[examples/fake_judge.py](../examples/fake_judge.py) is a judge that needs no model, for trying the pipeline.

## Writing a judge

A judge is any object with a `name` and a method `judge(candidates, settings) -> list[Verdict]`, returning one
verdict per candidate, in order. Use `judges.label_for(score, behaves_differently, settings)` so that labels follow
the configured thresholds.
