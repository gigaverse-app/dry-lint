# Default model review and adoption

Model review should run alongside function checks in the action and staged hook, with an explicit opt-out.
Adopters may declare model ownership policies; dry-lint must not infer a repository's architectural boundaries
from generic request/response names. Atomic scores prioritize review and cannot authorize consolidation.

The adoption ratchet records exact, source-reviewed duplicate pairs. Existing allowances cannot grow,
survive changed evidence, or reopen after cleanup. Intentional boundaries belong in documented policies or
pair-specific reviewed dismissals, not in duplicate debt.

## Verification plan

- Exercise default model detection, independent opt-outs, and combined function/model reports in real temporary repositories.
- Preserve model candidates across the split detect/judge action and show them in the sticky report.
- Prove unchanged debt is allowed, changed/new duplicates block, and removed allowances cannot be reused.
- Prove policy changes invalidate evidence and atomic negatives cannot create or clear accepted debt.
- Run the revised workflow on gigaverse-ai and gigaverse-backend, reviewing actual ownership and consumers
  before recording their initial model debt.
