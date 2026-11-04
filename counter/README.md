# dry-lint's global counter

A Cloudflare Worker that counts every duplicate dry-lint has kept out of a codebase, across every repository
whose action shares its totals ([what is sent, and how to opt out](../docs/github-action.md#the-global-counter)).

| Request | Answer |
| --- | --- |
| `POST /v1/pulls` | Count one merged pull request: `{repository: sha256(owner/name), pull, kept_out, caught, …}`. `{"counted": false}` if it was counted already. |
| `GET /v1/totals[?repository=OWNER/NAME]` | The totals, as JSON. |
| `GET /v1/badge[?metric=kept-out\|drifted\|lines\|pulls\|functions\|repositories\|spent][&repository=]` | A [shields.io endpoint badge](https://shields.io/badges/endpoint-badge). |
| `GET /v1/sign.svg[?theme=dark][&repository=]` | The README sign. |

One SQLite-backed Durable Object holds the counts. A contribution is inserted once, keyed on the repository hash
and pull request number, and the running totals move only when the row is new. A field added later is added to
both tables at zero when the Durable Object starts, so totals count it from that day. The rules (what a contribution
may claim, how the totals read) are in `src/tally.js`, which has no Cloudflare dependency and is tested with
Node's own runner:

```bash
node --test
npx wrangler dev   # the Worker and its Durable Object, locally
```

## Where it runs

- **Account:** `Gigaverse OSS`, a Cloudflare account on the Workers Free plan, kept separate from paid accounts.
  A Free account cannot be billed: past the free limits, requests fail instead. Keep it that way: never upgrade
  it to Workers Paid or add a payment method. Sign in with GitHub.
- **Address:** `https://dry-lint-counter.gigaverse-oss.workers.dev`, the account's `gigaverse-oss` workers.dev
  subdomain. `COUNTER` in `src/dry_lint/action.py` and the README's sign point there.
- **Deploys:** Workers Builds, connected to `gigaverse-app/dry-lint` with root directory `counter` and watch path
  `counter/*`. A push to `main` that changes the counter deploys it; nothing is deployed by hand.

To set it up again: in the `Gigaverse OSS` account, Workers & Pages → Create → Import a repository →
`gigaverse-app/dry-lint`, root directory `counter`, deploy command `npx wrangler deploy`. The Durable Object's
data stays with the Worker named `dry-lint-counter`; deleting that Worker deletes the counts.
