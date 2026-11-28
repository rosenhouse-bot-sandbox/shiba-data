// The pipeline as a graph: tables are nodes and operations are edges.
// The rows are the example cell's, copied from main's 2027 data.
import { format } from "./permalink.js";

export const EXAMPLE = { sheet: "main", plan: "H1036-153-0", column: "ambulance" };

export const STORES = {
  git: { label: "In git", note: "committed" },
  r2: { label: "In R2", note: "stored files" },
  d1: { label: "In D1", note: "database, recent builds" },
  web: { label: "Website", note: "" },
};

const REPO = "https://github.com/rosenhouse-bot-sandbox/shiba-data";

// col and row place a node in the map's lanes. git is a path under data/<year>/, code a path in the repo, and cms names
// the CMS file that R2 copies. A byColumn table's link filters it to the cell's column too.
export const NODES = {
  landscape: { col: 2, row: 0, store: "r2", label: "CMS Landscape", cms: "Landscape",
    table: { name: "CY2027_Landscape_202610.csv", note: "one row per plan per county",
      cols: ["Contract Plan Segment ID", "Plan Name", "County Name", "Plan Type", "SNP Type", "Part C Premium", "In-Network MOOP"],
      rows: [["H1036_153_0", "Humana Total Complete (HMO)", "Multnomah", "HMO", "Not Applicable", "$0.00", "$5,150.00"],
        ["H1036_153_0", "Humana Total Complete (HMO)", "Clackamas", "HMO", "Not Applicable", "$0.00", "$5,150.00"]] } },
  links: { col: 1, row: 0, store: "git", label: "links", git: "links.csv",
    table: { name: "links", note: "copied from the volunteers' Links sheet", cols: ["plan_ids", "kind", "url"],
      rows: [["H1036-153-0", "SB", "https://assets.humana.com/is/content/humana/H1036153000SB27pdf"],
        ["H1036-153-0", "EOC", "https://assets.humana.com/is/content/humana/H1036153000EOC27pdf"]] } },
  found: { col: 0, row: 0, store: "git", label: "found", git: "found.csv",
    table: { name: "found", note: "Claude sessions found no URL for this plan", cols: ["plan_ids", "kind", "url", "found_via"], rows: [] } },
  pbp: { col: 3, row: 5, store: "r2", label: "CMS PBP tables", cms: "PBP",
    table: { name: "pbp_b4_emerg_urgent.txt", note: "the plan's emergency and urgent care copays abroad",
      cols: ["bid_id", "pbp_b4c_copay_amt_wec_min", "pbp_b4c_copay_amt_wec_max", "pbp_b4c_copay_amt_wuc_min", "pbp_b4c_copay_amt_wuc_max"],
      rows: [["H1036_153_0", "115.00", "115.00", "40.00", "40.00"]] } },
  plans: { col: 2, row: 1, store: "d1", label: "plans",
    table: { name: "plans", note: "39 rows", cols: ["plan_id", "plan_name", "plan_type", "organization", "premium", "moop_in_network"],
      rows: [["H1036-153-0", "Humana Total Complete (HMO)", "HMO", "Humana", "$0", "$5,150"]] } },
  documents: { col: 1, row: 2, store: "d1", label: "documents",
    table: { name: "documents", note: "one URL per plan and kind", cols: ["plan_ids", "kind", "url", "found_via"],
      rows: [["H1036-153-0", "SB", "…/H1036153000SB27pdf", "volunteers' Links sheet"],
        ["H1036-153-0", "EOC", "…/H1036153000EOC27pdf", "volunteers' Links sheet"]] } },
  checked: { col: 1, row: 3, store: "git", label: "documents_checked", git: "generated/documents_checked.csv",
    table: { name: "documents_checked", note: "selected columns", cols: ["plan_ids", "kind", "sha256", "pages", "cover_problems"],
      rows: [["H1036-153-0", "SB", "ce13e925c0384896d725da85a06c14df…", "24", ""],
        ["H1036-153-0", "EOC", "64e05773e847b56e0eeb5425979d5499…", "188", ""]] } },
  text: { col: 1, row: 4, store: "r2", label: "page text",
    text: { name: "6ebca98d895a45b3.txt", note: "SB page 9",
      href: "blobs/6ebca98d895a45b3d8c15ea4fd6a6052d6a31ade9374ff3cdfe194d957f8c1b7.txt",
      lines: ["=====PAGE 9=====", " SKILLED NURSING FACILITY (SNF)",
        " This plan covers up to 100 days in a SNF        $10 copay per day for days 1-20", " AMBULANCE",
        " Air                                             20% of the cost",
        " Ground                                          $325 copay per date of service",
        " TRANSPORTATION                                  Not Covered"] } },
  prompt: { col: 0, row: 4, store: "git", label: "fact_prompt", code: "pipeline/fact_prompt.md",
    text: { name: "pipeline/fact_prompt.md", note: "the reader prompt's template",
      lines: ["# Task", "", "You help Medicare counselors compare plans. Read the pages below from a plan's {KIND} for plan year {YEAR},",
        "and list every benefit fact they state about the benefits named below. A wrong fact is much worse than a missing one.",
        "", "The document covers these plans:", "{PLANS}", "…", "{VOCABULARY}"] } },
  sheet: { col: 1, row: 7, store: "d1", label: "main_chart",
    table: { name: "main_chart", note: "every rule's value, selected columns", cols: ["plan_id", "plan_name", "AB_ambulance"],
      rows: [["H1036-153-0", "Humana Total Complete (HMO)", "$325 or 20% | $325"]] } },
  answers: { col: 0, row: 5, store: "r2", label: "model answers",
    text: { name: "answers/e920fcee050a431f.json", note: "Claude Opus, high effort · 3,479 in / 954 out tokens",
      lines: [
        '[{"benefit": "ambulance.air", "setting": "any", "network": "in", "cost_kind": "coinsurance", "amount": "20%", "page": 9, "quotes": ["20% of the cost"]},',
        ' {"benefit": "ambulance.ground", "setting": "any", "network": "in", "cost_kind": "copay", "amount": "$325", "page": 9, "quotes": ["$325 copay per date of service"]},',
        ' {"benefit": "ambulance", "setting": "outside_us", "covered_by": "medicare", "amount": "$325", "page": 6, "quotes": ["Emergency ambulance: $325 copay per date of"]}]'] } },
  facts: { col: 1, row: 6, store: "d1", label: "document_facts",
    table: { name: "document_facts", note: "accepted facts, selected columns",
      cols: ["benefit", "setting", "network", "condition", "covered_by", "cost_kind", "amount", "source", "page"],
      rows: [["ambulance.ground", "any", "in", "Emergency Ambulance", "medicare", "copay", "$325", "EOC", "46"],
        ["ambulance.ground", "any", "in", "Non-Emergency Ambulance", "medicare", "copay", "$325", "EOC", "46"],
        ["ambulance.air", "any", "in", "Emergency Ambulance", "medicare", "coinsurance", "20%", "EOC", "46"],
        ["ambulance", "outside_us", "out", "Emergency Ambulance", "supplemental", "copay", "$325", "EOC", "46"],
        ["ambulance.ground", "any", "in", "", "medicare", "copay", "$325", "SB", "9"],
        ["ambulance.air", "any", "in", "", "medicare", "coinsurance", "20%", "SB", "9"]] } },
  rules: { col: 0, row: 6, store: "git", label: "rule code", code: "pipeline/present.py",
    text: { name: "pipeline/present.py", note: "the Ambulance column's entry in COLUMNS, and the rule it names",
      lines: ['COLUMNS = {..., "AB_ambulance": ambulance, ...}', "", "def ambulance(organization, found):",
        '    """Line 1 is trips within the U.S. and line 2 is emergency trips abroad, each as (value, cited facts).', "    …"] } },
  presented: { col: 0, row: 7, store: "d1", label: "presented", byColumn: true,
    table: { name: "presented", note: "one row per citation", cols: ["plan_id", "column", "line", "value", "pdf_page", "quote"],
      rows: [["H1036-153-0", "AB_ambulance", "1", "$325 or 20%", "46", "In-Network: Emergency Ambulance $325 copayment per date of service regardless of the number of trips – Ground Ambulance"],
        ["H1036-153-0", "AB_ambulance", "1", "$325 or 20%", "46", "… Ground Ambulance 20% coinsurance regardless of the number of trips – Air Ambulance"],
        ["H1036-153-0", "AB_ambulance", "2", "$325", "46", "Worldwide Coverage $325 copayment per date of service regardless of the number of trips – Emergency Ambulance"]] } },
  cmsFacts: { col: 2, row: 6, store: "d1", label: "pbp_facts",
    table: { name: "pbp_facts", note: "the facts the Ambulance rule considers, selected columns", cols: ["benefit", "setting", "condition", "amount", "source"],
      rows: [["emergency", "outside_us", "", "$115", "PBP"], ["emergency", "outside_us", "urgently needed services", "$40", "PBP"]] } },
  caveats: { col: 2, row: 7, store: "d1", label: "caveats",
    table: { name: "caveats", note: "the rule wrote no caveat", cols: ["sheet", "plan_id", "column", "kind", "comment"], rows: [] } },
  notes: { col: 2, row: 8, store: "git", label: "comments", git: "comments.csv",
    table: { name: "comments", note: "the cell has no note", cols: ["sheet", "plan_id", "column", "kind", "comment"], rows: [] } },
  site: { col: 1, row: 9, store: "web", label: "pdxplans.org",
    text: { name: "pdxplans.org", note: "after a volunteer clicks the cell",
      lines: ["Humana Total Complete (HMO) · Ambulance", "  $325 or 20% | $325", "", "EOC page 46, highlighted in the PDF beside the sheet:",
        '  "In-Network: Emergency Ambulance $325 copayment per date of service regardless of the number',
        '   of trips – Ground Ambulance 20% coinsurance regardless of the number of trips – Air Ambulance"'] } },
};

