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

test("returns nothing when only part of the quote matches", () => {
  assert.deepEqual(matchRanges(["copay per stay", "elsewhere"], "you pay $0 copay per stay"), []);
});

test("returns nothing when the quote is absent", () => {
  assert.deepEqual(matchRanges(["something else"], "$320 copay otherwise"), []);
});

// Item order in a two-column table alternates between the columns.
const columns = ["$0 copayment or a", "30% coinsurance or", "colonoscopy at an", "Medicare-covered", "outpatient hospital.", "surgery or other"];
const lefts = [321.1, 447.1, 321.1, 447.1, 321.1, 447.1];

test("finds a quote that runs down one column", () => {
  assert.deepEqual(matchRanges(columns, "$0 copayment or a colonoscopy at an outpatient hospital", lefts), [
    { item: 0, start: 0, end: 17 },
    { item: 2, start: 0, end: 17 },
    { item: 4, start: 0, end: 19 },
  ]);
});

test("returns nothing for a column quote without item positions", () => {
  assert.deepEqual(matchRanges(columns, "$0 copayment or a colonoscopy at an outpatient hospital"), []);
});

test("returns nothing when a column quote occurs in two columns", () => {
  const twice = ["You pay these", "You pay these", "until", "amounts", "amounts"];
  assert.deepEqual(matchRanges(twice, "You pay these amounts", [321, 447, 500, 321, 447]), []);
});
