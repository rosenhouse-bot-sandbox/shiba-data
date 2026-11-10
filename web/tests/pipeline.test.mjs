import { test } from "node:test";
import fs from "node:fs";
import assert from "node:assert/strict";
import { NODES, STEPS, LINKS, nodeBox, pillBox, edge, before, after, stepById, chain, strip, details } from "../static/pipeline.js";

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

const trace = ({ presented = false } = {}) => ({
  cell: { value: "$5" },
  rule: { status: "not_recorded" },
  layers: { status: "traced", applied: [{ layer: "generated/presented.csv", rows: presented ? [{}] : [] }] },
});
const ids = (t) => chain(t).map((s) => s.id);

test("every cell reads facts from the documents", () => {
  const steps = ids(trace());
  for (const id of ["find-pdfs", "read-facts", "check-facts", "column-rules", "added-facts"]) assert.ok(steps.includes(id), id);
});

test("only a cell the presented layer cites stacks it", () => {
  assert.ok(!ids(trace()).includes("stack-presented"));
  assert.ok(ids(trace({ presented: true })).includes("stack-presented"));
});

test("without a trace, the chain is every step", () => {
  assert.equal(chain(null), STEPS);
});

const EOC = "https://x/eoc.pdf";
const full = {
  cell: { value: "" },
  plan: { status: "traced", row: { plan_id: "H1-1-0", plan_name: "Plan One" } },
  documents: { status: "traced", documents: [{ kind: "SB", url: "https://x/sb.pdf", found_via: "Links sheet", pages: 10, cover_problems: "" },
    { kind: "EOC", url: EOC, found_via: "Links sheet", pages: 90, cover_problems: "" },
    { kind: "RIDER", url: "https://x/rider.pdf", found_via: "carrier page", pages: 4, cover_problems: "no year" }] },
  draft: { status: "traced", value: "$0" },
  layers: { status: "traced", draft: "$0", applied: [{ layer: "generated/presented.csv", value: "", rows: [{ url: EOC, pdf_page: 5 }] }],
    live: { value: "", set_by: "generated/presented.csv", citations: [{ url: EOC, pdf_page: 5 }, { url: "https://x/sb.pdf", pdf_page: 2 }] } },
};
const stripOf = (id, t = full) => strip(stepById(id), t);

test("each step's strip reads the cell's own records", () => {
  assert.deepEqual(stripOf("list-plans"), ["H1-1-0 in the Landscape file", "plans.csv: Plan One"]);
  assert.deepEqual(stripOf("find-pdfs"), ["2 sources", "SB, EOC and RIDER URLs"]);
  assert.deepEqual(stripOf("download"), ["3 URLs", "SB, 10 pages; EOC, 90 pages; RIDER, 4 pages, cover problems"]);
  assert.deepEqual(stripOf("extract-text"), ["3 PDFs", "text of 104 pages"]);
  assert.deepEqual(stripOf("draft"), ["the column rule", "$0"]);
  assert.deepEqual(stripOf("stack-draft"), ["draft $0", "live blank, set by generated/presented.csv"]);
  assert.deepEqual(stripOf("stack-presented"), ["presented blank, 1 quote from EOC page 5", "live blank"]);
  assert.deepEqual(stripOf("publish"), ["live blank", "site cell blank with 2 quotes from EOC page 5; SB page 2"]);
});

test("a strip says when the trace has no quotes to name", () => {
  const bare = { ...full, layers: { ...full.layers, live: { value: "$0", citations: [] } } };
  assert.deepEqual(stripOf("stack-draft", bare), ["draft $0", "live $0"]);
  assert.deepEqual(stripOf("publish", bare), ["live $0", "site cell $0 with no quotes"]);
});

test("a step whose record the trace lacks, or that has no strip, gets none", () => {
  assert.equal(strip(stepById("list-plans"), { ...full, plan: { status: "not_recorded" } }), null);
  assert.equal(strip(stepById("read-facts"), full), null);
  assert.equal(strip(stepById("draft"), null), null);
});

// A replayed build's trace of the example cell, which records answers, checks and the rule.
const replay = JSON.parse(fs.readFileSync(new URL("./fixtures/replay_trace.json", import.meta.url)));

test("a replayed trace writes the fact steps' strips", () => {
  assert.deepEqual(strip(stepById("read-facts"), replay), ["SB and EOC page text", "4 saved answers from claude-opus-5-5"]);
  assert.deepEqual(strip(stepById("check-facts"), replay), ["8 facts", "7 kept, 1 rejected"]);
  assert.deepEqual(strip(stepById("column-rules"), replay), ["5 facts used, 2 set aside", "line 1 $325 or 20%; line 2 $325"]);
});

