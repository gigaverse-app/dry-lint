# Opt-in operation-family judging

A family question asks whether one complete operation should be shared by several independent native
owners. Nomination is retrieval evidence. It never confirms a duplicate, creates pair verdicts or expands
into a clique. The family answer can confirm a subset and leave additional siblings rejected or unknown.

This implementation supplies the request adapter, judge plugin, exact cache, provider-free response
recorder and renderer. The CLI/scheduling integration supplies the existing campaign admission adapter.
It must run after the protected pair pass, under the same residual USD and call caps. There is no private
family allowance, automatic retry, provider fallback or default change.

## What nomination counts as removable

A family is nominated only when replacing every site with a helper call removes statements. Two rules keep
idioms out of that estimate:

- A site whose `return`, `break` or `continue` leaves the region costs two statements: the call and the
  condition that still transfers control (`if guard(value): return ...`). A helper cannot return from or
  continue its caller. A region that returns or raises on every path, or that ends the function, stays one
  `return helper(...)` call. `raise` is always free, so validation guards such as a shared budget check
  are unaffected.
- A region must name at least two domain identifiers: non-local names, attributes, keyword names or string
  literals. Locals become anonymous slots in the canonical form, so `if item: items.append(item)` would
  otherwise match unrelated code across a repository.

On 32 gigaverse-backend pull requests these rules reduced per-PR nominations from 19 to 5 (13 distinct
families to 4) and kept the one source-reviewed useful family; repository-wide nominations fell from 57 to 26.

## Native campaign configuration

Operation-family recovery is explicitly enabled for `check` after the complete protected pair pass:

```toml
preset = "balanced"

[discovery.families]
judge = { use = "anthropic-family", model = "claude-haiku-5-5", max_tokens = 2048 }
max_members = 8
max_questions = 3
```

On a Claude subscription instead of an API key, use `judge = { use = "claude-code-family" }`. It sends the same
prompt through `claude -p` with every tool off, and in CI the CLI logs in with `CLAUDE_CODE_OAUTH_TOKEN`.
Subscription calls are charged at the model's list price, like the pair `claude-code` judge, and the CLI's
reported token usage settles the reservation.

The adopter chooses the model/output ceiling and supplies its own credentials. These settings are an example,
not a measured quality recommendation. There is no separate family allowance: conservative reservations,
actual-usage settlement, retained failure holds, prior spending and all call caps share the native campaign.
Only text, JSON, Markdown and check-run output are supported. Split detect/judge and baseline sweep reject
this opt-in before judging; they do not silently omit family coverage. No default or CI setup changes.

## The backlog: families across the whole repository

`check` asks only about families with a member the change touches. On gigaverse-backend that skipped about 105
families with three or more owners in every pull request, so most repeated operations surface only in a
whole-repository view. `dry-lint scan` with the same `[discovery.families]` table nominates every family in the
repository. Its questions run after the complete pair pass and fit what the run's `budget.usd` has left, held
conservatively and settled at actual usage like pair questions; a pair the budget deferred leaves nothing for
families. A family question costs far more than a pair: about $0.13 each with Claude Sonnet 5.5 against the
$0.04 default allowance, so pass `--budget-usd` sized for the backlog (roughly 30 families on gigaverse-backend).

The family adapter uses the existing detector's pair rules and exact reviewed feedback to honor applicable
human decisions. If a nominated family's owners contain a settled pair, it omits that whole nomination and
reports the reason rather than silently clipping members. These rule exclusions do not claim a model answer.
Oversized or invalid source exclusions remain unresolved. Unknown members remain unresolved even when the
answer rejects consolidation. Family proposals are advisory and do not become confirmed pair findings.

Main reports write schema 15, carrying `families` and `family_exclusions`; old reports load with empty lists.
The independent family envelopes still use schema 1. Exact family records occupy a separate physical namespace.
Cache failures preserve the protected pair report: reads fail closed without a paid call, and writes settle the
admitted call's known usage (or retain its unknown-usage hold). Cached-only summaries retain the family policy
identity with zero new calls/charge. Clients close after the queue, including failure paths.

## Integration

Load the opt-in judge with the existing plugin mechanism:

```python
from dry_lint.plugins import load
from dry_lint.settings import PluginChoice

judge = load("judges", PluginChoice(use="anthropic-family", model="claude-sonnet-5-5", max_tokens=8192))
```

The adopter supplies `ANTHROPIC_API_KEY` or an explicit `api_key`. An absent key sets `available=False`;
the executor lists unconfirmed owners without creating a client, looking up positives or reserving money.
The SDK is optional and imported lazily only for an admitted call with a key. Root's orchestration should
close the judge after the queue. Calling the plugin directly bypasses admission just as directly calling
an ordinary judge does; product execution must use `FamilyJudging`.

