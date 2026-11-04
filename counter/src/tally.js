/**
 * The counter's rules, free of Cloudflare: what a contribution may say, and how the totals are shown.
 *
 * A contribution is one merged pull request's ledger, sent once by the Action on its repository's default branch.
 * The repository arrives as the SHA-256 of its lower-cased `owner/name`, never its name. Counts are self-reported,
 * so each is bounded: one pull request cannot claim more than a pull request plausibly holds.
 */

export const LIMITS = {
  kept_out: 1_000, caught: 1_000, dismissed: 1_000, merged_open: 1_000, pushes: 10_000, runs: 10_000,
  judgments: 1_000_000, functions: 1_000_000, usd: 100,
};
export const FIELDS = Object.keys(LIMITS);
export const PURPLE = "7E4FC9";

export class Invalid extends Error {}

/** A contribution, checked and reduced to the fields the counter keeps; throws Invalid otherwise. */
export function contribution(body) {
  if (typeof body !== "object" || body === null || Array.isArray(body)) throw new Invalid("expected a JSON object");
  if (typeof body.repository !== "string" || !/^[0-9a-f]{64}$/.test(body.repository)) {
    throw new Invalid("repository must be the SHA-256 of owner/name, in hex");
  }
  if (!Number.isInteger(body.pull) || body.pull < 1 || body.pull > 10_000_000) {
    throw new Invalid("pull must be a pull request number");
  }
  const entry = { repository: body.repository, pull: body.pull };
  for (const field of FIELDS) {
    const value = body[field] ?? 0;
    const whole = field !== "usd";
    if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > LIMITS[field] ||
        (whole && !Number.isInteger(value))) {
      throw new Invalid(`${field} must be a number from 0 to ${LIMITS[field]}`);
    }
    entry[field] = value;
  }
  if (entry.kept_out + entry.dismissed + entry.merged_open > entry.caught) {
    throw new Invalid("kept_out, dismissed and merged_open cannot exceed caught");
  }
  entry.version = typeof body.version === "string" ? body.version.slice(0, 32) : "";
  return entry;
}

/** The SHA-256 of a repository's lower-cased `owner/name`: how contributions name it. */
export async function repositoryKey(name) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(name.trim().toLowerCase()));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function count(value) {
  return Math.round(value).toLocaleString("en-US");
}

/** The sign's number, McDonald's style: from 1,000 on, rounded down to two significant figures, "over" it. */
export function milestone(value) {
  if (value < 1000) return ["SO FAR", count(value)];
  const step = 10 ** (Math.floor(Math.log10(value)) - 1);
  return ["OVER", count(Math.floor(value / step) * step)];
}

export function dollars(usd) {
  return usd >= 0.1 || usd === 0 ? `$${usd.toFixed(2)}` : usd >= 0.001 ? `$${usd.toFixed(3)}` : "under $0.001";
}

const METRICS = {
  "kept-out": (t) => ["duplicates kept out", count(t.kept_out)],
  pulls: (t) => ["pull requests checked", count(t.pulls)],
  repositories: (t) => ["repositories", count(t.repositories)],
  spent: (t) => ["judging spent", dollars(t.usd)],
};

/** A shields.io endpoint badge: https://shields.io/badges/endpoint-badge */
export function badge(totals, metric = "kept-out") {
  const [label, message] = (METRICS[metric] ?? METRICS["kept-out"])(totals);
  return { schemaVersion: 1, label, message, color: PURPLE, labelColor: "24292F", logoSvg: LOGO, cacheSeconds: 300 };
}

const THEMES = {
  light: {
    background: "#FFFFFF", wash: "#F3ECFD", border: "#D1D9E0", text: "#1F2328", muted: "#59636E", accent: "#7E4FC9",
    rule: "#E4DAF5",
  },
  dark: {
    background: "#0D1117", wash: "#1A1030", border: "#30363D", text: "#F0F6FC", muted: "#9198A1", accent: "#C9AEF5",
    rule: "#2D2440",
  },
};
const FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif";
const MINT = "#7FD49A";

