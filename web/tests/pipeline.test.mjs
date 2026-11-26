import { test } from "node:test";
import fs from "node:fs";
import assert from "node:assert/strict";
import { NODES, STEPS, RING, MIN_GAP, inputs, nodeBox, pillBox, paths, before, after, stepById, strip, details, records } from "../static/pipeline.js";

const inside = ([x, y], b) => x > b.x && x < b.x + b.w && y > b.y && y < b.y + b.h;

test("no edge passes behind a node", () => {
  for (const s of STEPS) for (const { at } of paths(s)) {
    for (const id of Object.keys(NODES)) {
      if (id === s.to || inputs(s).includes(id)) continue;
      for (let t = 0; t <= 1; t += 0.01) assert.ok(!inside(at(t), nodeBox(id)), `${s.id} crosses ${id}`);
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

// Boxes side by side may share rows; boxes above one another keep MIN_GAP between them, outside a node's ring.
const verticalGap = ([a, ar], [b, br]) => a.x < b.x + b.w && b.x < a.x + a.w ? Math.max(b.y - (a.y + a.h), a.y - (b.y + b.h)) - ar - br : Infinity;

test("boxes above one another keep a minimum gap outside any ring", () => {
  assert.ok(MIN_GAP >= 16);
  const boxes = [...Object.keys(NODES).map((id) => [id, nodeBox(id), RING]), ...STEPS.map((s) => [s.id, pillBox(s), 0])];
  for (const [i, [a, ...ab]] of boxes.entries()) for (const [b, ...bb] of boxes.slice(i + 1)) {
    assert.ok(verticalGap(ab, bb) >= MIN_GAP, `${a} and ${b} are ${verticalGap(ab, bb)}px apart`);
  }
});

test("every edge runs downward", () => {
  for (const s of STEPS) for (const { at } of paths(s)) assert.ok(at(1)[1] > at(0)[1], s.id);
});

test("no two nodes overlap", () => {
  const ids = Object.keys(NODES);
  for (const a of ids) for (const b of ids) {
    if (a < b) assert.ok(`${NODES[a].col},${NODES[a].row}` !== `${NODES[b].col},${NODES[b].row}`, `${a} and ${b}`);
  }
});

test("every step joins known nodes and has a unique id", () => {
  assert.equal(new Set(STEPS.map((s) => s.id)).size, STEPS.length);
  for (const s of STEPS) for (const id of [...inputs(s), s.to]) assert.ok(NODES[id], s.id);
});

test("a step's inputs join at its one label, which points to its output", () => {
  assert.deepEqual(inputs(stepById("find-pdfs")), ["links", "plans", "found"]);
  assert.deepEqual(inputs(stepById("sheet")), ["facts", "pbp"]);
  assert.deepEqual(inputs(stepById("publish")), ["sheet", "presented"]);
  for (const s of STEPS.filter((s) => inputs(s).length > 1)) {
    const p = pillBox(s), top = [p.x + p.w / 2, p.y], bottom = [p.x + p.w / 2, p.y + p.h];
    const ins = paths(s).filter((e) => !e.arrow), [out] = paths(s).filter((e) => e.arrow);
    assert.equal(ins.length, inputs(s).length, s.id);
    for (const e of ins) assert.deepEqual(e.at(1), top, s.id);
    assert.deepEqual(out.at(0), bottom, s.id);
    const to = nodeBox(s.to);
    assert.deepEqual(out.at(1), [to.x + to.w / 2, to.y], s.id);
    assert.ok(p.y > Math.max(...inputs(s).map((id) => nodeBox(id).y + nodeBox(id).h)), `${s.id} label sits below its inputs`);
  }
});

test("each step draws one arrow, into its output", () => {
  for (const s of STEPS) {
    const arrows = paths(s).filter((e) => e.arrow), to = nodeBox(s.to);
    assert.equal(arrows.length, 1, s.id);
    assert.deepEqual(arrows[0].at(1), [to.x + to.w / 2, to.y], s.id);
  }
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
  assert.deepEqual(after(rules).map((s) => s.id), ["publish"]);
  assert.deepEqual(after(stepById("sheet")).map((s) => s.id), ["publish"]);
  assert.deepEqual(before(stepById("list-plans")), []);
  assert.deepEqual(after(stepById("list-plans")).map((s) => s.id), ["find-pdfs"]);
  assert.deepEqual(before(stepById("publish")).map((s) => s.id), ["column-rules", "sheet"]);
});

const EOC = "https://x/eoc.pdf";
const full = {
  cell: { value: "" },
  plan: { status: "traced", row: { plan_id: "H1-1-0", plan_name: "Plan One", organization: "Org One" } },
  documents: { status: "traced", documents: [{ kind: "SB", url: "https://x/sb.pdf", found_via: "Links sheet", pages: 10, cover_problems: "" },
    { kind: "EOC", url: EOC, found_via: "Links sheet", pages: 90, cover_problems: "" },
    { kind: "RIDER", url: "https://x/rider.pdf", found_via: "carrier page", pages: 4, cover_problems: "no year" }],
    candidates: [{ source: "found.csv", kind: "RIDER", url: "https://x/rider.pdf", found_via: "carrier page", used: true },
      { source: "links.csv", kind: "SB", url: "https://x/sb.pdf", found_via: "Links sheet", used: true },
      { source: "links.csv", kind: "EOC", url: EOC, found_via: "Links sheet", used: true },
      { source: "URL template", kind: "SB", url: "https://x/sb.pdf", found_via: "URL template", used: false },
      { source: "URL template", kind: "EOC", url: "https://x/other.pdf", found_via: "URL template", used: false }] },
  sheet: { status: "traced", value: "" },
  citations: { status: "traced", shown: [{ url: EOC, pdf_page: 5 }, { url: "https://x/sb.pdf", pdf_page: 2 }], hidden: [] },
};
const stripOf = (id, t = full) => strip(stepById(id), t);

test("each step's strip reads the cell's own records", () => {
  assert.deepEqual(stripOf("list-plans"), ["H1-1-0 in the Landscape file", "plans.csv: Plan One"]);
  assert.deepEqual(stripOf("find-pdfs"), ["5 URLs from 3 sources", "SB, EOC and RIDER URLs"]);
  assert.deepEqual(stripOf("download"), ["3 URLs", "SB, 10 pages; EOC, 90 pages; RIDER, 4 pages, cover problems"]);
  assert.deepEqual(stripOf("extract-text"), ["3 PDFs", "text of 104 pages"]);
  assert.deepEqual(stripOf("sheet"), ["the column rule", "blank"]);
  assert.deepEqual(stripOf("publish"), ["sheet blank", "site cell blank with 2 quotes from EOC page 5; SB page 2"]);
});

test("Find PDFs shows the plan's row and every URL each source offered, marking the ones it kept", () => {
  const [plan, offered] = records(stepById("find-pdfs"), full);
  assert.deepEqual(plan.rows, [["H1-1-0", "Plan One", "Org One"]]);
  assert.deepEqual(offered.rows.map((r) => r.slice(0, 2)),
    [["found.csv", "RIDER"], ["links.csv", "SB"], ["links.csv", "EOC"], ["URL template", "SB"], ["URL template", "EOC"]]);
  assert.deepEqual(offered.hi, [0, 1, 2]);
});

test("a strip says when the trace has no quotes to name", () => {
  const bare = { ...full, sheet: { status: "traced", value: "$0" }, citations: { status: "traced", shown: [], hidden: [] } };
  assert.deepEqual(stripOf("publish", bare), ["sheet $0", "site cell $0 with no quotes"]);
});

test("a step whose record the trace lacks, or that has no strip, gets none", () => {
  assert.equal(strip(stepById("list-plans"), { ...full, plan: { status: "not_recorded" } }), null);
  assert.equal(strip(stepById("read-facts"), full), null);
  assert.equal(strip(stepById("sheet"), null), null);
});

// A replayed build's trace of the example cell, which records answers, checks and the rule.
const replay = JSON.parse(fs.readFileSync(new URL("./fixtures/replay_trace.json", import.meta.url)));

test("a replayed trace writes the fact steps' strips", () => {
  assert.deepEqual(strip(stepById("read-facts"), replay), ["SB and EOC page text", "4 saved answers from claude-opus-5-5"]);
  assert.deepEqual(strip(stepById("check-facts"), replay), ["8 facts", "7 kept, 1 rejected"]);
  assert.deepEqual(strip(stepById("column-rules"), replay), ["5 facts used, 2 set aside", "line 1 $325 or 20%; line 2 $325"]);
});

test("every step shows a replayed cell's input and output rows", () => {
  for (const s of STEPS) {
    const tables = records(s, replay);
    for (const role of ["Input", "Output"]) assert.ok(tables.some((r) => r.role === role && r.rows.length), `${s.id} ${role}`);
    for (const r of tables) for (const row of r.rows) assert.equal(row.length, r.cols.length, `${s.id} ${r.name}`);
  }
});

test("a step shows the tables whose records the trace has", () => {
  const unread = { ...replay, answers: { status: "not_recorded" } };
  assert.deepEqual(records(stepById("read-facts"), unread).map((r) => r.name), ["page text"]);
  assert.deepEqual(records(stepById("find-pdfs"), { ...replay, plan: { status: "none" } }).map((r) => r.name), ["URLs offered", "documents.csv"]);
});

test("Read facts lists only the reader prompts' answers", () => {
  const [, answers] = records(stepById("read-facts"), replay);
  assert.deepEqual(answers.rows.map((r) => r.slice(2)), [["EOC", "ambulance"], ["SB", "ambulance"]]);
});

test("Extract page text outputs the text files, named by the text's hash and linked to their blobs", () => {
  const [pdfs, text] = records(stepById("extract-text"), replay);
  const docs = replay.documents.documents;
  assert.deepEqual(text.rows.map((r) => r[2]), docs.map((d) => ({ text: `${d.text.layout.slice(0, 16)}…`, href: `blobs/${d.text.layout}.txt` })));
  assert.deepEqual(pdfs.rows.map((r) => r[1]), docs.map((d) => ({ text: `${d.sha256.slice(0, 16)}…`, href: `docs/${d.sha256}.pdf` })));
});

test("the example's page text links to its blob", () => {
  const { name, href } = NODES.text.text;
  assert.equal(href, `blobs/${replay.documents.documents[0].text.layout}.txt`);
  assert.ok(href.startsWith(`blobs/${name.replace(".txt", "")}`));
});

test("Publish outputs only the shown citations, naming each document", () => {
  const [first, ...rest] = replay.citations.shown;
  const t = { ...replay, citations: { status: "traced", shown: rest, hidden: [first] } };
  const [, presented, site] = records(stepById("publish"), t);
  assert.equal(presented.rows.length, 5);
  assert.deepEqual(presented.hi, [0, 1, 2, 3]);
  assert.deepEqual(site.rows, presented.rows.slice(0, 4));
  assert.deepEqual(new Set(site.rows.map((r) => r[2])), new Set(["EOC"]));
});

test("Check facts marks the kept facts and outputs only those", () => {
  const [stated, kept] = records(stepById("check-facts"), replay);
  assert.equal(stated.rows.length, 8);
  assert.equal(stated.hi.length, 7);
  assert.deepEqual(kept.rows.map((r) => r.slice(2)), stated.hi.map((i) => stated.rows[i].slice(2)));
});

test("Column rules marks the facts its lines used", () => {
  const [facts, cited] = records(stepById("column-rules"), replay);
  assert.equal(facts.rows.length, 7);
  assert.deepEqual(facts.hi, [0, 1, 2, 3, 4]);
  assert.equal(cited.rows.length, 5);
});

test("a held cell's rule strip says why", () => {
  const held = { ...replay, rule: { ...replay.rule, held: "the EOC and SB disagree", lines: [] } };
  assert.deepEqual(strip(stepById("column-rules"), held), ["0 facts used, 2 set aside", "held: the EOC and SB disagree"]);
});

test("every step has a strip for a replayed trace", () => {
  assert.deepEqual(STEPS.filter((s) => !strip(s, replay)).map((s) => s.id), []);
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
  const t = withPrompts(["facts/a/reread", "ce13e925c0384896.retry.md"], ["facts/review", "v-0.md"],
    ["facts/a/recheck", "v-0123456789abcdef.md"]);
  assert.deepEqual(lines("read-facts", t).slice(2), ["SB second reader prompt, retried, answered by m"]);
  assert.deepEqual(lines("check-facts", t).slice(-2), ["reviewer prompt, answered by m",
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
  assert.deepEqual(lines("column-rules", t), ["The rule leaves this cell blank, because the EOC and SB disagree",
    "Set aside PBP, ambulance.air 20%: SB ranks below EOC"]);
});

test("a step without a traced record has no details", () => {
  assert.deepEqual(lines("check-facts", { ...replay, fact_checks: { status: "not_recorded" } }), []);
  assert.deepEqual(lines("check-facts", { ...replay, answers: { status: "not_recorded" } }).length, 8);
  assert.deepEqual(lines("sheet"), []);
  assert.deepEqual(details(stepById("sheet"), null), []);
});
