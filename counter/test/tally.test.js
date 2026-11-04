import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { test } from "node:test";

import { Invalid, badge, contribution, dollars, milestone, scope, sign } from "../src/tally.js";

const REPOSITORY = createHash("sha256").update("github-repository:4242").digest("hex");
const VALID = { repository: REPOSITORY, pull: 12, kept_out: 2, caught: 3, dismissed: 1, pushes: 4, runs: 5,
  judgments: 9, functions: 60, usd: 0.007, version: "0.1.0" };
const TOTALS = { pulls: 58, repositories: 12, kept_out: 1234, caught: 1400, dismissed: 40, pushes: 300,
  judgments: 5000, functions: 90000, usd: 0.84 };

test("a contribution keeps exactly the counted fields, with missing counts as zero", () => {
  const { version, ...rest } = VALID;
  assert.deepEqual(contribution({ ...rest, unexpected: "dropped" }),
    { ...rest, merged_open: 0, version: "" });
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

test("the badge is a shields.io endpoint, in dry-lint's purple", () => {
  assert.deepEqual(badge(TOTALS), { schemaVersion: 1, label: "duplicates kept out", message: "1,234",
    color: "7E4FC9", labelColor: "24292F", cacheSeconds: 300 });
  assert.equal(badge(TOTALS, "pulls").message, "58");
  assert.equal(badge(TOTALS, "repositories").label, "repositories");
  assert.equal(badge(TOTALS, "spent").message, "$0.84");
  assert.equal(badge(TOTALS, "unknown").label, "duplicates kept out");
});

test("the sign's number is never more than the count: exact below 1,000, rounded down above", () => {
  assert.deepEqual([0, 4, 999, 1234, 98_765, 1_234_567].map(milestone), [
    ["SO FAR", "0"], ["SO FAR", "4"], ["SO FAR", "999"], ["OVER", "1,200"], ["OVER", "98,000"],
    ["OVER", "1,200,000"]]);
});

test("the sign leads with the number and says what it counts", () => {
  const svg = sign(TOTALS);
  assert.match(svg, />OVER<\/text>/);
  assert.match(svg, />1,200</);
  assert.match(svg, /aria-label="1,234 duplicate functions/);
  assert.match(svg, /duplicate functions kept out of codebases/);
  assert.match(svg, /across 58 pull requests · 12 repositories · \$0\.84 of judging/);
  assert.match(svg, /fill="#FFFFFF"/);
  assert.match(sign(TOTALS, "dark"), /fill="#0D1117"/);
});

test("a repository's sign names it, escaped, and counts in the singular when it should", () => {
  const svg = sign({ ...TOTALS, kept_out: 1, pulls: 1, repositories: 1 }, "light", "acme/<shop>");
  assert.match(svg, /1 duplicate function kept out of acme\/&lt;shop&gt;/);
  assert.match(svg, /across 1 pull request · \$0\.84 of judging/);
  assert.doesNotMatch(svg, /repositor/);
});