/** dry-lint's mark for a shields.io badge: two waves, one over the other. */
const LOGO = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M3 9.5c3-3 6-3 9 0s6 3 9 0M3 15.5c3-3 6-3 9 0s6 3 9 0" fill="none" stroke="${MINT}" stroke-width="2.6" stroke-linecap="round"/></svg>`;

/**
 * The sign: one number, as large as it gets, what it counts, and what it took. For a README, in a <picture> by
 * theme; it scales to any width. `scope` is "" for every repository, or a repository's name for its own sign.
 */
export function sign(totals, theme = "light", scope = "") {
  const c = THEMES[theme] ?? THEMES.light;
  const noun = totals.kept_out === 1 ? "duplicate function" : "duplicate functions";
  const where = scope ? `kept out of ${scope}` : "kept out of codebases";
  const stats = [
    [count(totals.pulls), `pull request${totals.pulls === 1 ? "" : "s"}`],
    ...(scope ? [] : [[count(totals.repositories), `repositor${totals.repositories === 1 ? "y" : "ies"}`]]),
    [dollars(totals.usd), "of judging"],
  ];
  const across = stats.map(([value, what]) => `${value} ${what}`).join(" · ");
  const label = escape(`${count(totals.kept_out)} ${noun} ${where}, across ${across}`);
  const [lead, number] = milestone(totals.kept_out);
  const shown = scope.length > 40 ? `${scope.slice(0, 39)}…` : scope;
  const heading = shown ? `${lead} · ${shown}` : lead;
  const caption = scope ? `${noun} kept out` : `${noun} ${where}`;
  const column = 448 / stats.length;
  const columns = stats.map(([value, what], i) => {
    const x = 808 + column * i + column / 2;
    return `<text x="${x}" y="104" text-anchor="middle" font-family="${FONT}" font-size="34" font-weight="800" fill="${c.text}">${value}</text>
  <text x="${x}" y="134" text-anchor="middle" font-family="${FONT}" font-size="15" font-weight="600" letter-spacing="1" fill="${c.muted}">${what.toUpperCase()}</text>`;
  });
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="200" viewBox="0 0 1280 200" role="img" aria-label="${label}">
  <title>${label}</title>
  <defs>
    <linearGradient id="wash" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${c.background}"/><stop offset="1" stop-color="${c.wash}"/></linearGradient>
    <linearGradient id="tile" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#9D6FE6"/><stop offset="1" stop-color="#5B32A8"/></linearGradient>
  </defs>
  <rect x="1" y="1" width="1278" height="198" rx="22" fill="${c.background}"/>
  <rect x="1" y="1" width="1278" height="198" rx="22" fill="url(#wash)" stroke="${c.border}" stroke-width="2"/>
  <rect x="28" y="28" width="144" height="144" rx="26" fill="url(#tile)"/>
  <path d="M58 86c14-14 28-14 42 0s28 14 42 0M58 116c14-14 28-14 42 0s28 14 42 0" fill="none" stroke="#FFFFFF" stroke-width="9" stroke-linecap="round"/>
  <circle cx="156" cy="44" r="7" fill="${MINT}"/>
  <text x="204" y="62" font-family="${FONT}" font-size="15" font-weight="700" letter-spacing="3" fill="${c.accent}">${escape(heading)}</text>
  <text x="200" y="134" font-family="${FONT}" font-size="80" font-weight="800" letter-spacing="-2" fill="${c.text}">${number}</text>
  <text x="204" y="170" font-family="${FONT}" font-size="24" font-weight="600" fill="${c.accent}">${escape(caption)}</text>
  <line x1="784" y1="44" x2="784" y2="156" stroke="${c.rule}" stroke-width="2"/>
  ${columns.join("\n  ")}
</svg>
`;
}

function escape(text) {
  return text.replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
}
