import { test } from "node:test";
import assert from "node:assert/strict";
import { ago } from "../static/ago.js";

const now = new Date("2026-10-27T15:00:00Z");
const before = (minutes) => new Date(now - minutes * 60000);

test("uses minutes under an hour", () => {
  assert.equal(ago(before(0), now), "0 minutes ago");
  assert.equal(ago(before(1), now), "1 minute ago");
  assert.equal(ago(before(59), now), "59 minutes ago");
});

test("a clock behind the build says 0 minutes", () => {
  assert.equal(ago(before(-1), now), "0 minutes ago");
});

test("uses hours under two days", () => {
  assert.equal(ago(before(60), now), "1 hour ago");
  assert.equal(ago(before(47 * 60 + 59), now), "47 hours ago");
});

test("uses days after that", () => {
  assert.equal(ago(before(48 * 60), now), "2 days ago");
  assert.equal(ago(before(30 * 24 * 60), now), "30 days ago");
});