export const SHEET_TABLES = { main: "main_chart", dvha: "dvha" };
export const nodeName = (id, sheet) => id === "sheet" ? SHEET_TABLES[sheet] : NODES[id].label;

// The URL of a node's data, or null. at is { year, sheet, plan, column, sha, cell, cms }: column is the cell's column key,
// sha the build's commit, if known, cell the cell's link on the site, and cms the CMS download URLs by file.
export function nodeHref(id, { year, sheet, plan, column, sha, cell, cms }) {
  const n = NODES[id];
  if (n.git) return `${REPO}/blob/${sha ?? "main"}/data/${year}/${n.git}`;
  if (n.code) return `${REPO}/blob/${sha ?? "main"}/${n.code}`;
  if (n.store === "d1") return sha ? format({ year, view: "tables", build: sha, table: nodeName(id, sheet), plan, ...(n.byColumn ? { sheet, column } : {}) }) : null;
  if (n.store === "web") return cell;
  return n.cms ? cms[n.cms] : null;
}

// A paragraph is a list of segments: a string, or [term, text] for a term in web/terms.py.
// record names the key of the cell's trace (#181) that shows the step.
// paras hold for any cell. example holds only for the example cell: highlight lists, by node, the example rows
// that the cell uses.
export const STEPS = [
  { id: "list-plans", record: "plan", from: "landscape", to: "plans", label: "List the plans",
    paras: [["Code keeps ", ["bothCounties", "plans sold in both counties"], ". A plan's Landscape rows become one row of plans."]],
    example: { highlight: { landscape: [0, 1], plans: [0] }, before: "H1036_153_0 in Multnomah and Clackamas", after: "H1036-153-0, one row",
      paras: [["The plan has one Landscape row per county. 39 plans remain."]] } },
  { id: "find-pdfs", record: "documents", from: "plans", also: ["found", "links"], to: "documents", label: "Find PDFs",
    paras: [["plans lists the plans that need an SB and EOC. Three sources offer URLs: found holds what Claude sessions found on carrier sites, links copies the volunteers' Links sheet, and code fills URL templates for carriers whose URLs follow a pattern. ",
      ["firstUrl", "The first URL found wins"], "."]],
    example: { highlight: { plans: [0], links: [0, 1], documents: [0, 1] }, before: "links: …H1036153000EOC27pdf", after: "documents: EOC URL",
      paras: [] } },
  { id: "download", record: "documents", from: "documents", to: "checked", label: "Download PDFs",
    paras: [["The pipeline downloads each PDF, runs a ", ["cover", "cover check"], ", and records the PDF's SHA-256 hash."]],
    example: { highlight: { documents: [0], checked: [0] }, before: "…/H1036153000SB27pdf", after: "sha256 ce13e925…, 24 pages", paras: [] } },
  { id: "extract-text", record: "documents", from: "checked", to: "text", label: "Extract page text",
    paras: [["Code turns each page into ", ["layoutText", "text that keeps the page's columns"], ". The PDFs and texts are stored in R2, named by hash, so every later run reads the same bytes."]],
    example: { highlight: { checked: [0], text: [3, 4, 5] }, before: "PDF ce13e925…", after: "text of page 9", paras: [] } },
  { id: "cms-facts", record: "rule", from: "pbp", also: ["plans"], to: "cmsFacts", label: "Read CMS fields",
    paras: [["Code turns the plan's PBP fields into facts, and the premiums and drug deductible that plans copies from the Landscape file. They rank below every document, so a rule uses one only when no document gives the value. A value built from one has no citation."]],
    example: { highlight: { pbp: [0], plans: [0], cmsFacts: [0, 1] }, before: "pbp_b4c_copay_amt_wec_min = 115.00", after: "emergency abroad $115",
      paras: [["Line 2 of the Ambulance rule considers these facts, but sets them aside because the EOC prices ambulance trips abroad."]] } },
  { id: "read-facts", record: "answers", from: "text", also: ["prompt"], to: "answers", label: "Claude reads facts",
    paras: [["Code fills fact_prompt.md to make ", ["prompt", "one prompt"], " per document and benefit group. Claude Opus answers each with facts, each with its quotes and page."],
      ["The answer is ", ["hash", "saved under a hash of the model, effort and prompt"], ", so a rerun calls no model."]],
    example: { highlight: { text: [3, 4, 5], answers: [0, 1, 2] }, before: "Ground  $325 copay per date of service", after: "{benefit: ambulance.ground, amount: $325, page: 9}",
      paras: [["The Ambulance column uses the ambulance and emergency groups, so Claude gets four prompts, one per group and document. For the SB and the ambulance group, Claude answers with three facts."]] } },
  { id: "check-facts", record: "fact_checks", from: "answers", also: ["text"], to: "facts", label: "Check facts",
    paras: [["Code runs a ", ["quoteCheck", "quote check"], " of every fact against its page's text. A verifier, Claude Opus, then reads the page and judges each fact mixed with ", ["decoy", "decoys"], ". Last, a ", ["reviewer", "reviewer"], " checks each fact a value would cite. The verifier's and reviewer's answers are saved with the reader's."]],
    example: { highlight: { answers: [2], facts: [3, 4, 5] }, before: "SB: abroad, covered_by medicare", after: "rejected; the EOC's supplemental fact stands",
      paras: [["The verifier rejected the SB's worldwide fact: Medicare doesn't cover care abroad, so it is supplemental. The EOC's fact, already marked supplemental, passed."]] } },
  { id: "column-rules", record: "rule", from: "facts", also: ["rules", "cmsFacts"], to: "presented", alsoTo: ["sheet", "caveats"], label: "Apply column rules",
    paras: [["Each column has a rule, written in code from the domain expert's instructions. It takes facts from the ", ["bestSource", "best source"], " and cites their quotes. It writes each value to the sheet and each citation to presented. A line that only CMS data backs has no citation, so a volunteer can't check it."],
      ["Some rules also write a caveat from the facts a cell cites, such as \"In the labs range, the 20% is for genetic testing.\""]],
    example: { highlight: { facts: [0, 1, 2, 3], rules: [0, 2], presented: [0, 1, 2], sheet: [0] }, before: "ground $325, air 20%, abroad $325", after: "$325 or 20% | $325",
      paras: [["In the ", ["rule", "Ambulance rule"], ", line 1 takes in-network, Medicare-covered ground and air trips from the EOC. Line 2 takes trips abroad. Each line cites the quotes of the facts it used, so line 1 gets four citations and line 2 one, all from EOC page 46."]] } },
  { id: "write-notes", record: "notes", from: "sheet", also: ["presented"], to: "notes", label: "Write notes",
    paras: [["Claude sessions write a note in a pull request where a value needs explaining that no rule gives, such as something the documents leave unclear. No workflow runs this step. Each note cites a page and quote."]],
    example: { highlight: { sheet: [0], presented: [0, 1, 2] }, before: "$325 or 20% | $325", after: "no note",
      paras: [["The Ambulance cell has no note."]] } },
  { id: "publish", record: "citations", from: "sheet", also: ["presented", "notes", "caveats"], to: "site", label: "Publish",
    paras: [["Merging to main builds the site from the sheet, its citations, the notes that Claude sessions write and the rules' caveats. A cell with both shows both. ", ["worker", "The pdxplans Worker"], " serves it at pdxplans.org, and the same build updates the volunteers' Google Sheet."]],
    example: { highlight: { sheet: [0], presented: [0, 1, 2], site: [1, 4, 5] }, before: "$325 or 20% | $325, 5 quotes", after: "cell + EOC page 46 highlight", paras: [] } },
];

