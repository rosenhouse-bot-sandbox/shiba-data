// The pipeline as a graph: tables are nodes and operations are edges.
// The rows are the example cell's, copied from main's 2027 data.

export const EXAMPLE = { sheet: "main", plan: "H1036-153-0", column: "ambulance" };

// col and row place a node in the map's lanes.
export const NODES = {
  landscape: { col: 0, row: 0, kind: "CMS source", source: true, label: "Landscape.csv",
    table: { name: "CY2027_Landscape_202610.csv", note: "one row per plan per county",
      cols: ["Contract Plan Segment ID", "Plan Name", "County Name", "Plan Type", "SNP Type", "Part C Premium", "In-Network MOOP"],
      rows: [["H1036_153_0", "Humana Total Complete (HMO)", "Multnomah", "HMO", "Not Applicable", "$0.00", "$5,150.00"],
        ["H1036_153_0", "Humana Total Complete (HMO)", "Clackamas", "HMO", "Not Applicable", "$0.00", "$5,150.00"]] } },
  links: { col: 1, row: 0, kind: "Links sheet", source: true, label: "links.csv",
    table: { name: "links.csv", note: "copied from the volunteers' Links sheet", cols: ["plan_ids", "kind", "url"],
      rows: [["H1036-153-0", "SB", "https://assets.humana.com/is/content/humana/H1036153000SB27pdf"],
        ["H1036-153-0", "EOC", "https://assets.humana.com/is/content/humana/H1036153000EOC27pdf"]] } },
  pbp: { col: 2, row: 5, kind: "CMS source", source: true, label: "PBP tables",
    table: { name: "pbp_Section_D.txt", note: "the plan's deductible fields, which become facts the rules read; the ambulance rule reads none",
      cols: ["bid_id", "pbp_d_inn_deduct_yn"], rows: [["H1036_153_0", "2"]] } },
  plans: { col: 0, row: 1, kind: "table", label: "plans.csv",
    table: { name: "generated/plans.csv", note: "39 rows", cols: ["plan_id", "plan_name", "plan_type", "organization", "premium", "moop_in_network"],
      rows: [["H1036-153-0", "Humana Total Complete (HMO)", "HMO", "Humana", "$0", "$5,150"]] } },
  documents: { col: 1, row: 2, kind: "table", label: "documents.csv",
    table: { name: "generated/documents.csv", note: "one URL per plan and kind", cols: ["plan_ids", "kind", "url", "found_via"],
      rows: [["H1036-153-0", "SB", "…/H1036153000SB27pdf", "volunteers' Links sheet"],
        ["H1036-153-0", "EOC", "…/H1036153000EOC27pdf", "volunteers' Links sheet"]] } },
  checked: { col: 1, row: 3, kind: "table", label: "documents_checked",
    table: { name: "generated/documents_checked.csv", note: "selected columns", cols: ["plan_ids", "kind", "sha256", "pages", "cover_problems"],
      rows: [["H1036-153-0", "SB", "ce13e925c0384896d725da85a06c14df…", "24", ""],
        ["H1036-153-0", "EOC", "64e05773e847b56e0eeb5425979d5499…", "188", ""]] } },
  text: { col: 1, row: 4, kind: "files in R2", source: true, label: "page text",
    text: { name: "ce13e925c0384896.txt", note: "SB page 9",
      lines: ["=====PAGE 9=====", " SKILLED NURSING FACILITY (SNF)",
        " This plan covers up to 100 days in a SNF        $10 copay per day for days 1-20", " AMBULANCE",
        " Air                                             20% of the cost",
        " Ground                                          $325 copay per date of service",
        " TRANSPORTATION                                  Not Covered"] } },
  draft: { col: 2, row: 8, kind: "table", label: "main_chart.csv",
    table: { name: "generated/main_chart.csv", note: "every rule's value, selected columns", cols: ["plan_id", "plan_name", "AB_ambulance"],
      rows: [["H1036-153-0", "Humana Total Complete (HMO)", "$325 or 20% | $325"]] } },
  answers: { col: 0, row: 5, kind: "model answers", source: true, label: "answers/*.json",
    text: { name: "answers/e920fcee050a431f.json", note: "Claude Opus, high effort · 3,479 in / 954 out tokens",
      lines: [
        '[{"benefit": "ambulance.air", "setting": "any", "network": "in", "cost_kind": "coinsurance", "amount": "20%", "page": 9, "quotes": ["20% of the cost"]},',
        ' {"benefit": "ambulance.ground", "setting": "any", "network": "in", "cost_kind": "copay", "amount": "$325", "page": 9, "quotes": ["$325 copay per date of service"]},',
        ' {"benefit": "ambulance", "setting": "outside_us", "covered_by": "medicare", "amount": "$325", "page": 6, "quotes": ["Emergency ambulance: $325 copay per date of"]}]'] } },
  facts: { col: 0, row: 6, kind: "table", label: "document_facts",
    table: { name: "machine/document_facts.csv", note: "accepted facts, selected columns",
      cols: ["benefit", "setting", "network", "condition", "covered_by", "cost_kind", "amount", "source", "page"],
      rows: [["ambulance.ground", "any", "in", "Emergency Ambulance", "medicare", "copay", "$325", "EOC", "46"],
        ["ambulance.ground", "any", "in", "Non-Emergency Ambulance", "medicare", "copay", "$325", "EOC", "46"],
        ["ambulance.air", "any", "in", "Emergency Ambulance", "medicare", "coinsurance", "20%", "EOC", "46"],
        ["ambulance", "outside_us", "out", "Emergency Ambulance", "supplemental", "copay", "$325", "EOC", "46"],
        ["ambulance.ground", "any", "in", "", "medicare", "copay", "$325", "SB", "9"],
        ["ambulance.air", "any", "in", "", "medicare", "coinsurance", "20%", "SB", "9"]] } },
  presented: { col: 0, row: 8, kind: "table", label: "presented.csv",
    table: { name: "generated/presented.csv", note: "one row per citation", cols: ["plan_id", "column", "line", "value", "pdf_page", "quote"],
      rows: [["H1036-153-0", "AB_ambulance", "1", "$325 or 20%", "46", "In-Network: Emergency Ambulance $325 copayment per date of service regardless of the number of trips – Ground Ambulance"],
        ["H1036-153-0", "AB_ambulance", "1", "$325 or 20%", "46", "… Ground Ambulance 20% coinsurance regardless of the number of trips – Air Ambulance"],
        ["H1036-153-0", "AB_ambulance", "2", "$325", "46", "Worldwide Coverage $325 copayment per date of service regardless of the number of trips – Emergency Ambulance"]] } },
  live: { col: 1, row: 9, kind: "result", label: "live sheet",
    table: { name: "live sheet (main)", note: "after stacking the layers", cols: ["plan_id", "plan_name", "AB_ambulance", "citations"],
      rows: [["H1036-153-0", "Humana Total Complete (HMO)", "$325 or 20% | $325", "4 quotes, EOC page 46"]] } },
  site: { col: 1, row: 10, kind: "website", source: true, label: "pdxplans.org",
    text: { name: "pdxplans.org", note: "after a volunteer clicks the cell",
      lines: ["Humana Total Complete (HMO) · Ambulance", "  $325 or 20% | $325", "", "EOC page 46, highlighted in the PDF beside the sheet:",
        '  "In-Network: Emergency Ambulance $325 copayment per date of service regardless of the number',
        '   of trips – Ground Ambulance 20% coinsurance regardless of the number of trips – Air Ambulance"'] } },
};

