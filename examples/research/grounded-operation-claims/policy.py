"""One frozen, outcome-independent research policy on canonical AnthropicJudge."""

import hashlib
from types import SimpleNamespace

from dry_lint.judges.anthropic import AnthropicJudge
from dry_lint.judges.command import OPERATIONS_PROMPT, PROMPT_POLICIES, prompt

MODEL = "claude-haiku-5-5"
OUTPUT = 2048
POLICY = "shared-operations-grounded-claim-v1"
GROUNDING = """Ground the reported claim in independently repeated implementation, using only the supplied source.
Before deciding, examine the plausible overlaps across BOTH complete functions, including executable policy
outside calls to shared helpers. Do not stop at the first familiar call or short matching expression.
For each possible operation, distinguish its implemented contract from its callers' generic mechanics.
Apply this counterfactual: if calls to existing shared owners and generic syntax were factored out, what
specific domain decision, ordered transformation, or lifecycle guarantee would still be independently owned
at both sites? A repeated composition can qualify when its ordering, data flow, or failure contract itself
owns meaningful policy. A short domain rule can qualify; length and confidence thresholds are not substitutes
for this test. A helper call alone does not establish the helper's unseen implementation or equivalence.

Make the final why independently checkable. For every operation you actually recommend sharing, give a brief
exact source anchor from NEW and from EXISTING, state the common input-to-result or state-transition contract,
and explain the residual policy that the counterfactual leaves duplicated. State the relevant variation to
preserve in the callers. Anchor the actual claimed operation, not unrelated code elsewhere in either function.
If an apparent overlap is already shared or only generic mechanics, look for another established independent
operation before concluding separate. If none is established, explain the limiting evidence. Do not invent
missing helper bodies, intended ownership, or supporting context. Do not credit an operation you leave unmentioned.
Keep this evidence concise inside the existing why string; return the same JSON object schema requested above.

"""
TEMPLATE = OPERATIONS_PROMPT.replace("# NEW: <<new_name>>", GROUNDING + "# NEW: <<new_name>>", 1)
DIGEST = hashlib.sha256(TEMPLATE.encode()).hexdigest()
PROMPT_VERSION = "dry-grounded-claim-v1-" + DIGEST[:16]
VERSION = f"{PROMPT_VERSION}:{MODEL}:output={OUTPUT}"


def register():
    entry = (PROMPT_VERSION, TEMPLATE)
    previous = PROMPT_POLICIES.setdefault(POLICY, entry)
    if previous != entry:
        raise ValueError("Research policy name collision")


register()


def descriptor(arm):
    policy = POLICY if arm == "grounded" else "shared-operations"
    if arm not in ("baseline", "grounded"):
        raise ValueError("Unknown arm")
    return SimpleNamespace(
        name="anthropic-operations",
        model=MODEL,
        prompt_policy=policy,
        version=f"{PROMPT_POLICIES[policy][0]}:{MODEL}:output={OUTPUT}",
        max_tokens=OUTPUT,
        strict_version=True,
        subscription=False,
    )


class GroundedClaimJudge(AnthropicJudge):
    """Canonical SDK, parser and usage; no custom provider or source transformation."""

    def __init__(self, *, api_key, http_client=None):
        if not api_key:
            raise ValueError("Explicit root-supplied credential required")
        super().__init__(
            model=MODEL,
            api_key=api_key,
            workers=1,
            effort=None,
            http_client=http_client,
            prompt_policy=POLICY,
            max_tokens=OUTPUT,
            max_retries=0,
            retry_malformed=False,
        )

    def input_text(self, candidate):
        return prompt(candidate, policy=POLICY)