// A step reads from first, then each node in also.
export const inputs = (step) => [step.from, ...(step.also ?? [])];
// A step writes to its to node first, then each node in alsoTo.
export const outputs = (step) => [step.to, ...(step.alsoTo ?? [])];
// A step with several inputs or outputs joins and splits its edges at its label.
const branches = (step) => inputs(step).length > 1 || outputs(step).length > 1;

export const NODE_W = 128;
export const NODE_H = 54;
export const PILL_W = 116;
export const PILL_H = 24;
// A selected node's ring, drawn outside its box.
export const RING = 4;
// The space above and below every label, outside any ring.
export const MIN_GAP = 18;
// The space edges get above a label where they merge, so they curve gently.
export const MERGE_ROOM = 48;
const COL_STEP = 138;
const ROW_STEP = NODE_H + 2 * (RING + MIN_GAP) + PILL_H;
const MARGIN = 10;

// Rows that a merging step writes to are taller by the extra room its edges need.
const mergeRows = new Set(STEPS.filter(branches).map((s) => NODES[s.to].row));
const rowY = (row) => MARGIN + row * ROW_STEP + [...mergeRows].filter((r) => r <= row).length * (MERGE_ROOM - MIN_GAP);

export function nodeBox(id) {
  const n = NODES[id];
  return { x: MARGIN + n.col * COL_STEP, y: rowY(n.row), w: NODE_W, h: NODE_H };
}