export const DRAFT_FILES = { main: "main_chart.csv", dvha: "dvha.csv" };

// A paragraph is a list of segments: a string, or [term, text] for a term in web/terms.py.
// record names the key of the cell's trace (#181) that shows the step.
// paras hold for any cell. example holds only for the example cell, on the steps that touched it: highlight lists the example rows
// that the cell uses in the input and the output.
export const STEPS = [
  { id: "list-plans", record: "plan", from: "landscape", to: "plans", label: "List the plans",
    paras: [["Code keeps ", ["bothCounties", "plans sold in both counties"], ". A plan's Landscape rows become one row of plans.csv."]],
    example: { highlight: [[0, 1], [0]], before: "H1036_153_0 in Multnomah and Clackamas", after: "H1036-153-0, one row",
      paras: [["The plan has one Landscape row per county. 39 plans remain."]] } },
  { id: "find-pdfs", record: "documents", from: "links", to: "documents", label: "Find PDFs",
    paras: [["URLs come from browser searches of carrier sites by Claude sessions, the volunteers' Links sheet, and URL patterns. ", ["firstUrl", "The first URL found wins"], "."]],
    example: { highlight: [[0, 1], [0, 1]], before: "links.csv: …H1036153000EOC27pdf", after: "documents.csv: EOC URL",
      paras: [["This plan's URLs came from the Links sheet."]] } },
  { id: "download", record: "documents", from: "documents", to: "checked", label: "Download PDFs",
    paras: [["The pipeline downloads each PDF, runs a ", ["cover", "cover check"], ", and records the PDF's SHA-256 hash."]],
    example: { highlight: [[0], [0]], before: "…/H1036153000SB27pdf", after: "sha256 ce13e925…, 24 pages", paras: [] } },
  { id: "extract-text", record: "documents", from: "checked", to: "text", label: "Extract page text",
    paras: [["Code turns each page into ", ["layoutText", "text that keeps the page's columns"], ". The PDFs and texts are stored in R2, named by hash, so every later run reads the same bytes."]],
    example: { highlight: [[0], [3, 4, 5]], before: "PDF ce13e925…", after: "text of page 9", paras: [] } },
  { id: "read-facts", record: "answers", from: "text", to: "answers", label: "Claude reads facts",
    paras: [["The pipeline sends Claude Opus ", ["prompt", "one prompt"], " per document and benefit group. Claude answers with facts, each with its quotes and page."],
      ["The answer is ", ["hash", "saved under a hash of the model, effort and prompt"], ", so a rerun calls no model."]],
    example: { highlight: [[3, 4, 5], [0, 1, 2]], before: "Ground  $325 copay per date of service", after: "{benefit: ambulance.ground, amount: $325, page: 9}",
      paras: [["For this SB and the ambulance group, Claude answers with three facts."]] } },
  { id: "check-facts", record: "fact_checks", from: "answers", to: "facts", label: "Check facts",
    paras: [["Code runs a ", ["quoteCheck", "quote check"], " on every fact. A verifier, Claude Opus, then judges each fact mixed with ", ["decoy", "decoys"], ". Last, a ", ["reviewer", "reviewer"], " checks each fact a value would cite."]],
    example: { highlight: [[2], [3, 4, 5]], before: "SB: abroad, covered_by medicare", after: "rejected; the EOC's supplemental fact stands",
      paras: [["The verifier rejected the SB's worldwide fact: Medicare doesn't cover care abroad, so it is supplemental. The EOC's fact, already marked supplemental, passed."]] } },
  { id: "column-rules", record: "rule", from: "facts", to: "presented", label: "Column rules",
    paras: [["Each column has a rule, written in code from the domain expert's instructions. It takes facts from the ", ["bestSource", "best source"], " and cites their quotes."]],
    example: { highlight: [[0, 1, 2, 3], [0, 1, 2]], before: "ground $325, air 20%, abroad $325", after: "$325 or 20% | $325",
      paras: [["In the ", ["rule", "Ambulance rule"], ", line 1 takes in-network, Medicare-covered ground and air trips from the EOC. Line 2 takes trips abroad. Each line cites the quotes of the facts it used, so this cell gets four citations from EOC page 46."]] } },
  { id: "draft", record: "draft", from: "facts", to: "draft", label: "Draft sheet",
    paras: [["The column rules also write every value to a draft sheet. A line that only CMS data backs has no citation, so a volunteer can't check it."]],
    example: { highlight: [[0, 1, 2, 3], [0]], before: "ground $325, air 20%, abroad $325", after: "$325 or 20% | $325",
      paras: [["Every line here cites the EOC."]] } },
  { id: "stack-draft", record: "layers", from: "draft", to: "live", label: "Stack: draft",
    paras: [["The draft is the bottom ", ["layer", "layer"], ". A later layer that sets the same cell wins."]],
    example: { highlight: [[0], [0]], before: "draft $325 or 20% | $325", after: "bottom layer", paras: [] } },
  { id: "stack-presented", record: "layers", from: "presented", to: "live", label: "Stack: presented",
    paras: [["The presented ", ["layer", "layer"], " sits above the draft. Code drops any citation whose value differs from the cell's final value."]],
    example: { highlight: [[0, 1, 2], [0]], before: "presented $325 or 20% | $325, 4 quotes", after: "live value, cited",
      paras: [["Its value is the same here, so the cell keeps its value and gains four citations."]] } },
  { id: "publish", record: "layers", from: "live", to: "site", label: "Publish",
    paras: [["Merging to main builds the site. ", ["worker", "The pdxplans Worker"], " serves it at pdxplans.org, and the same build updates the volunteers' Google Sheet."]],
    example: { highlight: [[0], [1, 4, 5]], before: "live AB_ambulance", after: "cell + EOC page 46 highlight", paras: [] } },
];

