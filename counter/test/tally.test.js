import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { test } from "node:test";

import { Invalid, backlog, badge, contribution, dollars, milestone, percent, scope, sign } from "../src/tally.js";

const REPOSITORY = createHash("sha256").update("github-repository:4242").digest("hex");
const VALID = { repository: REPOSITORY, pull: 12, kept_out: 2, caught: 3, dismissed: 1, pushes: 4, runs: 5,
  judgments: 9, functions: 60, usd: 0.007, version: "0.1.0" };
const TOTALS = { pulls: 58, repositories: 12, kept_out: 1234, caught: 1400, dismissed: 40, pushes: 300,
  judgments: 5000, functions: 90000, usd: 0.84, pairs: 41000, reused: 15000, drifted_kept_out: 212,
  rewrites_kept_out: 900, lines_kept_out: 38900, measured_pulls: 50, measured_kept_out: 1200, measured_judgments: 5000 };

test("a contribution keeps exactly the counted fields, with missing counts as zero", () => {
  const { version, ...rest } = VALID;
  assert.deepEqual(contribution({ ...rest, unexpected: "dropped" }),
    { ...rest, merged_open: 0, pairs: 0, reused: 0, drifted_kept_out: 0, rewrites_kept_out: 0, lines_kept_out: 0,
      measured_pulls: 0, measured_kept_out: 0, measured_judgments: 0, version: "" });
  assert.equal(contribution(VALID).version, "0.1.0");
});

test("a contribution names its repository by key, never by name", () => {
  assert.throws(() => contribution({ ...VALID, repository: "acme/shop" }), Invalid);
});

for (const [name, change] of [
  ["not an object", null],
  ["a list", []],
  ["no pull request number", { pull: 0 }],
  ["a fractional count", { kept_out: 1.5 }],
  ["a negative count", { judgments: -1 }],
  ["an implausible spend", { usd: 1000 }],
  ["a count that is not a number", { pushes: "4" }],
  ["more settled than caught", { kept_out: 3, dismissed: 1 }],
  ["more measured than kept out", { measured_kept_out: 3 }],
  ["a fractional measured count", { measured_kept_out: 1.5 }],
  ["more drifted than measured", { measured_kept_out: 1, drifted_kept_out: 2 }],
  ["more rewrites than measured", { measured_kept_out: 1, rewrites_kept_out: 2 }],
]) {
  test(`a contribution with ${name} is refused`, () => {
    assert.throws(() => contribution(change === null || Array.isArray(change) ? change : { ...VALID, ...change }),
      Invalid);
  });
}

test("a read finds one repository by its key, and never by its name", () => {
  assert.deepEqual(scope(new URLSearchParams("")), { key: "*", label: "" });
  assert.deepEqual(scope(new URLSearchParams(`key=${REPOSITORY}`)), { key: REPOSITORY, label: "this repository" });
  assert.deepEqual(scope(new URLSearchParams(`key=${REPOSITORY}&name=acme/shop`)), { key: REPOSITORY, label: "acme/shop" });
  assert.throws(() => scope(new URLSearchParams("repository=acme/shop")), Invalid);
  assert.throws(() => scope(new URLSearchParams(`repository=acme/shop&key=${REPOSITORY}`)), Invalid);
  assert.throws(() => scope(new URLSearchParams("key=acme/shop")), Invalid);
  assert.equal(scope(new URLSearchParams(`key=${REPOSITORY}&name=${"x".repeat(300)}`)).label.length, 100);
});

test("dollars never round a small spend down to nothing", () => {
  assert.deepEqual([0, 0.0004, 0.0123, 0.84, 12].map(dollars), ["$0.00", "under $0.001", "$0.012", "$0.84", "$12.00"]);
});

test("the badge is a shields.io endpoint, in dry-lint's purple, with dry-lint's mark", () => {
  const { logoSvg, ...rest } = badge(TOTALS);
  assert.deepEqual(rest, { schemaVersion: 1, label: "duplicates kept out", message: "1,234",
    color: "7E4FC9", labelColor: "24292F", cacheSeconds: 300 });
  assert.match(logoSvg, /^<svg xmlns="http:\/\/www\.w3\.org\/2000\/svg"[^]*<\/svg>$/);
  assert.deepEqual(["drifted", "lines", "pulls", "functions", "repositories", "spent"].map((m) => badge(TOTALS, m).message),
    ["212", "38,900", "58", "90,000", "12", "$0.84"]);
  assert.equal(badge(TOTALS, "unknown").label, "duplicates kept out");
});

test("a share is a whole percentage, or a dash when there is nothing to share", () => {
  assert.deepEqual([percent(15000, 20000), percent(1, 3), percent(0, 0)], ["75%", "33%", "–"]);
});