export const MAP_W = MARGIN * 2 + Math.max(...Object.values(NODES).map((n) => n.col)) * COL_STEP + NODE_W;
export const MAP_H = MARGIN + rowY(Math.max(...Object.values(NODES).map((n) => n.row))) + NODE_H;

// A vertical cubic curve between two points.
function curve([x1, y1], [x2, y2]) {
  const dy = Math.max(26, (y2 - y1) / 2);
  const c1 = [x1, y1 + dy], c2 = [x2, y2 - dy];
  const at = (t) => {
    const u = 1 - t;
    return [u ** 3 * x1 + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t ** 3 * x2,
      u ** 3 * y1 + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t ** 3 * y2];
  };
  return { d: `M${x1},${y1} C${c1} ${c2} ${x2},${y2}`, at };
}

const bottom = (b) => [b.x + b.w / 2, b.y + b.h];
const top = (b) => [b.x + b.w / 2, b.y];

const center = (boxes) => boxes.reduce((x, b) => x + b.x + b.w / 2, 0) / boxes.length;

// Every label sits MIN_GAP above its outputs, which share a row. A step with one input and one output has its label on
// its edge; otherwise the inputs join above the outputs' center, and the edges split there.
export function pillBox(step) {
  const to = nodeBox(step.to);
  const x = branches(step) ? center(outputs(step).map(nodeBox)) : curve(bottom(nodeBox(step.from)), top(to)).at(0.5)[0];
  return { x: x - PILL_W / 2, y: to.y - RING - MIN_GAP - PILL_H, w: PILL_W, h: PILL_H };
}

