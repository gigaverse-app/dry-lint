/**
 * dry-lint's global counter: every duplicate kept out of every codebase that shares its totals.
 *
 *   POST /v1/pulls                     one merged pull request's ledger; counted once per repository and number
 *   GET  /v1/totals[?repository=o/n]   the totals, as JSON
 *   GET  /v1/badge[?metric=&repository=]  a shields.io endpoint badge
 *   GET  /v1/sign.svg[?theme=dark&repository=]  the README sign
 *
 * One SQLite-backed Durable Object holds the counts: a contribution is inserted once (the repository and pull
 * request number are its key) and the running totals move only when a row is new, so a retried or repeated
 * send changes nothing. Reads are cached for a minute (at the edge too, once it has a custom domain).
 */

import { DurableObject } from "cloudflare:workers";
import { Invalid, badge, contribution, repositoryKey, sign } from "./tally.js";

const EMPTY = { pulls: 0, repositories: 0, kept_out: 0, caught: 0, dismissed: 0, pushes: 0, judgments: 0,
  functions: 0, usd: 0, since: null };

export class Counter extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.sql = ctx.storage.sql;
    this.sql.exec(`
      CREATE TABLE IF NOT EXISTS pulls (
        repository TEXT NOT NULL, pull INTEGER NOT NULL, kept_out INTEGER, caught INTEGER, dismissed INTEGER,
        merged_open INTEGER, pushes INTEGER, runs INTEGER, judgments INTEGER, functions INTEGER, usd REAL,
        version TEXT, at TEXT NOT NULL, PRIMARY KEY (repository, pull));
      CREATE TABLE IF NOT EXISTS totals (
        scope TEXT PRIMARY KEY, pulls INTEGER, kept_out INTEGER, caught INTEGER, dismissed INTEGER, pushes INTEGER,
        judgments INTEGER, functions INTEGER, usd REAL, since TEXT);`);
  }

  /** Count one merged pull request; false when it was counted already. */
  record(entry) {
    const at = new Date().toISOString();
    const inserted = this.sql.exec(
      `INSERT OR IGNORE INTO pulls VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      entry.repository, entry.pull, entry.kept_out, entry.caught, entry.dismissed, entry.merged_open, entry.pushes,
      entry.runs, entry.judgments, entry.functions, entry.usd, entry.version, at).rowsWritten > 0;
    if (inserted) {
      for (const scope of ["*", entry.repository]) {
        this.sql.exec(
          `INSERT INTO totals VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (scope) DO UPDATE SET pulls = pulls + 1, kept_out = kept_out + excluded.kept_out,
             caught = caught + excluded.caught, dismissed = dismissed + excluded.dismissed,
             pushes = pushes + excluded.pushes, judgments = judgments + excluded.judgments,
             functions = functions + excluded.functions, usd = usd + excluded.usd`,
          scope, entry.kept_out, entry.caught, entry.dismissed, entry.pushes, entry.judgments, entry.functions,
          entry.usd, at);
      }
    }
    return inserted;
  }

  /** Totals for every repository ("*"), or for one by its key. */
  totals(scope = "*") {
    const [row] = this.sql.exec(`SELECT * FROM totals WHERE scope = ?`, scope).toArray();
    const repositories = scope === "*" ? this.sql.exec(`SELECT COUNT(*) AS n FROM totals`).one().n - (row ? 1 : 0) : 1;
    if (!row) return { ...EMPTY, repositories: 0 };
    const { scope: _, ...figures } = row;
    return { ...figures, usd: Math.round(figures.usd * 1e6) / 1e6, repositories };
  }
}

function json(body, status = 200, headers = {}) {
  return new Response(JSON.stringify(body), {
    status, headers: { "content-type": "application/json; charset=utf-8", ...headers },
  });
}

async function read(request, env, ctx) {
  const cache = caches.default;
  const cached = await cache.match(request);
  if (cached) return cached;
  const url = new URL(request.url);
  const name = url.searchParams.get("repository") ?? "";
  const counter = env.COUNTER.get(env.COUNTER.idFromName("global"));
  const totals = await counter.totals(name ? await repositoryKey(name) : "*");
  const caching = { "cache-control": "public, max-age=60" };
  let response;
  if (url.pathname === "/v1/totals") {
    response = json(totals, 200, caching);
  } else if (url.pathname === "/v1/badge") {
    response = json(badge(totals, url.searchParams.get("metric") ?? "kept-out"), 200, caching);
  } else {
    response = new Response(sign(totals, url.searchParams.get("theme") ?? "light", name), {
      headers: { "content-type": "image/svg+xml; charset=utf-8", ...caching },
    });
  }
  ctx.waitUntil(cache.put(request, response.clone()));
  return response;
}

async function write(request, env) {
  if (Number(request.headers.get("content-length") ?? 0) > 4096) return json({ error: "too large" }, 413);
  let entry;
  try {
    entry = contribution(await request.json());
  } catch (error) {
    if (error instanceof Invalid || error instanceof SyntaxError) return json({ error: error.message }, 400);
    throw error;
  }
  const counter = env.COUNTER.get(env.COUNTER.idFromName("global"));
  return json({ counted: await counter.record(entry) });
}

export default {
  async fetch(request, env, ctx) {
    const { pathname } = new URL(request.url);
    if (request.method === "POST" && pathname === "/v1/pulls") return write(request, env);
    if (request.method === "GET" && ["/v1/totals", "/v1/badge", "/v1/sign.svg"].includes(pathname)) {
      return read(request, env, ctx);
    }
    if (request.method === "GET" && pathname === "/") {
      return Response.redirect("https://github.com/gigaverse-app/dry-lint#the-counter", 302);
    }
    return json({ error: "not found" }, 404);
  },
};
