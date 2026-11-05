# dry-lint's global counter

A Cloudflare Worker that counts every duplicate dry-lint has kept out of a codebase, across every repository
whose action shares its totals ([what is sent, and how to opt out](../docs/github-action.md#the-global-counter)).

| Request | Answer |
| --- | --- |
| `POST /v1/pulls` | Count one merged pull request: `{repository: KEY, pull, kept_out, caught, …}`, where `KEY` is the repository's counter key, `sha256("github-repository:" + numeric repository id)`. `{"counted": false}` if it was counted already. |
| `GET /v1/totals[?key=KEY]` | The totals, as JSON: everyone's, or one repository's. |
| `GET /v1/badge[?metric=kept-out\|drifted\|lines\|pulls\|functions\|repositories\|spent][&key=KEY]` | A [shields.io endpoint badge](https://shields.io/badges/endpoint-badge). |
| `GET /v1/sign.svg[?theme=dark][&key=KEY][&name=OWNER/NAME][&cleaned=N&remaining=N&dismissed=N]` | The README sign; `name` only labels it. A repository's backlog counts add a band of how much of its accepted duplication was cleaned up; dry-lint's sweep writes them into its README block. Like `name`, they are the README's statement and never reach the totals. |

Contributions are pseudonymous: a key ties one repository's pull requests together, but a repository is never
looked up by name (`?repository=` is refused), and a name does not lead to its key. Contributions sent before keys
came from repository ids were keyed on the SHA-256 of `owner/name`; they stay in the totals.

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
- **Deploys:** [`.github/workflows/counter.yml`](../.github/workflows/counter.yml). A push to `main` that changes
  `counter/` runs the tests, then `wrangler deploy` with the `CLOUDFLARE_API_TOKEN` secret, then checks the Worker
  answers. A failed deploy fails that run on `main`, where it is seen; nothing else deploys the counter. (This page
  once named Workers Builds, which never deployed: until November 4, 2026 the only deployment was a manual upload
  of the first commit, so later merges never reached the sign.)
- **The token:** a Cloudflare API token from the `Edit Cloudflare Workers` template, limited to the `Gigaverse OSS`
  account, stored as `CLOUDFLARE_API_TOKEN` on the repository's `counter` environment. To check what is live:
  `npx wrangler deployments list` lists each deployment and its source.

The Durable Object's data stays with the Worker named `dry-lint-counter`; deleting that Worker deletes the counts.
Columns are only ever added (`worker.js` adds any missing one at zero when the Durable Object starts), and every
insert names its columns, so a rollback to an earlier version still writes to the wider tables. The exception is
the first version, `310dfc9`, which inserted by position: it cannot write once a column has been added, so never
roll back to it.