// The lines a step draws. Only those into an output get an arrow.
export function paths(step) {
  if (!branches(step)) return [{ ...curve(bottom(nodeBox(step.from)), top(nodeBox(step.to))), arrow: true }];
  const pill = pillBox(step);
  return [...inputs(step).map((id) => ({ ...curve(bottom(nodeBox(id)), top(pill)), arrow: false })),
    ...outputs(step).map((id) => ({ ...curve(bottom(pill), top(nodeBox(id))), arrow: true }))];
}

export const stepById = (id) => STEPS.find((s) => s.id === id);
export const before = (step) => STEPS.filter((s) => outputs(s).some((id) => inputs(step).includes(id)));
export const after = (step) => STEPS.filter((s) => outputs(step).some((id) => inputs(s).includes(id)));

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

function readerAnswers(t) {
  const answers = uniquePrompts(t, true).map(({ answer }) => answer);
  return answers.length ? `${plural(answers.length, "saved answer")} from ${listed([...new Set(answers.map((a) => a.model))])}` : "no saved answers";
}

// What each step took in and gave out for a cell, read from its trace.
const STRIPS = {
  "list-plans": (t) => [`${t.plan.row.plan_id} in the Landscape file`, `plans: ${t.plan.row.plan_name}`],
  "find-pdfs": (t) => [`${plural(t.documents.candidates.length, "URL")} from ${plural(new Set(t.documents.candidates.map((c) => c.source)).size, "source")}`,
    `${kinds(t)} URLs`],
  "download": (t) => [plural(t.documents.documents.length, "URL"), t.documents.documents.map((d) =>
    `${d.kind}, ${plural(d.pages, "page")}${d.cover_problems ? ", cover problems" : ""}`).join("; ")],
  "extract-text": (t) => [plural(t.documents.documents.length, "PDF"),
    `text of ${plural(t.documents.documents.reduce((n, d) => n + d.pages, 0), "page")}`],
  "cms-facts": (t) => ["the plan's PBP and Landscape fields",
    cmsFacts(t).length ? `${plural(cmsFacts(t).length, "CMS fact")} for this column` : "no CMS facts for this column"],
  "read-facts": (t) => [`${kinds(t)} page text`, readerAnswers(t)],
  "check-facts": (t) => {
    const kept = t.fact_checks.rows.filter((r) => r.kept).length;
    return [plural(t.fact_checks.rows.length, "fact"), `${kept} kept, ${t.fact_checks.rows.length - kept} rejected`];
  },
  "column-rules": (t) => [`${plural(t.rule.lines.reduce((n, l) => n + l.facts.length, 0), "fact")} used, ${t.rule.set_aside.length} set aside`,
    t.rule.held ? `held: ${t.rule.held}` : t.rule.lines.map((l) => `line ${l.line} ${shownValue(l.value)}`).join("; ")],
  "write-notes": (t) => [`sheet ${shownValue(t.sheet.value)}`, t.notes.rows.length ? `${t.notes.rows[0].kind} note` : "no note"],
  "publish": (t) => [`sheet ${shownValue(t.sheet.value)}`, `site cell ${shownValue(t.sheet.value)} with ${quotes(t.citations.shown, t)}`],
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
  review: "reviewer prompt",
};
const READING = ["read", "reread"];
// A prompt's dir is facts/[inherited/]<group>/<role>, or facts/review.
const roleOf = (p) => p.dir.split("/").at(-1);
const groupOf = (p) => p.dir.split("/").length > 2 ? p.dir.split("/").at(-2) : null;
const isReading = (p) => READING.includes(roleOf(p));

