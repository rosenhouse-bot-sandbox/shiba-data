import { test } from "node:test";
import assert from "node:assert/strict";
import { shown, sortRows, toCsv, ordered, pageOf, rowCount, known, PAGE_SIZE } from "../static/tables.js";

const facts = [
  { plan_id: "H1", benefit: "ambulance.ground", amount: "$325", page: "46", quotes: '["$325 copayment"]' },
  { plan_id: "H1", benefit: "dental", amount: "$1,500", page: "9", quotes: "[]" },
  { plan_id: "H2", benefit: "ambulance.air", amount: "20%", page: "", quotes: "[]" },
];

test("a plan filter keeps that plan's rows, including documents that cover several plans", () => {
  assert.deepEqual(shown(facts, { plan: "H1" }).map((r) => r.benefit), ["ambulance.ground", "dental"]);
  const docs = [{ plan_ids: "H1;H2", kind: "EOC" }, { plan_ids: "H2", kind: "SB" }, { plan_ids: "H11", kind: "SB" }];
  assert.deepEqual(shown(docs, { plan: "H1" }), [docs[0]]);
  assert.deepEqual(shown(docs, {}), docs);
});

test("a column filter keeps the rows of that sheet's column, and does not apply to a table without columns", () => {
  const presented = [
    { sheet: "main", plan_id: "H1", column: "C_premium" },
    { sheet: "dvha", plan_id: "H1", column: "C_premium" },
    { sheet: "main", plan_id: "H1", column: "AB_ambulance" },
  ];
  assert.deepEqual(shown(presented, { sheet: "dvha", column: "C_premium" }), [presented[1]]);
  const sources = [{ plan_id: "H1", column: "C_premium" }, { plan_id: "H1", column: "E_moop" }];
  assert.deepEqual(shown(sources, { sheet: "main", column: "C_premium" }), [sources[0]]);
  assert.deepEqual(shown(facts, { sheet: "main", column: "C_premium" }), facts);
});

test("a search matches any value, ignoring case", () => {
  assert.deepEqual(shown(facts, { query: "AMBULANCE" }).length, 2);
  assert.deepEqual(shown(facts, { query: "copayment" }), [facts[0]]);
  assert.deepEqual(shown(facts, { query: " " }), facts);
});

test("a column of amounts or pages sorts as numbers, with blanks last", () => {
  assert.deepEqual(sortRows(facts, "page", "ascending").map((r) => r.page), ["9", "46", ""]);
  assert.deepEqual(sortRows(facts, "page", "descending").map((r) => r.page), ["46", "9", ""]);
  assert.deepEqual(sortRows(facts, "amount", "ascending").map((r) => r.amount), ["20%", "$325", "$1,500"]);
});

test("a column with a value that is only a sign or symbol sorts as text", () => {
  const rows = ["5", "-", "3", "$", "10", "1"].map((v) => ({ v }));
  assert.deepEqual(sortRows(rows, "v", "ascending").map((r) => r.v), ["-", "$", "1", "3", "5", "10"]);
});

test("a text column sorts by its words, with numbers in order", () => {
  const rows = [{ id: "H10-1" }, { id: "h2-1" }, { id: "H1-1" }];
  assert.deepEqual(sortRows(rows, "id", "ascending").map((r) => r.id), ["H1-1", "h2-1", "H10-1"]);
});

test("sorting keeps the order of equal rows, and does not change the rows it is given", () => {
  const rows = [{ k: "b", n: 1 }, { k: "a", n: 2 }, { k: "b", n: 3 }];
  assert.deepEqual(sortRows(rows, "k", "descending").map((r) => r.n), [1, 3, 2]);
  assert.deepEqual(rows.map((r) => r.n), [1, 2, 3]);
});

test("pages hold 100 rows, and a page past the end shows the last page", () => {
  const rows = Array.from({ length: 250 }, (_, n) => ({ n }));
  assert.equal(PAGE_SIZE, 100);
  assert.deepEqual(pageOf(rows, 1), { page: 1, pages: 3, first: 1, last: 100, rows: rows.slice(0, 100) });
  assert.deepEqual(pageOf(rows, 9), { page: 3, pages: 3, first: 201, last: 250, rows: rows.slice(200) });
  assert.deepEqual(pageOf([], 1), { page: 1, pages: 1, first: 0, last: 0, rows: [] });
});

test("CSV quotes values that need it", () => {
  assert.equal(toCsv(["a", "b"], [{ a: 'say "hi"', b: "x,y" }, { a: "1", b: "line\nbreak" }]),
    'a,b\r\n"say ""hi""","x,y"\r\n1,"line\nbreak"\r\n');
});

test("tables list in the pipeline's order, then the rest by name", () => {
  assert.deepEqual(ordered(["presented", "zeta", "plans", "alpha", "document_facts"]),
    ["plans", "document_facts", "presented", "alpha", "zeta"]);
});

test("row counts read in words", () => {
  assert.equal(rowCount(1), "1 row");
  assert.equal(rowCount(7837), "7,837 rows");
});

test("a link's plan or column that matches no row is dropped, and so is a column for a table without one", () => {
  const presented = [{ sheet: "main", plan_id: "H1", column: "C_premium" }, { sheet: "dvha", plan_id: "H2", column: "G_vision" }];
  const state = { view: "tables", table: "presented" };
  assert.deepEqual(known({ ...state, plan: "H2", sheet: "dvha", column: "G_vision" }, presented),
    { ...state, plan: "H2", sheet: "dvha", column: "G_vision" });
  assert.deepEqual(known({ ...state, plan: "BOGUS", sheet: "main", column: "G_vision" }, presented),
    { ...state, plan: undefined, sheet: undefined, column: undefined });
  const docs = [{ plan_ids: "H1;H2", kind: "EOC" }];
  assert.deepEqual(known({ ...state, plan: "H2", sheet: "main", column: "C_premium" }, docs), { ...state, plan: "H2", sheet: undefined, column: undefined });
});

test("a text column sorts amounts with thousands separators by their value", () => {
  const rows = ["$1,980 per admit", "$250 | 1-5", "$10", "n/a", "$5,100"].map((v) => ({ v }));
  assert.deepEqual(sortRows(rows, "v", "ascending").map((r) => r.v), ["$10", "$250 | 1-5", "$1,980 per admit", "$5,100", "n/a"]);
});

test("a table without a sheet field holds the main sheet's columns", () => {
  const sources = [{ plan_id: "H1", column: "C_premium" }];
  assert.deepEqual(shown(sources, { sheet: "dvha", column: "C_premium" }), []);
  assert.deepEqual(known({ sheet: "dvha", column: "C_premium" }, sources), { plan: undefined, sheet: undefined, column: undefined });
  assert.deepEqual(known({ sheet: "main", column: "C_premium" }, sources), { plan: undefined, sheet: "main", column: "C_premium" });
});
