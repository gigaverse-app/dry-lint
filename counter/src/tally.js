/**
 * The counter's rules, free of Cloudflare: what a contribution may say, and how the totals are shown.
 *
 * A contribution is one merged pull request's ledger, sent once by the Action on its repository's default branch.
 * The repository arrives as its counter key, the SHA-256 of its numeric GitHub id, never its name: pseudonymous,
 * since a name alone does not lead to the key. Counts are self-reported, so each is bounded: one pull request
 * cannot claim more than a pull request plausibly holds.
 */

import { LINT } from "./lint.js";

export const LIMITS = {
  kept_out: 1_000, caught: 1_000, dismissed: 1_000, merged_open: 1_000, pushes: 10_000, runs: 10_000,
  judgments: 1_000_000, functions: 1_000_000, usd: 100,
  pairs: 1_000_000, reused: 1_000_000, drifted_kept_out: 1_000, rewrites_kept_out: 1_000, lines_kept_out: 1_000_000,
};
/** What a contribution says about its duplicates beyond counting them: older Actions send none of it. */
const DETAILS = ["pairs", "reused", "drifted_kept_out", "rewrites_kept_out", "lines_kept_out"];
/**
 * Set by the counter, never sent: how much of a contribution was measured in detail. Shares are taken over these,
 * so totals from Actions that predate the details read as unknown, not as zero.
 */
const MEASURED = ["measured_pulls", "measured_kept_out", "measured_judgments"];
export const FIELDS = [...Object.keys(LIMITS), ...MEASURED];
/** The fields the totals sum; a pull request's own row keeps the rest. */
export const TOTALED = FIELDS.filter((field) => !["merged_open", "runs"].includes(field));
export const PURPLE = "7E4FC9";

export class Invalid extends Error {}