// The steps that touched a cell, read from its trace. Without a trace, every step.
export function chain(trace) {
  if (!trace) return STEPS;
  const presented = (trace.layers?.applied ?? []).some((l) => l.layer === "generated/presented.csv" && l.rows.length);
  return STEPS.filter((s) => s.id !== "stack-presented" || presented);
}

// Edges with no step of their own.
export const LINKS = [["plans", "documents"], ["pbp", "draft"]];

export const NODE_W = 128;
export const NODE_H = 54;
const COL_STEP = 138;
const ROW_STEP = 80;
const MARGIN = 10;

export function nodeBox(id) {
  const n = NODES[id];
  return { x: MARGIN + n.col * COL_STEP, y: MARGIN + n.row * ROW_STEP, w: NODE_W, h: NODE_H };
}

export const MAP_W = MARGIN * 2 + Math.max(...Object.values(NODES).map((n) => n.col)) * COL_STEP + NODE_W;
export const MAP_H = MARGIN * 2 + Math.max(...Object.values(NODES).map((n) => n.row)) * ROW_STEP + NODE_H;

// A vertical cubic curve from the bottom middle of one node to the top middle of another.
export function edge(from, to) {
  const a = nodeBox(from), b = nodeBox(to);
  const x1 = a.x + a.w / 2, y1 = a.y + a.h, x2 = b.x + b.w / 2, y2 = b.y;
  const dy = Math.max(26, (y2 - y1) / 2);
  const c1 = [x1, y1 + dy], c2 = [x2, y2 - dy];
  const at = (t) => {
    const u = 1 - t;
    return [u ** 3 * x1 + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t ** 3 * x2,
      u ** 3 * y1 + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t ** 3 * y2];
  };
  return { d: `M${x1},${y1} C${c1} ${c2} ${x2},${y2}`, at };
}

