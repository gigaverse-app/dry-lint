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
  return { schemaVersion: 1, label, message, color: PURPLE, labelColor: "24292F", cacheSeconds: 300 };
}

const THEMES = {
  light: { background: "#FFFFFF", border: "#D1D9E0", text: "#1F2328", muted: "#59636E", accent: "#7E4FC9", tint: "#F3EFFA" },
  dark: { background: "#0D1117", border: "#30363D", text: "#F0F6FC", muted: "#9198A1", accent: "#A47BE8", tint: "#1E1530" },
};
const FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif";

/**
 * The sign: one number, as large as it gets, and what it counts. For a README, in a <picture> by theme.
 * `scope` is "" for every repository, or a repository's name for its own sign.
 */
export function sign(totals, theme = "light", scope = "") {
  const c = THEMES[theme] ?? THEMES.light;
  const noun = totals.kept_out === 1 ? "duplicate function" : "duplicate functions";
  const where = scope ? `kept out of ${escape(scope)}` : "kept out of codebases";
  const across = [
    `${count(totals.pulls)} pull request${totals.pulls === 1 ? "" : "s"}`,
    scope ? "" : `${count(totals.repositories)} repositor${totals.repositories === 1 ? "y" : "ies"}`,
    `${dollars(totals.usd)} of judging`,
  ].filter(Boolean).join(" · ");
  const label = `${count(totals.kept_out)} ${noun} ${where}, across ${across}`;
  const [lead, number] = milestone(totals.kept_out);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="120" viewBox="0 0 640 120" role="img" aria-label="${label}">
  <title>${label}</title>
  <rect x="0.5" y="0.5" width="639" height="119" rx="12" fill="${c.background}" stroke="${c.border}"/>
  <rect x="16" y="16" width="88" height="88" rx="10" fill="${c.tint}"/>
  <text x="60" y="58" text-anchor="middle" font-family="${FONT}" font-size="30" font-weight="700" fill="${c.accent}">≈</text>
  <text x="60" y="84" text-anchor="middle" font-family="${FONT}" font-size="11" font-weight="600" fill="${c.accent}" letter-spacing="0.5">DRY-LINT</text>
  <text x="124" y="34" font-family="${FONT}" font-size="12" font-weight="600" fill="${c.muted}" letter-spacing="1.5">${lead}</text>
  <text x="124" y="72" font-family="${FONT}" font-size="40" font-weight="800" fill="${c.text}">${number}</text>
  <text x="124" y="92" font-family="${FONT}" font-size="14" font-weight="600" fill="${c.accent}">${noun} ${where}</text>
  <text x="124" y="108" font-family="${FONT}" font-size="11" fill="${c.muted}">across ${across}</text>
</svg>
`;
}

function escape(text) {
  return text.replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
}