test("the sign's number is never more than the count: exact below 1,000, rounded down above", () => {
  assert.deepEqual([0, 4, 999, 1234, 98_765, 1_234_567].map(milestone), [
    ["SO FAR", "0"], ["SO FAR", "4"], ["SO FAR", "999"], ["OVER", "1,200"], ["OVER", "98,000"],
    ["OVER", "1,200,000"]]);
});

test("the sign shows what was kept out, and what was checked to get there, never what it cost", () => {
  const svg = sign(TOTALS);
  assert.match(svg, />1,200\+</);
  assert.match(svg, />duplicates kept out</);
  assert.match(svg, />75% rewrites, not copies</);  // of the 1,200 measured, not of all 1,234
  assert.equal(svg.match(/>in the 1,200 of 1,234 measured</g).length, 2);  // drift and lines count those alone
  assert.match(svg, />212</);
  assert.match(svg, />drifted copies cleaned up</);
  assert.match(svg, />38,900</);
  assert.match(svg, />lines never merged</);
  for (const [value, label] of [["58", "PULL REQUESTS AUDITED"], ["90,000", "FUNCTIONS CHECKED"],
    ["41,000", "LOOK-ALIKES COMPARED"], ["75%", "RE-CHECKS SKIPPED"], ["12", "REPOSITORIES TRUST IT"]]) {
    assert.match(svg, new RegExp(`>${value}</text>\\s*<text[^>]*>${label}<`));
  }
  assert.match(svg, /aria-label="1,234 duplicate functions kept out of codebases, 900 of the 1,200 measured rewrites rather than copies, /);
  assert.doesNotMatch(svg, /\$|judging/);
  assert.match(svg, /<image href="data:image\/png;base64,/);
  assert.match(svg, /fill="#FFFFFF"/);
  assert.match(sign(TOTALS, "dark"), /fill="#0D1117"/);
});

test("the counter marks a contribution measured from what it sent, and trusts only a stated, bounded count", () => {
  const stated = contribution({ ...VALID, pairs: 4, measured_kept_out: 1, drifted_kept_out: 1, lines_kept_out: 9,
    measured_pulls: 9, measured_judgments: 1 });
  assert.deepEqual([stated.measured_pulls, stated.measured_kept_out, stated.measured_judgments], [1, 1, 9]);
  assert.deepEqual([stated.drifted_kept_out, stated.lines_kept_out], [1, 9]);
  const older = contribution({ ...VALID, measured_pulls: 1, measured_judgments: 9 });
  assert.deepEqual([older.measured_pulls, older.measured_kept_out, older.measured_judgments], [0, 0, 0]);
});

test("details from an Action that does not say which duplicates it measured are not counted", () => {
  const unsaid = contribution({ ...VALID, pairs: 4, reused: 2, drifted_kept_out: 1, rewrites_kept_out: 1,
    lines_kept_out: 9 });
  assert.deepEqual([unsaid.measured_pulls, unsaid.measured_judgments, unsaid.pairs, unsaid.reused], [1, 9, 4, 2]);
  assert.deepEqual([unsaid.measured_kept_out, unsaid.drifted_kept_out, unsaid.rewrites_kept_out,
    unsaid.lines_kept_out], [0, 0, 0, 0]);
});

test("a sign whose every duplicate kept out was measured shows plain notes", () => {
  const svg = sign({ ...TOTALS, measured_kept_out: TOTALS.kept_out });
  assert.match(svg, />already behaving differently</);
  assert.match(svg, />of duplicated logic</);
  assert.doesNotMatch(svg, /measured</);
});

test("duplicates kept out before any was measured read as unknown, even once runs are measured", () => {
  const svg = sign({ ...TOTALS, measured_kept_out: 0, drifted_kept_out: 0, rewrites_kept_out: 0, lines_kept_out: 0 });
  assert.equal(svg.match(/>not measured yet</g).length, 2);
  assert.match(svg, />rewrites, not just copies</);
  assert.match(svg, />41,000<\/text>\s*<text[^>]*>LOOK-ALIKES COMPARED</);
  assert.deepEqual(["drifted", "lines"].map((m) => badge({ ...TOTALS, measured_kept_out: 0 }, m).message), ["–", "–"]);
});

test("totals from Actions that predate the details read as unknown on the sign, never as zero", () => {
  const { drifted_kept_out, lines_kept_out, rewrites_kept_out, pairs, reused, measured_pulls, measured_kept_out,
    measured_judgments, ...older } = TOTALS;
  const svg = sign(older);
  assert.doesNotMatch(svg, /undefined|NaN|0%/);
  assert.match(svg, />rewrites, not just copies</);
  assert.equal(svg.match(/>not measured yet</g).length, 2);
  for (const label of ["LOOK-ALIKES COMPARED", "RE-CHECKS SKIPPED"]) {
    assert.match(svg, new RegExp(`>–</text>\\s*<text[^>]*>${label}<`));
  }
  assert.doesNotMatch(svg, /aria-label="[^"]*(rewrites|drifted|never merged)/);
  assert.deepEqual(["drifted", "lines", "kept-out"].map((m) => badge(older, m).message), ["–", "–", "1,234"]);
});

test("a fresh counter shows zeros: nothing has been kept out, so nothing is unknown", () => {
  const svg = sign({ pulls: 0, repositories: 0, kept_out: 0, judgments: 0, functions: 0 });
  assert.doesNotMatch(svg, /undefined|NaN|>–<\/text>\s*<text[^>]*>LOOK|not measured yet/);
  assert.match(svg, />0<\/text>\s*<text[^>]*>lines never merged</);
});

test("a repository's sign names it, escaped, and counts in the singular when it should", () => {
  const one = { ...TOTALS, kept_out: 1, drifted_kept_out: 1, rewrites_kept_out: 1, lines_kept_out: 1, pulls: 1,
    functions: 1, pairs: 1, repositories: 1 };
  const svg = sign(one, "light", "acme/<shop>");
  for (const text of ["duplicate kept out", "drifted copy cleaned up", "line never merged", "PULL REQUEST AUDITED",
    "FUNCTION CHECKED", "LOOK-ALIKE COMPARED", "acme/&lt;shop&gt;", "REPOSITORY"]) {
    assert.match(svg, new RegExp(`>${text}<`));
  }
  assert.match(svg, /1 duplicate function kept out of acme\/&lt;shop&gt;/);
  assert.doesNotMatch(svg, /TRUST/);
});

test("a repository's sign shows a long name shortened, and keeps it whole in its label", () => {
  const name = `acme/${"x".repeat(60)}`;
  const svg = sign(TOTALS, "light", name);
  assert.match(svg, new RegExp(`>acme/x{16}…<`));
  assert.match(svg, new RegExp(`aria-label="[^"]*kept out of ${name},`));
});

test("a sign without backlog counts keeps its size and has no backlog band", () => {
  const svg = sign(TOTALS, "light", "acme/shop");
  assert.match(svg, /viewBox="0 0 1280 330"/);
  assert.doesNotMatch(svg, /BACKLOG/);
  assert.equal(backlog(new URLSearchParams("key=x&name=acme/shop")), null);
});

test("a repository's backlog grows its sign by a band of what was cleaned up out of everything accepted", () => {
  const accepted = backlog(new URLSearchParams("cleaned=8&remaining=21&dismissed=1"));
  assert.deepEqual(accepted, { cleaned: 8, remaining: 21, dismissed: 1 });
  const svg = sign(TOTALS, "dark", "acme/shop", accepted);
  assert.match(svg, /viewBox="0 0 1280 420"/);
  assert.match(svg, />8 of 30</);
  assert.match(svg, />BACKLOG CLEANED</);
  assert.match(svg, /27% of the 30 duplicate pairs accepted at adoption cleaned up · 21 remaining · 1 dismissed/);
  // The filled bar is the cleaned share of the 1040-wide track.
  assert.match(svg, /<rect x="200" y="356" width="277" height="16"/);
  assert.match(svg, /aria-label="[^"]*8 of 30 accepted duplicate pairs cleaned up, 21 remaining"/);
});

test("a backlog with nothing cleaned yet shows an empty bar, and a missing count reads as zero", () => {
  const accepted = backlog(new URLSearchParams("remaining=29"));
  assert.deepEqual(accepted, { cleaned: 0, remaining: 29, dismissed: 0 });
  const svg = sign(TOTALS, "light", "acme/shop", accepted);
  assert.match(svg, />0 of 29</);
  // Green fills only the lines tile's stripe: the bar has no filled part.
  assert.equal(svg.match(/fill="#3FB950"/g).length, 1);
  assert.equal(sign(TOTALS, "light", "acme/shop", { cleaned: 1, remaining: 28, dismissed: 0 })
    .match(/fill="#3FB950"/g).length, 2);
});

for (const query of ["cleaned=-1", "remaining=1.5", "dismissed=lots", "cleaned=12345678"]) {
  test(`a backlog count must be a whole number of pairs: ${query}`, () => {
    assert.throws(() => backlog(new URLSearchParams(query)), Invalid);
  });
}