export const PILL_W = 116;
export const PILL_H = 24;

// A step's label sits at the middle of its edge.
export function pillBox(step) {
  const [x, y] = edge(step.from, step.to).at(0.5);
  return { x: x - PILL_W / 2, y: y - PILL_H / 2, w: PILL_W, h: PILL_H };
}

export const stepById = (id) => STEPS.find((s) => s.id === id);
export const before = (step, steps = STEPS) => steps.filter((s) => s.to === step.from);
export const after = (step, steps = STEPS) => steps.filter((s) => s.from === step.to);

const shownValue = (v) => v === "" ? "blank" : v;
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const listed = (words) => words.length < 2 ? words.join("") : `${words.slice(0, -1).join(", ")} and ${words.at(-1)}`;
const kinds = (t) => listed(t.documents.documents.map((d) => d.kind));

// "3 quotes from EOC pages 46, 51", naming each document by its kind.
function quotes(rows, trace) {
  if (!rows.length) return "no quotes";
  const kind = Object.fromEntries(trace.documents.documents.map((d) => [d.url, d.kind]));
  const pages = Map.groupBy(rows, (r) => kind[r.url]);
  const where = [...pages].map(([k, rs]) => {
    const ps = [...new Set(rs.map((r) => r.pdf_page))].sort((x, y) => x - y);
    return `${k} ${ps.length === 1 ? "page" : "pages"} ${ps.join(", ")}`;
  });
  return `${plural(rows.length, "quote")} from ${where.join("; ")}`;
}

const layer = (trace, name) => trace.layers.applied.find((l) => l.layer === name);
const live = (t) => `live ${shownValue(t.layers.live.value)}`;

// What each step took in and gave out for a cell, read from its trace.
const STRIPS = {
  "list-plans": (t) => [`${t.plan.row.plan_id} in the Landscape file`, `plans.csv: ${t.plan.row.plan_name}`],
  "find-pdfs": (t) => [plural(new Set(t.documents.documents.map((d) => d.found_via)).size, "source"), `${kinds(t)} URLs`],
  "download": (t) => [plural(t.documents.documents.length, "URL"), t.documents.documents.map((d) =>
    `${d.kind}, ${plural(d.pages, "page")}${d.cover_problems ? ", cover problems" : ""}`).join("; ")],
  "extract-text": (t) => [plural(t.documents.documents.length, "PDF"),
    `text of ${plural(t.documents.documents.reduce((n, d) => n + d.pages, 0), "page")}`],
  "read-facts": (t) => [`${kinds(t)} page text`, `${plural(t.answers.rows.length, "saved answer")} from ${listed([...new Set(t.answers.rows.map((a) => a.model))])}`],
  "check-facts": (t) => {
    const kept = t.fact_checks.rows.filter((r) => r.kept).length;
    return [plural(t.fact_checks.rows.length, "fact"), `${kept} kept, ${t.fact_checks.rows.length - kept} rejected`];
  },
  "column-rules": (t) => [`${plural(t.rule.lines.reduce((n, l) => n + l.facts.length, 0), "fact")} used, ${t.rule.set_aside.length} set aside`,
    t.rule.held ? `held: ${t.rule.held}` : t.rule.lines.map((l) => `line ${l.line} ${shownValue(l.value)}`).join("; ")],
  "draft": (t) => ["the column rule", shownValue(t.draft.value)],
  "stack-draft": (t) => [`draft ${shownValue(t.layers.draft)}`,
    t.layers.live.value === t.layers.draft ? live(t) : `${live(t)}, set by ${t.layers.live.set_by}`],
  "stack-presented": (t) => {
    const presented = layer(t, "generated/presented.csv");
    return [`presented ${shownValue(presented.value)}, ${quotes(presented.rows, t)}`, live(t)];
  },
  "publish": (t) => [live(t), `site cell ${shownValue(t.layers.live.value)} with ${quotes(t.layers.live.citations, t)}`],
};