const isInherited = (p) => p.dir.includes("/inherited/");

// An inherited task can repeat its version's own prompt in the same answer, so each answer lists each prompt once.
function uniquePrompts(t, reading) {
  return t.answers.rows.flatMap((answer) => {
    const own = new Map();
    for (const p of answer.prompts.filter((p) => isReading(p) === reading)) {
      if (!own.has(p.prompt) || !isInherited(p)) own.set(p.prompt, p);
    }
    return [...own.values()].map((p) => ({ p, answer }));
  });
}

// What a prompt is, then the flags that follow it.
function promptLabel(t, p) {
  const kind = docKindOf(t, p.task);
  const group = groupOf(p);
  const reviewed = roleOf(p) === "review" && t.fact_checks.rows.find((r) => r.reviewer.prompt === p.prompt);
  const what = `${kind ? `${kind} ` : ""}${PROMPT_ROLES[roleOf(p)] ?? "prompt"}${group ? ` for the ${group} group` : ""}`
    + (reviewed ? ` for ${checkedFactLabel(t, reviewed)}` : "");
  return [what, (p.task.includes(".retry.") ? ", retried" : "") + (isInherited(p) ? ", inherited" : "")];
}

function promptLinks(t, reading) {
  if (t.answers.status !== "traced") return [];
  const links = uniquePrompts(t, reading).map(({ p, answer }) => ({ p, answer, label: promptLabel(t, p) }));
  const shared = ([what, flags]) => links.filter(({ label }) => label[0] === what && label[1] === flags).length > 1;
  return links.map(({ p, answer, label: [what, flags] }) => ({
    text: `${what}${shared([what, flags]) ? ` ${p.prompt.slice(0, 8)}` : ""}${flags}, answered by ${answer.model}`, href: p.url,
  }));
}

const factLabel = (kind, page, f) =>
  `${kind ?? "Unknown document"}${page ? ` page ${page}` : ""}, ${[f.benefit, f.amount].filter(Boolean).join(" ")}${f.condition ? ` (${f.condition})` : ""}`;
const verdict = (who, check) => `${who} ${check.ok ? "agreed" : "disagreed"}: ${check.reason.replace(/\.$/, "")}`;

const taskOf = (t, prompt) => t.answers.rows?.flatMap((a) => a.prompts).find((p) => p.prompt === prompt)?.task;

// A fact that failed its quote check has no id, so its document comes from the prompt that stated it.
function checkedFactLabel(t, row) {
  const statedBy = row.stated_by[0];
  const stated = statedBy?.stated ?? {};
  const task = taskOf(t, statedBy?.prompt);
  return row.fact ? factLabel(row.fact.source, row.fact.page, stated) : factLabel(task && docKindOf(t, task), stated.page, stated);
}

function factCheck(t, row) {
  const parts = [checkedFactLabel(t, row)];
  if (row.code_check && row.code_check !== "passed") parts.push(`Quote check failed: ${row.code_check}`);
  parts.push(...row.verifier.map((v) => verdict("Verifier", v)));
  if (row.reviewer.status === "traced") parts.push(verdict("Reviewer", row.reviewer));
  return { text: `${row.kept ? "Kept" : "Rejected"}: ${parts.join(". ")}.` };
}

// Lines that show a step's work for a cell, read from its trace.
const DETAILS = {
  "find-pdfs": (t) => t.documents.candidates.filter((c) => c.source === "URL template").map((c) =>
    ({ text: `A URL template in code offered the ${c.kind}${c.used ? ", and it won" : ""}`, href: c.url })),
  "read-facts": (t) => promptLinks(t, true),
  "check-facts": (t) => [...t.fact_checks.rows.map((r) => factCheck(t, r)), ...promptLinks(t, false)],
  "column-rules": (t) => t.rule.held ? [{ text: `The rule leaves this cell blank, because ${t.rule.held}` }] : [],
};