`request_from_nomination(nomination)` consumes `FamilyNomination` from `operation_families`. It retains
full signatures, documentation, function bodies, helper/delegate context and its digest, local caller IDs,
bindings, enclosing scopes and exact UTF-8 column spans. Whole-line highlights are deliberately reconstructed
from the native function; original column slices are independently validated, including original line endings.
Caller IDs only describe available file-local resolution, not a complete caller graph.

Requests reject oversized evidence as a whole instead of truncating source: 2–12 owners, up to 16 operation
regions per owner, 32 KB per complete function, 16 KB of context per owner and 1 MiB per serialized question.
The separate `max_input_bytes` plugin option bounds the actual rendered prompt (default 256 KiB, configurable
up to 1 MiB). The prompt retains full functions and semantic context once; hashes, canonical AST serialization,
and duplicate region bodies stay in exact storage/cache identity. Highlights are exact line/column coordinates
within the complete source, never clipped snippets.
Set nomination limits accordingly or report oversized nominations as unconfirmed. Do not silently omit
members and reuse the same question identity. Output is bounded to a configured 1–16,000 tokens, default 8192. The independent input/output bounds
do not grant spending: shared native campaign reservation still decides whether the question fits.

```python
from dry_lint.family_models import request_from_nomination
from dry_lint.family_judging import FamilyJudging, FamilyVerdictStore
from dry_lint.family_report import FamilyReport
from dry_lint.store import DirectoryStore

request = request_from_nomination(nomination)
# shared_admission implements FamilyAdmission against the EXISTING CampaignStore.
# rates comes from the adopter's existing price configuration, USD per million tokens.
store = FamilyVerdictStore(DirectoryStore(cache_root / "families"))
finding = FamilyJudging(judge, store, shared_admission, rates).finding(request)
report = FamilyReport(findings=[finding])
print(report.text())
```

The backend namespace must be separate from pair records, since pair record enumeration expects pair
schemas. All family artifacts carry independent schema 1; embedding them in the main report/candidate file
requires the main file's schema bump in the integration change.

`FamilyAdmission.reserve(request, judge, usd)` returns a durable reservation index, `"budget"`, or `None`
(deferred). Its implementation must reserve in the existing campaign transaction, using `family_key` as
attempt evidence, enforce residual/protected-pass gating and cumulative USD/call limits, and prevent repeated
failed/abandoned attempts on the same revision. `settle(index, actual_usd_or_none, success)` returns the charge.
The family executor cannot advance a campaign or replenish credit. Input reservation uses UTF-8 byte count
plus framing and the finite output ceiling, matching native discovery. Actual usage, including cache token
tiers, settles even rejected/malformed/refused answers. Missing usage retains the reservation charge.

## Answer and reuse contract

Every owner must be classified exactly once. Consolidation requires at least two explicitly confirmed,
independent native owners, exact complete highlighted anchors, a common operation and shared contract, and
an explicit proposed helper signature, inputs, outputs and side effects. Each confirmed member must state
caller differences, ordering, exceptions, existing reuse and migration with evidence from that owner.
Confirmed anchors carry source quotations once. Claims cite `SourceReference(owner_id, start_line, end_line)`
without repeating source text; common-operation/contract references must match confirmed complete regions.
Unknown IDs, partial/altered source anchors, unbound common/helper claims and incomplete answers fail closed.
No score field exists. Mechanical grounding checks source references; semantic correctness still requires
source review and is never exported as pair gold data.

Reuse requires an exact ordered request, all full source/context/operation bodies, judge identity, model,
output cap and actual prompt text. Changing an unconfirmed sibling also invalidates the answer. There is
no structure-only, subset, similarity or changed-membership reuse. Cache reads reparse and ground the stored
raw response. Only valid completed responses enter the verdict cache; failures retain raw response and usage
on the failed finding for diagnosis and independent review.

The report presents one consolidation proposal and helper interface, per-member source coordinates and
migration constraints. Rejected and unknown siblings appear in a separate unconfirmed section. An explicitly unjudged, no-key,
deferred, budget-limited or failed question lists only unconfirmed members. Model prose is flattened,
bounded and escaped in Markdown. Historical response cost and this invocation's campaign charge are distinct;
cache hits cost zero this invocation and unknown actual costs remain unknown.

## Provider-free response recording

```python
from dry_lint.family_models import FamilyResponse
from dry_lint.family_judging import record_family_response

response = FamilyResponse.model_validate_json(captured_response_json)
record = record_family_response(request, judge, response, rates)
```

This function parses/validates an already captured response without constructing a client, calling a provider,
reserving money or writing a pair verdict. `FamilyResponse` carries raw text, optional usage, stop reason,
response ID and model. Failed findings retain the same envelope. Only `end_turn` is accepted as a complete answer;
truncated/refused responses fail even if their partial JSON happens to parse. Costs use configured rates and
recorded provider usage; they are not represented as invoice verification.
