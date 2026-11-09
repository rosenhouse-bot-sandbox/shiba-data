import { test } from "node:test";
import assert from "node:assert/strict";
import { parse, format } from "../static/permalink.js";

const cases = [
  ["#/2027/main", { year: 2027, view: "main" }],
  ["#/2027/dvha/H3805-048-0/dental", { year: 2027, view: "dvha", plan: "H3805-048-0", sheet: "dvha", column: "dental" }],
  ["#/2027/main/H3805-048-0/primary_care/EOC/112",
    { year: 2027, view: "main", plan: "H3805-048-0", sheet: "main", column: "primary_care", kind: "EOC", page: 112 }],
  ["#/2027/plan/H3805-048-0", { year: 2027, view: "plan", plan: "H3805-048-0" }],
  ["#/2027/plan/H3805-048-0/EOC/4", { year: 2027, view: "plan", plan: "H3805-048-0", kind: "EOC", page: 4 }],
  ["#/2027/plan/H3805-048-0/dvha/dental/SB/3",
    { year: 2027, view: "plan", plan: "H3805-048-0", sheet: "dvha", column: "dental", kind: "SB", page: 3 }],
  ["#/2027/notes", { year: 2027, view: "notes" }],
  ["#/2027/how", { year: 2027, view: "how" }],
  ["#/2027/how/main/H1036-153-0/ambulance/column-rules",
    { year: 2027, view: "how", plan: "H1036-153-0", sheet: "main", column: "ambulance", step: "column-rules" }],
  ["#/2027/notes/main/H3805-048-0/ambulance/RIDER/2",
    { year: 2027, view: "notes", plan: "H3805-048-0", sheet: "main", column: "ambulance", kind: "RIDER", page: 2 }],
];

test("format and parse round-trip", () => {
  for (const [hash, state] of cases) {
    assert.equal(format(state), hash);
    assert.deepEqual(parse(hash, 2027), state, hash);
  }
});

test("links without a year are for the live year", () => {
  assert.deepEqual(parse("#/main/H2001-045-0/H_inpatient", 2027),
    { year: 2027, view: "main", plan: "H2001-045-0", sheet: "main", column: "H_inpatient" });
  assert.deepEqual(parse("#/plan/H2001-045-0", 2027), { year: 2027, view: "plan", plan: "H2001-045-0" });
  assert.deepEqual(parse("", 2027), { year: 2027, view: "main" });
  assert.deepEqual(parse("#/", 2027), { year: 2027, view: "main" });
});

test("document kinds are case-insensitive and a missing page is page 1", () => {
  assert.deepEqual(parse("#/2027/plan/H1/eoc", 2027), { year: 2027, view: "plan", plan: "H1", kind: "EOC", page: 1 });
});

test("links to Ambiguities open Notes", () => {
  assert.deepEqual(parse("#/2027/ambiguities/main/H1/ambulance", 2027),
    { year: 2027, view: "notes", plan: "H1", sheet: "main", column: "ambulance" });
});

test("an unknown view falls back to the main sheet", () => {
  assert.deepEqual(parse("#/2027/nope", 2027), { year: 2027, view: "main" });
});

test("a malformed escape is read as it is", () => {
  assert.deepEqual(parse("#/2027/main/%/x", 2027), { year: 2027, view: "main", plan: "%", sheet: "main", column: "x" });
});

test("a pipeline link with no step opens the cell's first step", () => {
  assert.deepEqual(parse("#/2027/how/main/H1/ambulance", 2027),
    { year: 2027, view: "how", plan: "H1", sheet: "main", column: "ambulance" });
});
