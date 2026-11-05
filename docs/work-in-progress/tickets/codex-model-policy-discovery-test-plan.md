# Model discovery and adopter ownership policies

Model similarity currently misses small contracts and shared subsets. Pair judgments can also mistake an
intentionally independent prompt or public API contract for duplication. Preserve the default mechanical
candidate set, add bounded exploration, and carry adopter policy into the existing review pipeline.

```text
Before
declared fields -> Dice top-k -> generic model judgment -> report

After
declared fields -> unchanged Dice top-k -------------------+
                -> opt-in field TF-IDF / lower overlap ----+-> adopter pair policies
                                                           -> budgeted judgment / coding-agent review
```

Adopters can match both sides by file and symbol name, attach ownership guidance, adjust review priority, or
explicitly discard a pair with a reason. Matching is symmetric. Filename conventions are configured ownership
claims, not inferred semantic facts. A public-versus-private rule must not suppress two copies inside the same
public contract. Matched policies travel with candidates and participate in evidence/cache invalidation.

The coding agent resolves actual roles, nested types and construction sites before consolidating. Optional Jev
model questions expose separate ownership, existing reuse and uncertainty as evidence; an atomic negative is
not architectural proof. No repository-specific names or policies are built into the detector.

## Validation plan

- [x] Detection integration: unchanged baseline pairs survive exploration; tiny models and meaningful subsets
      enter the exploration lane, with bounded neighbours and no repeated pairs.
- [x] Adopter policy integration: path/name combinations match both orientations, priority reaches budget
      admission, and a discard stays visible with its exact reason while consuming no judge calls.
- [x] Ownership controls: prompt/domain and private/public rules preserve same-owner reuse candidates.
- [x] Evidence integration: policy edits and supplied source evidence changes invalidate verdict reuse and
      reviewed dismissals; candidate round-trips and legacy files remain readable.
- [x] Judge integration: real HTTP client over MockTransport preserves typed model facts and policies;
      ordinary function judging remains unchanged.
- [x] Coding-agent handoff: unresolved model ownership remains visible with the relevant policy and source
      evidence; confidence in similarity does not imply permission to merge contracts.
- [x] Live probe: rerun corrected labels and consumer scans on pinned AI/backend/web source; independently
      review fresh candidates and measure retrieval, review yield and policy controls. Store private evidence
      outside the code PR.
- [x] Full repository checks: lint, tests with coverage, build and dry-lint self-check; inspect final diff and CI.

## Measurement constraints

Previous probe labels were corrected using explicit repository-owner policy: structured-answer prompt models
evolve independently from conformed models, and externally published Developer API models have a longer
compatibility lifetime than internal Product schemas. Tool arguments remain unresolved where independent
prompt tuning is plausible. The original positive pool consequently changed from 26 to 24.

Use the corrected labels as development evidence, not an unbiased estimate of production precision or global
recall. Count related positive pairs as families when reporting review yield. Reuse production comparers,
judging, budgets and feedback rather than another parallel pipeline.

## Result

The opt-in workflow is implemented and measured. See [model discovery](../../model-duplication.md) for
configuration, pinned consumer revisions, corrected labels, fresh review yield and Jev ranking results.
The same-source tests, 100% coverage, both supported CI Python versions, build, consumer installation on
Linux/macOS/Windows and the judged self-check passed in [CI run 290](https://github.com/gigaverse-app/dry-lint/actions/runs/41959318352).
Private run artifacts remain outside the repository. No consumer refactor is included in this PR.