// RECORDS[step][node] reads the cell's rows in that node's table from the trace. Each table names the records it needs,
// and hi lists the rows the step kept or used.
const traced = (r) => r?.status === "traced";
const table = (needs, note, cols, rows, hi = () => []) => ({ needs, note, cols, rows, hi });
const short = (sha) => sha ? `${sha.slice(0, 16)}…` : "";
const blob = (sha, href) => sha ? { text: short(sha), href: href(sha) } : "";
const FACT_COLS = ["source", "page", "benefit", "setting", "network", "condition", "amount"];
const factRow = (kind, page, f) => [kind ?? "", String(page ?? ""), f.benefit, f.setting, f.network, f.condition ?? "", f.amount];
const CMS_PLAN_COLS = ["plan_id", "premium", "premium_full_extra_help", "part_d_deductible"];
const PLAN_COLS = ["plan_id", "plan_name", "plan_type", "organization", "premium", "moop_in_network"];
const documentsCsv = table(["documents"], "the plan's rows", ["kind", "url", "found_via"],
  (t) => t.documents.documents.map((d) => [d.kind, d.url, d.found_via]));
const checkedCsv = table(["documents"], "the plan's rows, selected columns", ["kind", "sha256", "pages", "cover_problems"],
  (t) => t.documents.documents.map((d) => [d.kind, blob(d.sha256, (s) => `docs/${s}.pdf`), String(d.pages ?? ""), d.cover_problems]));
const pageText = table(["documents"], "one file per PDF, named by the text's hash", ["kind", "pages", "text file"],
  (t) => t.documents.documents.map((d) => [d.kind, String(d.pages ?? ""), blob(d.text?.layout, (s) => `blobs/${s}.txt`)]));
// A source's table lists the URLs it offered the plan, in the order tried.
const offered = (source, note) => {
  const mine = (t) => t.documents.candidates.filter((c) => c.source === source);
  return table(["documents"], `${note}; highlighted rows won`, ["kind", "url", "found_via"],
    (t) => mine(t).map((c) => [c.kind, c.url, c.found_via]), (t) => mine(t).flatMap((c, i) => c.used ? [i] : []));
};
const statedKind = (t, row) => {
  const task = taskOf(t, row.stated_by[0]?.prompt);
  return row.fact?.source ?? (task && docKindOf(t, task));
};
const stated = (row) => row.stated_by[0]?.stated ?? {};
const used = (t) => t.rule.lines.flatMap((l) => l.facts);
const considered = (t) => [...used(t), ...t.rule.set_aside];
const cmsFacts = (t) => considered(t).filter((f) => f.origin === "pbp");
// An origin's table lists the facts of that origin that the rule considered: each line's facts, highlighted, then
// the facts it set aside and why.
const RULE_FACT_COLS = ["line", "source", "page", "benefit", "amount", "set aside because", "setting", "network", "condition"];
const ruleFactRow = (line, f, why) => [line, f.source, String(f.page ?? ""), f.benefit, f.amount, why, f.setting, f.network, f.condition ?? ""];
const ruleFacts = (origin, note) => {
  const usedBy = (t) => t.rule.lines.flatMap((l) => l.facts.filter((f) => f.origin === origin).map((f) => ruleFactRow(String(l.line), f, "")));
  return table(["rule"], `${note}; highlighted facts were used`, RULE_FACT_COLS,
    (t) => [...usedBy(t), ...t.rule.set_aside.filter((f) => f.origin === origin).map((f) => ruleFactRow("", f, f.reasons.join("; ")))],
    (t) => usedBy(t).map((_, i) => i));
};
// Names the lines that a link to code points to, such as "present.py lines 323–332".
const codeLines = (url) => {
  const [start, end] = url.split("#L")[1].split("-L");
  return `${url.split("/").at(-1).split("#")[0]} ${start === end ? `line ${start}` : `lines ${start}–${end}`}`;
};
const sheetRow = table(["sheet"], "the cell", ["plan_id", "column", "value"], (t) => [[t.cell.plan_id, t.cell.col, shownValue(t.sheet.value)]]);
const cellNote = table(["notes"], "the cell's note", ["kind", "comment"], (t) => t.notes.rows.map((r) => [r.kind, r.comment]));
const cellCaveat = table(["caveats"], "the cell's caveat", ["kind", "comment"], (t) => t.caveats.rows.map((r) => [r.kind, r.comment]));
const kindOf = (t, url) => t.documents.documents.find((d) => d.url === url)?.kind ?? "";
const CITE_COLS = ["line", "value", "document", "pdf_page", "quote"];
const citationRows = (t, rows) => rows.map((c) => [String(c.line ?? ""), shownValue(c.value ?? ""), kindOf(t, c.url), String(c.pdf_page), c.quote]);
const allCitations = (t) => [...t.citations.shown, ...t.citations.hidden];
const cellCitations = table(["citations", "documents"], "the cell's citations", CITE_COLS, (t) => citationRows(t, allCitations(t)));