test("a held cell's rule strip says why", () => {
  const held = { ...replay, rule: { ...replay.rule, held: "the EOC and SB disagree", lines: [] } };
  assert.deepEqual(strip(stepById("column-rules"), held), ["0 facts used, 2 set aside", "held: the EOC and SB disagree"]);
});

test("every step of a replayed trace's chain has a strip, except added facts the cell lacks", () => {
  const missing = chain(replay).filter((s) => !strip(s, replay)).map((s) => s.id);
  assert.deepEqual(missing, ["added-facts"]);
});

const BLOBS = "https://pdxplans.org/blobs/";
const lines = (id, t = replay) => details(stepById(id), t).map((l) => l.text);

test("Claude reads facts links each reader prompt", () => {
  assert.deepEqual(details(stepById("read-facts"), replay), [
    { text: "EOC reader prompt, answered by claude-opus-5-5", href: `${BLOBS}226ee67e4a27f3e7c117e6aa8e197a07423fac0b4d1fe9b6d6033e8602313064.txt` },
    { text: "SB reader prompt, answered by claude-opus-5-5", href: `${BLOBS}6761dbbfbd4ec26bccf84990d6d9db9b6ff67e7aa12674da3851203ab390d96b.txt` },
  ]);
});

// The replayed trace with one more answer whose prompts sit in the given dirs and tasks.
const withPrompts = (...prompts) => ({ ...replay, answers: { ...replay.answers, rows: [...replay.answers.rows,
  { model: "m", prompts: prompts.map(([dir, task]) => ({ dir, task, prompt: task, url: task })) }] } });

test("a prompt's label names its role, its document when known, and a retry", () => {
  const t = withPrompts(["facts/a/reread", "ce13e925c0384896.retry.md"], ["facts/review", "v-0.md"], ["facts/review/earlier", "v-1.md"],
    ["facts/a/recheck", "v-0123456789abcdef.md"]);
  assert.deepEqual(lines("read-facts", t).slice(2), ["SB second reader prompt, retried, answered by m"]);
  assert.deepEqual(lines("check-facts", t).slice(-3), ["reviewer prompt, answered by m", "earlier reviewer prompt, answered by m",
    "second verifier prompt, answered by m"]);
});

test("Check facts gives each fact's verdicts", () => {
  const got = lines("check-facts");
  assert.equal(got.length, 8 + 2);
  assert.equal(got[0], "Kept: EOC page 46, ambulance.ground $325. Verifier agreed: Page 46 ambulance row, In-Network, Emergency Ambulance: $325 copayment per date of service for Ground Ambulance.");
  assert.match(got[7], /^Rejected: SB page 6, ambulance \$325\. Verifier disagreed: The page 6 Worldwide Coverage/);
  assert.deepEqual(got.slice(8), ["EOC verifier prompt, answered by claude-opus-5-5", "SB verifier prompt, answered by claude-opus-5-5"]);
});

test("a fact that failed its quote check names its document from the prompt that stated it, and the reviewer's verdict shows", () => {
  const [row] = replay.fact_checks.rows.filter((r) => r.fact?.source === "SB");
  const failed = { ...row, fact: null, code_check: "quote not found", kept: false,
    reviewer: { status: "traced", ok: false, reason: "Wrong row." } };
  const t = { ...replay, fact_checks: { status: "traced", rows: [failed] } };
  assert.match(lines("check-facts", t)[0],
    /^Rejected: SB page 9, ambulance\.\w+ \S+\. Quote check failed: quote not found\. Verifier agreed: .*\. Reviewer disagreed: Wrong row\.$/);
});

test("Column rules lists the facts each line used and why others were set aside", () => {
  const got = lines("column-rules");
  assert.ok(got.includes("Line 2 ($325) used EOC page 46, ambulance $325"));
  assert.ok(got.includes("Set aside SB page 9, ambulance.air 20%: SB ranks below EOC"));
});

test("a held rule says why, and a fact with no page names none", () => {
  const pbp = { ...replay.rule.set_aside[0], source: "PBP", page: "" };
  const t = { ...replay, rule: { ...replay.rule, held: "the EOC and SB disagree", lines: [], set_aside: [pbp] } };
  assert.deepEqual(lines("column-rules", t), ["The rule leaves this cell as it was, because the EOC and SB disagree",
    "Set aside PBP, ambulance.air 20%: SB ranks below EOC"]);
});

test("a step without a traced record has no details", () => {
  assert.deepEqual(lines("check-facts", { ...replay, fact_checks: { status: "not_recorded" } }), []);
  assert.deepEqual(lines("check-facts", { ...replay, answers: { status: "not_recorded" } }).length, 8);
  assert.deepEqual(lines("draft"), []);
  assert.deepEqual(details(stepById("draft"), null), []);
});
