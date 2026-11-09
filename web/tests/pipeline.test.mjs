import { test } from "node:test";
import assert from "node:assert/strict";
import { NODES, STEPS, LINKS, nodeBox, pillBox, edge, before, after, stepById, chain, strip } from "../static/pipeline.js";

const inside = ([x, y], b) => x > b.x && x < b.x + b.w && y > b.y && y < b.y + b.h;

test("no edge passes behind a node", () => {
  for (const [from, to] of [...STEPS.map((s) => [s.from, s.to]), ...LINKS]) {
    const { at } = edge(from, to);
    for (const id of Object.keys(NODES)) {
      if (id === from || id === to) continue;
      for (let t = 0; t <= 1; t += 0.01) assert.ok(!inside(at(t), nodeBox(id)), `${from}→${to} crosses ${id}`);
    }
  }
});

const overlap = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

test("step labels overlap no node and no other label", () => {
  for (const s of STEPS) {
    for (const id of Object.keys(NODES)) assert.ok(!overlap(pillBox(s), nodeBox(id)), `${s.id} label covers ${id}`);
    for (const t of STEPS) if (s !== t) assert.ok(!overlap(pillBox(s), pillBox(t)), `${s.id} and ${t.id} labels`);
  }
});

test("no two nodes overlap", () => {
  const ids = Object.keys(NODES);
  for (const a of ids) for (const b of ids) {
    if (a < b) assert.ok(`${NODES[a].col},${NODES[a].row}` !== `${NODES[b].col},${NODES[b].row}`, `${a} and ${b}`);
  }
});

test("every step joins two known nodes and has a unique id", () => {
  assert.equal(new Set(STEPS.map((s) => s.id)).size, STEPS.length);
  for (const s of STEPS) assert.ok(NODES[s.from] && NODES[s.to], s.id);
});

test("highlighted rows exist", () => {
  for (const s of STEPS.filter((s) => s.example)) {
    [s.from, s.to].forEach((id, i) => {
      const n = NODES[id], count = (n.table?.rows ?? n.text.lines).length;
      for (const r of s.example.highlight[i]) assert.ok(r < count, `${s.id} row ${r} of ${id}`);
    });
  }
});

test("each side of a step highlights the cell's rows or explains why there are none", () => {
  for (const s of STEPS.filter((s) => s.example)) for (const i of [0, 1]) assert.ok(s.example.highlight[i].length || s.example.none?.[i], `${s.id} side ${i}`);
});

test("neighbouring steps share a table", () => {
  const rules = stepById("column-rules");
  assert.deepEqual(before(rules).map((s) => s.id), ["check-facts"]);
  assert.deepEqual(after(rules).map((s) => s.id), ["stack-presented"]);
  assert.deepEqual(before(stepById("list-plans")), []);
});

const trace = ({ value = "$5", rule = "none", blanks = false, cited = false, presented = false } = {}) => ({
  cell: { value },
  rule: { status: rule },
  model_citations: blanks ? { status: "traced", rows: [{ step: "blanks" }] } : { status: "not_traced_yet" },
  layers: { status: "traced", applied: [{ layer: "machine/blanks.csv", rows: cited ? [{}] : [] },
    { layer: "generated/presented.csv", rows: presented ? [{}] : [] }] },
});
const ids = (t) => chain(t).map((s) => s.id);

test("a CMS-only cell's chain is the plan, the draft and the live sheet", () => {
  assert.deepEqual(ids(trace()), ["list-plans", "draft", "stack-draft", "publish"]);
});

test("a cell with a rule reads facts from the documents but skips blank-cell citations", () => {
  const steps = ids(trace({ rule: "not_traced_yet" }));
  for (const id of ["find-pdfs", "read-facts", "check-facts", "column-rules", "added-facts"]) assert.ok(steps.includes(id), id);
  assert.ok(!steps.includes("cite-blanks"));
});

test("only a cell the presented layer cites stacks it", () => {
  assert.ok(!ids(trace({ rule: "not_traced_yet" })).includes("stack-presented"));
  assert.ok(ids(trace({ rule: "not_traced_yet", presented: true })).includes("stack-presented"));
});

test("a blank cell, or one with a blank-cell citation, goes through the blanks step and its documents", () => {
  for (const t of [trace({ value: "" }), trace({ blanks: true })]) {
    assert.deepEqual(ids(t), ["list-plans", "find-pdfs", "download", "extract-text", "draft", "cite-blanks", "stack-draft", "publish"]);
  }
});

test("a cell cited by another layer uses the documents", () => {
  assert.ok(ids(trace({ cited: true })).includes("download"));
});

test("without a trace, the chain is every step", () => {
  assert.equal(chain(null), STEPS);
});

const EOC = "https://x/eoc.pdf";
const full = {
  cell: { value: "" },
  plan: { status: "traced", row: { plan_id: "H1-1-0", plan_name: "Plan One" } },
  documents: { status: "traced", documents: [{ kind: "SB", url: "https://x/sb.pdf", found_via: "Links sheet", pages: 10 },
    { kind: "EOC", url: EOC, found_via: "Links sheet", pages: 90 }] },
  draft: { status: "traced", value: "$0" },
  model_citations: { status: "traced", rows: [{ step: "blanks", url: EOC, pdf_page: 5 }, { step: "xref", url: EOC, pdf_page: 6 }] },
  layers: { status: "traced", draft: "$0", applied: [{ layer: "generated/presented.csv", value: "", rows: [{ url: EOC, pdf_page: 5 }] }],
    live: { value: "", citations: [{ url: EOC, pdf_page: 5 }, { url: EOC, pdf_page: 7 }] } },
};
const stripOf = (id) => strip(stepById(id), full);

test("each step's strip reads the cell's own records", () => {
  assert.deepEqual(stripOf("list-plans"), ["H1-1-0 in the Landscape file", "plans.csv: Plan One"]);
  assert.deepEqual(stripOf("find-pdfs"), ["Links sheet", "SB and EOC URLs"]);
  assert.deepEqual(stripOf("download"), ["2 URLs", "SB, 10 pages; EOC, 90 pages"]);
  assert.deepEqual(stripOf("extract-text"), ["2 PDFs", "text of 100 pages"]);
  assert.deepEqual(stripOf("draft"), ["the plan's CMS fields", "$0"]);
  assert.deepEqual(stripOf("cite-blanks"), ["blank", "1 quote from EOC page 5"]);
  assert.deepEqual(stripOf("stack-draft"), ["draft $0", "bottom layer"]);
  assert.deepEqual(stripOf("stack-presented"), ["presented blank, 1 quote from EOC page 5", "live blank"]);
  assert.deepEqual(stripOf("publish"), ["live blank", "2 quotes from EOC page 5, EOC page 7"]);
});

test("a step whose record the trace lacks, or that has no strip, gets none", () => {
  assert.equal(strip(stepById("list-plans"), { ...full, plan: { status: "not_recorded" } }), null);
  assert.equal(strip(stepById("read-facts"), full), null);
  assert.equal(strip(stepById("draft"), null), null);
});