/** A contribution, checked and reduced to the fields the counter keeps; throws Invalid otherwise. */
export function contribution(body) {
  if (typeof body !== "object" || body === null || Array.isArray(body)) throw new Invalid("expected a JSON object");
  if (typeof body.repository !== "string" || !/^[0-9a-f]{64}$/.test(body.repository)) {
    throw new Invalid("repository must be the repository's counter key: 64 lower-case hex characters");
  }
  if (!Number.isInteger(body.pull) || body.pull < 1 || body.pull > 10_000_000) {
    throw new Invalid("pull must be a pull request number");
  }
  const entry = { repository: body.repository, pull: body.pull };
  for (const field of Object.keys(LIMITS)) {
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
  if (entry.drifted_kept_out > entry.kept_out || entry.rewrites_kept_out > entry.kept_out) {
    throw new Invalid("drifted_kept_out and rewrites_kept_out cannot exceed kept_out");
  }
  const measured = DETAILS.some((field) => field in body);
  entry.measured_pulls = measured ? 1 : 0;
  entry.measured_kept_out = measured ? entry.kept_out : 0;
  entry.measured_judgments = measured ? entry.judgments : 0;
  entry.version = typeof body.version === "string" ? body.version.slice(0, 32) : "";
  return entry;
}

/**
 * Which totals a read asks for: everyone's, or one repository's by its counter key, which the Action prints on the
 * repository's default-branch runs. A name never finds a repository: names can be guessed, keys cannot. `name` only
 * labels the sign, for a repository that chooses to show its own.
 */
export function scope(params) {
  if (params.has("repository")) {
    throw new Invalid("a repository is found by its counter key (?key=), printed by dry-lint on its default branch");
  }
  const key = params.get("key") ?? "";
  if (!key) return { key: "*", label: "" };
  if (!/^[0-9a-f]{64}$/.test(key)) throw new Invalid("key must be 64 lower-case hex characters");
  return { key, label: (params.get("name") ?? "").slice(0, 100) || "this repository" };
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

/** Whether the detailed counts are known: some Action has measured them, or there is nothing to measure yet. */
function known(totals) {
  return (totals.measured_pulls ?? 0) > 0 || totals.pulls === 0;
}

/** A detailed count, or a dash while it is unknown: never a zero that only means "not measured". */
function measured(totals, value) {
  return known(totals) ? count(value ?? 0) : "–";
}

const METRICS = {
  "kept-out": (t) => ["duplicates kept out", count(t.kept_out)],
  drifted: (t) => ["drifted copies cleaned up", measured(t, t.drifted_kept_out)],
  lines: (t) => ["duplicate lines never merged", measured(t, t.lines_kept_out)],
  pulls: (t) => ["pull requests audited", count(t.pulls)],
  functions: (t) => ["functions checked", count(t.functions)],
  repositories: (t) => ["repositories", count(t.repositories)],
  spent: (t) => ["judging spent", dollars(t.usd)],
};

/** dry-lint's mark for a shields.io badge: two waves, one over the other. */
const MINT = "#7FD49A";
const LOGO = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M3 9.5c3-3 6-3 9 0s6 3 9 0M3 15.5c3-3 6-3 9 0s6 3 9 0" fill="none" stroke="${MINT}" stroke-width="2.6" stroke-linecap="round"/></svg>`;

/** A shields.io endpoint badge: https://shields.io/badges/endpoint-badge */
export function badge(totals, metric = "kept-out") {
  const [label, message] = (METRICS[metric] ?? METRICS["kept-out"])(totals);
  return { schemaVersion: 1, label, message, color: PURPLE, labelColor: "24292F", logoSvg: LOGO, cacheSeconds: 300 };
}

/** A whole-number share, or a dash when there is nothing to share. */
export function percent(part, whole) {
  return whole ? `${Math.round((100 * part) / whole)}%` : "–";
}

const THEMES = {
  light: {
    background: "#FFFFFF", wash: "#F3ECFD", border: "#D1D9E0", text: "#1F2328", muted: "#59636E", accent: "#7E4FC9",
    rule: "#E4DAF5", tile: "#FFFFFF", strip: "#FAF7FF",
  },
  dark: {
    background: "#0D1117", wash: "#1A1030", border: "#30363D", text: "#F0F6FC", muted: "#9198A1", accent: "#C9AEF5",
    rule: "#2D2440", tile: "#161B22", strip: "#120D1F",
  },
};
const FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif";
const DRIFT = "#F0883E", LINES = "#3FB950";

function text(x, y, size, weight, fill, content, extra = "") {
  return `<text x="${x}" y="${y}" font-family="${FONT}" font-size="${size}" font-weight="${weight}" fill="${fill}"${extra}>${content}</text>`;
}

/** One benefit: a large number, what it counts, and a note. The number shrinks to fit a tile. */
function tile(c, x, color, value, label, note) {
  const size = Math.min(60, Math.floor(272 / (0.58 * value.length)));
  return `<rect x="${x}" y="28" width="330" height="182" rx="16" fill="${c.tile}" stroke="${c.border}"/>
  <rect x="${x}" y="46" width="6" height="146" rx="3" fill="${color}"/>
  ${text(x + 28, 110, size, 800, c.text, value, ' letter-spacing="-1"')}
  ${text(x + 28, 144, 17, 700, c.text, label)}
  ${text(x + 28, 170, 14, 400, c.muted, note)}`;
}

/**
 * The sign: what dry-lint kept out of codebases, in three tiles, over a strip of what it checked to get there. For
 * a README, in a <picture> by theme; it scales to any width. `scope` is "" for every repository, or how a
 * repository's own sign names it, in the strip.
 */
export function sign(totals, theme = "light", scope = "") {
  const c = THEMES[theme] ?? THEMES.light;
  const kept = totals.kept_out, drifted = totals.drifted_kept_out ?? 0, lines = totals.lines_kept_out ?? 0;
  const rewrites = totals.rewrites_kept_out ?? 0, reused = totals.reused ?? 0, pairs = totals.pairs ?? 0;
  const one = (n, singular, many) => (n === 1 ? singular : many);
  const detailed = known(totals);
  const [lead, number] = milestone(kept);
  const shown = scope.length > 22 ? `${scope.slice(0, 21)}…` : scope;
  const strip = [
    [count(totals.pulls), one(totals.pulls, "PULL REQUEST AUDITED", "PULL REQUESTS AUDITED")],
    [count(totals.functions), one(totals.functions, "FUNCTION CHECKED", "FUNCTIONS CHECKED")],
    [measured(totals, pairs), one(pairs, "LOOK-ALIKE COMPARED", "LOOK-ALIKES COMPARED")],
    [percent(reused, reused + (totals.measured_judgments ?? 0)), "RE-CHECKS SKIPPED"],
    scope ? [escape(shown), "REPOSITORY"]
      : [count(totals.repositories), one(totals.repositories, "REPOSITORY TRUSTS IT", "REPOSITORIES TRUST IT")],
  ];
  const width = 1278 / strip.length;
  const cells = strip.map(([value, label], i) => {
    const x = 1 + width * i + width / 2;
    const size = i === 4 && scope ? 20 : 26;
    return `${text(x, 278, size, 800, c.text, value, ' text-anchor="middle"')}
  ${text(x, 302, 12, 700, c.muted, label, ' text-anchor="middle" letter-spacing="1.2"')}${i ? `
  <line x1="${1 + width * i}" y1="256" x2="${1 + width * i}" y2="312" stroke="${c.rule}" stroke-width="2"/>` : ""}`;
  });
  const label = escape([
    `${count(kept)} ${one(kept, "duplicate function", "duplicate functions")} kept out of ${scope || "codebases"}`,
    ...(detailed ? [
      `${count(rewrites)} of those measured rewrites rather than copies`,
      `${count(drifted)} drifted ${one(drifted, "copy", "copies")} cleaned up`,
      `${count(lines)} duplicate ${one(lines, "line", "lines")} never merged`,
    ] : []),
    `across ${count(totals.pulls)} ${one(totals.pulls, "pull request", "pull requests")}`,
  ].join(", "));
  const measuredKept = totals.measured_kept_out ?? 0;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="330" viewBox="0 0 1280 330" role="img" aria-label="${label}">
  <title>${label}</title>
  <defs>
    <linearGradient id="wash" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${c.background}"/><stop offset="1" stop-color="${c.wash}"/></linearGradient>
    <clipPath id="card"><rect x="1" y="1" width="1278" height="328" rx="22"/></clipPath>
  </defs>
  <rect x="1" y="1" width="1278" height="328" rx="22" fill="${c.background}"/>
  <rect x="1" y="1" width="1278" height="328" rx="22" fill="url(#wash)"/>
  <circle cx="122" cy="120" r="92" fill="${c.accent}" opacity="0.14"/>
  <image href="${LINT}" x="34" y="32" width="176" height="176"/>
  ${tile(c, 236, c.accent, lead === "OVER" ? `${number}+` : number, one(kept, "duplicate kept out", "duplicates kept out"),
    measuredKept ? `${percent(rewrites, measuredKept)} rewrites, not copies` : "rewrites, not just copies")}
  ${tile(c, 580, DRIFT, measured(totals, drifted), one(drifted, "drifted copy cleaned up", "drifted copies cleaned up"),
    detailed ? "already behaving differently" : "counted from the next merge")}
  ${tile(c, 924, LINES, measured(totals, lines), one(lines, "line never merged", "lines never merged"),
    detailed ? "of duplicated logic" : "counted from the next merge")}
  <rect x="1" y="236" width="1278" height="93" fill="${c.strip}" clip-path="url(#card)"/>
  <line x1="1" y1="236" x2="1279" y2="236" stroke="${c.border}" stroke-width="2"/>
  ${cells.join("\n  ")}
  <rect x="1" y="1" width="1278" height="328" rx="22" fill="none" stroke="${c.border}" stroke-width="2"/>
</svg>
`;
}

function escape(text) {
  return text.replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
}