export const RECORDS = {
  "list-plans": {
    landscape: table(["plan"], "the fields plans reads", ["field", "value"],
      (t) => traced(t.plan.landscape_row) ? t.plan.landscape_row.fields.map((f) => [f.field, f.value]) : []),
    plans: table(["plan"], "the plan's row, selected columns", PLAN_COLS, (t) => [PLAN_COLS.map((k) => t.plan.row[k])]),
  },
  "find-pdfs": {
    plans: table(["plan"], "the plan's row, selected columns", ["plan_id", "plan_name", "organization"],
      (t) => [[t.plan.row.plan_id, t.plan.row.plan_name, t.plan.row.organization]]),
    found: offered("found.csv", "tried first"),
    links: offered("links.csv", "tried next"),
    documents: documentsCsv,
  },
  "download": { documents: documentsCsv, checked: checkedCsv },
  "extract-text": { checked: checkedCsv, text: pageText },
  "cms-facts": {
    pbp: table(["rule"], "the fields behind the column's CMS facts", ["benefit", "fields"],
      (t) => cmsFacts(t).map((f) => [f.benefit, JSON.parse(f.quotes || "[]").join(", ")])),
    plans: table(["plan"], "the plan's Landscape fact columns", CMS_PLAN_COLS, (t) => [CMS_PLAN_COLS.map((k) => t.plan.row[k])]),
    cmsFacts: table(["rule"], "the column's CMS facts", ["benefit", "setting", "condition", "amount", "source"],
      (t) => cmsFacts(t).map((f) => [f.benefit, f.setting, f.condition ?? "", f.amount, f.source])),
  },
  "read-facts": {
    text: pageText,
    prompt: table(["answers", "documents"], "filled for each document and benefit group", ["document", "group", "prompt"],
      (t) => uniquePrompts(t, true).map(({ p }) => [docKindOf(t, p.task) ?? "", groupOf(p), short(p.prompt)])),
    answers: table(["answers", "documents"], "one saved answer per reader prompt", ["answer", "model", "document", "group"],
      (t) => uniquePrompts(t, true).map(({ p, answer: a }) => [a.key, a.model, docKindOf(t, p.task) ?? "", groupOf(p)])),
  },
  "check-facts": {
    answers: table(["fact_checks", "documents"], "the facts they state; highlighted facts were kept", FACT_COLS,
      (t) => t.fact_checks.rows.map((r) => factRow(statedKind(t, r), stated(r).page, stated(r))),
      (t) => t.fact_checks.rows.flatMap((r, i) => r.kept ? [i] : [])),
    text: pageText,
    facts: table(["fact_checks"], "the kept facts", FACT_COLS,
      (t) => t.fact_checks.rows.filter((r) => r.kept).map((r) => factRow(r.fact?.source, r.fact?.page, stated(r)))),
  },
  "column-rules": {
    facts: ruleFacts("document", "the document facts the rule considered"),
    rules: table([], "where the column gets its rule, then each function and name the rule uses", ["code", "lines"],
      (t, code) => code.length ? code.map((c) => [c.name, { text: codeLines(c.url), href: c.url }]) : null),
    cmsFacts: ruleFacts("pbp", "the CMS facts the rule considered"),
    presented: cellCitations,
    sheet: sheetRow,
    caveats: cellCaveat,
  },
  "write-notes": {
    sheet: sheetRow,
    presented: cellCitations,
    notes: cellNote,
  },
  "publish": {
    sheet: sheetRow,
    presented: table(["citations", "documents"], "the cell's citations; highlighted ones are shown", CITE_COLS,
      (t) => citationRows(t, allCitations(t)), (t) => t.citations.shown.map((_, i) => i)),
    notes: cellNote,
    caveats: cellCaveat,
    site: table(["citations", "documents"], "the quotes the cell shows", CITE_COLS, (t) => citationRows(t, t.citations.shown)),
  },
};

// A step shows one table per input, in the map's order, then its outputs. rows is null when the trace lacks a record
// the table needs, and empty when a record says no step touched the cell. code is the column's rule code links, from
// the site's data.
export const records = (step, trace, sheet = trace?.cell?.sheet, code = []) => [...inputs(step), ...outputs(step)].map((id, i) => {
  const r = RECORDS[step.id][id];
  const status = r.needs.map((k) => trace?.[k]?.status);
  const rows = status.every((s) => s === "traced") ? r.rows(trace, code) : status.every((s) => s === "traced" || s === "none") ? [] : null;
  return { role: i < inputs(step).length ? "Input" : "Output", node: id, name: nodeName(id, sheet),
    note: r.note, cols: r.cols, rows, hi: rows?.length ? r.hi(trace) : [] };
});

export const details = (step, trace) =>
  trace?.[step.record]?.status === "traced" && DETAILS[step.id] ? DETAILS[step.id](trace) : [];