// [before, after] for a step, or null when the trace does not say.
export const strip = (step, trace) =>
  trace?.[step.record]?.status === "traced" && STRIPS[step.id] ? STRIPS[step.id](trace) : null;

// A prompt's task names its document by the first 16 hex digits of the PDF's hash.
function docKindOf(t, task) {
  const prefix = task.match(/^(?:v-)?([0-9a-f]{16})\./)?.[1];
  return prefix && t.documents.documents.find((d) => d.sha256.startsWith(prefix))?.kind;
}

const PROMPT_ROLES = {
  read: "reader prompt", reread: "second reader prompt",
  check: "verifier prompt", recheck: "second verifier prompt",
  review: "reviewer prompt", earlier: "earlier reviewer prompt",
};
const READING = ["read", "reread"];

function promptLinks(t, reading) {
  if (t.answers.status !== "traced") return [];
  return t.answers.rows.flatMap((answer) => answer.prompts.map((p) => ({ p, answer })))
    .filter(({ p }) => READING.includes(p.dir.split("/").at(-1)) === reading)
    .map(({ p, answer }) => {
      const role = PROMPT_ROLES[p.dir.split("/").at(-1)] ?? "prompt";
      const kind = docKindOf(t, p.task);
      const retry = p.task.includes(".retry.") ? ", retried" : "";
      return { text: `${kind ? `${kind} ` : ""}${role}${retry}, answered by ${answer.model}`, href: p.url };
    });
}

const factLabel = (kind, page, f) =>
  `${kind ?? "Unknown document"}${page ? ` page ${page}` : ""}, ${[f.benefit, f.amount].filter(Boolean).join(" ")}`;
const verdict = (who, check) => `${who} ${check.ok ? "agreed" : "disagreed"}: ${check.reason.replace(/\.$/, "")}`;

function factCheck(t, row) {
  const statedBy = row.stated_by[0];
  const stated = statedBy?.stated ?? {};
  // A fact that failed its quote check has no id, so its document comes from the prompt that stated it.
  const task = t.answers.rows?.flatMap((a) => a.prompts).find((p) => p.prompt === statedBy?.prompt)?.task;
  const parts = [row.fact ? factLabel(row.fact.source, row.fact.page, stated) : factLabel(task && docKindOf(t, task), stated.page, stated)];
  if (row.code_check && row.code_check !== "passed") parts.push(`Quote check failed: ${row.code_check}`);
  parts.push(...row.verifier.map((v) => verdict("Verifier", v)));
  if (row.reviewer.status === "traced") parts.push(verdict("Reviewer", row.reviewer));
  return { text: `${row.kept ? "Kept" : "Rejected"}: ${parts.join(". ")}.` };
}

// Lines that show a step's work for a cell, read from its trace.
const DETAILS = {
  "read-facts": (t) => promptLinks(t, true),
  "check-facts": (t) => [...t.fact_checks.rows.map((r) => factCheck(t, r)), ...promptLinks(t, false)],
  "column-rules": (t) => [
    ...(t.rule.held ? [{ text: `The rule leaves this cell as it was, because ${t.rule.held}` }] : []),
    ...t.rule.lines.flatMap((l) => l.facts.map((f) => ({ text: `Line ${l.line} (${shownValue(l.value)}) used ${factLabel(f.source, f.page, f)}` }))),
    ...t.rule.set_aside.map((f) => ({ text: `Set aside ${factLabel(f.source, f.page, f)}: ${f.reasons.join("; ")}` })),
  ],
};

export const details = (step, trace) =>
  trace?.[step.record]?.status === "traced" && DETAILS[step.id] ? DETAILS[step.id](trace) : [];
