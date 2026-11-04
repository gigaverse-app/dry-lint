import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { test } from "node:test";

import { Invalid, badge, contribution, dollars, milestone, percent, repositoryKey, sign } from "../src/tally.js";

const REPOSITORY = createHash("sha256").update("acme/shop").digest("hex");
const VALID = { repository: REPOSITORY, pull: 12, kept_out: 2, caught: 3, dismissed: 1, pushes: 4, runs: 5,
  judgments: 9, functions: 60, usd: 0.007, version: "0.1.0" };
const TOTALS = { pulls: 58, repositories: 12, kept_out: 1234, caught: 1400, dismissed: 40, pushes: 300,
  judgments: 5000, functions: 90000, usd: 0.84, pairs: 41000, reused: 15000, drifted_kept_out: 212,
  rewrites_kept_out: 900, lines_kept_out: 38900 };

test("a contribution keeps exactly the counted fields, with missing counts as zero", () => {
  const { version, ...rest } = VALID;
  assert.deepEqual(contribution({ ...rest, unexpected: "dropped" }),
    { ...rest, merged_open: 0, pairs: 0, reused: 0, drifted_kept_out: 0, rewrites_kept_out: 0, lines_kept_out: 0,
      version: "" });
  assert.equal(contribution(VALID).version, "0.1.0");
});

test("a contribution names its repository by hash, never by name", () => {
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
  ["more drifted than kept out", { drifted_kept_out: 3 }],
  ["more rewrites than kept out", { rewrites_kept_out: 3 }],
]) {
  test(`a contribution with ${name} is refused`, () => {
    assert.throws(() => contribution(change === null || Array.isArray(change) ? change : { ...VALID, ...change }),
      Invalid);
  });
}

test("the repository key is the SHA-256 of the lower-cased name", async () => {
  assert.equal(await repositoryKey(" Acme/Shop "), REPOSITORY);
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
  assert.match(svg, />73% rewrites, not copies</);
  assert.match(svg, />212</);
  assert.match(svg, />drifted copies cleaned up</);
  assert.match(svg, />38,900</);
  assert.match(svg, />lines never merged</);
  for (const [value, label] of [["58", "PULL REQUESTS AUDITED"], ["90,000", "FUNCTIONS CHECKED"],
    ["41,000", "LOOK-ALIKES COMPARED"], ["75%", "RE-CHECKS SKIPPED"], ["12", "REPOSITORIES TRUST IT"]]) {
    assert.match(svg, new RegExp(`>${value}</text>\\s*<text[^>]*>${label}<`));
  }
  assert.match(svg, /aria-label="1,234 duplicate functions kept out of codebases, 900 of them rewrites rather than copies, /);
  assert.doesNotMatch(svg, /\$|judging/);
  assert.match(svg, /<image href="data:image\/png;base64,/);
  assert.match(svg, /fill="#FFFFFF"/);
  assert.match(sign(TOTALS, "dark"), /fill="#0D1117"/);
});

test("a sign from totals counted before drift, lines and rewrites existed shows zeros, not gaps", () => {
  const { drifted_kept_out, lines_kept_out, rewrites_kept_out, pairs, reused, ...older } = TOTALS;
  const svg = sign({ ...older, kept_out: 0, judgments: 0 });
  assert.doesNotMatch(svg, /undefined|NaN/);
  assert.match(svg, />rewrites, not just copies</);
  assert.match(svg, />–<\/text>\s*<text[^>]*>RE-CHECKS SKIPPED</);
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
