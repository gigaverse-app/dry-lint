# Original study code for review

These are byte-identical copies of the actual study implementations, included as plain files so they can be reviewed on GitHub. `ORIGINS.json` binds each copy to the complete implementation archive in `../reproduction/implementation.json.gz`.

- `trace_followup.py`: first-round source anchors, request preparation and cohort selection.
- `coverage_round2.py`: revised body windows, second-round preparation and source mapping.
- `trace_evaluate.py` and `score_coverage_round2.py`: original answer parsing and result scoring.
- `anthropic.py` and `jev.py`: actual provider question/renderer/parser implementations at the study revision.

These historical modules retain their original imports and lab paths. Do not run them as portable entrypoints or expect present-day production defaults to match them. Use the [reproduction kit](../reproduction/README.md) to execute the same selected-case transformations and recorded scoring without the original lab. The archive contains all local dependencies and the lockfile. The kit exposes original source, exact rendered questions and recorded answers separately.
