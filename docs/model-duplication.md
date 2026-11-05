# Model duplication probe

Model declarations need a separate signal from executable function similarity. The proposed opt-in model
extractors cover Pydantic models, dataclasses, TypeScript object types/interfaces and Zod object schemas.
They feed the existing candidate, judge, verdict-cache and reporting pipeline without importing adopter code.

## Decision contract

Shared fields propose a pair; they do not establish a shared authority. A consolidation finding must name
the concept and owner that should be reused, and explain how legitimate variations remain represented.
Field-for-field construction and copying are supporting evidence, not proof of equivalence.

Keep independently meaningful validation, lifecycle, invariant, exposure and wire contracts distinct.
Examples include public/private security boundaries, provider schemas, independently versioned events,
commands versus facts, different units or identity domains, and independent test oracles. Request/response
models are one example, not a blanket exemption. Different consumers, filenames or suffixes alone do not
justify a second authority. Existing inheritance, composition and schema derivation are reuse to recognize.

## Probe and test plan

- [ ] Extract real declarations from pinned gigaverse-ai, gigaverse-backend and gigaverse-web-app revisions.
- [ ] Label positive consolidations, meaningful near-copies and distinct contracts with source-grounded reasons.
- [ ] Measure candidate recall separately from adjudicated precision; keep uncertain labels out of headline metrics.
- [ ] Compare a naive field-overlap baseline, tune on development examples, and evaluate held-out examples.
- [ ] Exercise the CLI through a temporary repository, including same-file pairs and inline suppressions.
- [ ] Verify aliases, nested fields, defaults, validators, decorators and type edits invalidate cached evidence.
- [ ] Verify intentional inheritance/derivation is not treated as independently copied fields.
- [ ] Run the complete suite, lint, package build and dry-lint self-check.

Raw repository snapshots and run output remain outside the code PR. This document will record the final
supported scope, reproducible commands, metrics and limitations after the probe.
