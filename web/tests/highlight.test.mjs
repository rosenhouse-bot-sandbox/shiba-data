import { test } from "node:test";
import assert from "node:assert/strict";
import { matchRanges } from "../static/highlight.js";

test("finds a quote split across items and whitespace", () => {
  const items = ["you pay $0 copay per", "stay, or $1,980", "copay  per stay", "next"];
  assert.deepEqual(matchRanges(items, "per stay, or $1,980 copay per stay"), [
    { item: 0, start: 17, end: 20 },
    { item: 1, start: 0, end: 15 },
    { item: 2, start: 0, end: 15 },
  ]);
});

test("ignores case and line breaks inside the quote", () => {
  assert.deepEqual(matchRanges(["Naturopathy Services"], "naturopathy\nservices"), [
    { item: 0, start: 0, end: 20 },
  ]);
});

test("falls back to word runs when text order differs", () => {
  const items = ["$50 allowance every six months", "unrelated", "Chiropractic, Acupuncture & Naturopathy Services"];
  const quote = "Chiropractic, Acupuncture & Naturopathy Services (Supplemental) $50 allowance every six months";
  assert.deepEqual(matchRanges(items, quote), [
    { item: 0, start: 0, end: 30 },
    { item: 2, start: 0, end: 48 },
  ]);
});

test("returns nothing when the quote is absent", () => {
  assert.deepEqual(matchRanges(["something else"], "$320 copay otherwise"), []);
});
