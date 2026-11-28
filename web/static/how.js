// The pipeline view: a map of tables and steps, and a lens on one step.
import { el, svg } from "./dom.js";
import { hint } from "./hint.js";
import { format } from "./permalink.js";
import {
  EXAMPLE, NODES, STEPS, STORES, inputs, outputs, nodeName, NODE_W, NODE_H, RING, MAP_W, MAP_H,
  nodeBox, pillBox, paths, before, after, strip, details, records, nodeHref,
} from "./pipeline.js";
import { shown, pageOf, pager, bodyRow, rowCount } from "./tables.js";

export const howLink = (year, cell, step) => format({ year, view: "how", sheet: cell.sheet, plan: cell.plan, column: cell.column, step: step.id });
export const traceUrl = (year, sheet, plan, columnKey) => `trace/${year}/${sheet}/${plan}/${columnKey}`;
const exampleOf = (id) => NODES[id].table ?? NODES[id].text;
const store = (id) => STORES[NODES[id].store];
const isExample = (cell) => cell.sheet === EXAMPLE.sheet && cell.plan === EXAMPLE.plan && cell.column === EXAMPLE.column;

// cell is { sheet, plan, column, key, label, value }, where column is the column's id and key its key.
// load(table) gets a D1 table of the trace's build, and pageHref(row, page) links to a page that a row names.
export function howView({ year, cell, step, terms, trace, cms, code, load, pageHref }) {
  const at = STEPS.indexOf(step);
  const link = (s) => howLink(year, cell, s);
  const prev = STEPS[at - 1], next = STEPS[at + 1];
  return el("div", { class: "how" },
    el("div", { class: "how-head" },
      el("span", {}, "Following one cell:"),
      el("span", { class: "how-cell" }, cell.label),
      el("code", { class: "how-value" }, cell.value || "blank"),
      el("span", { class: "how-spacer" }),
      prev ? el("a", { class: "how-nav", href: link(prev), rel: "prev" }, "← Prev") : el("span", { class: "how-nav off" }, "← Prev"),
      el("span", { class: "how-count" }, `${at + 1} of ${STEPS.length}`),
      next ? el("a", { class: "how-nav primary", href: link(next), rel: "next" }, "Next →") : el("span", { class: "how-nav primary off" }, "Next →")),
    el("div", { class: "how-body" }, map(step, link, cell.sheet),
      lens(step, link, terms, isExample(cell) ? step.example : null, trace, code, { year, sheet: cell.sheet, plan: cell.plan, column: cell.key,
        sha: trace?.build?.sha ?? null,
        cell: format({ year, view: cell.sheet, plan: cell.plan, column: cell.column }), cms, load, pageHref })));
}

function map(step, link, sheet) {
  const on = new Set([...inputs(step), ...outputs(step)]);
  const lines = svg("svg", { width: MAP_W, height: MAP_H, "aria-hidden": "true" },
    svg("defs", {}, ...["off", "on"].map((k) => svg("marker", {
      id: `how-arrow-${k}`, viewBox: "0 0 10 10", refX: "9", refY: "5", markerWidth: "10", markerHeight: "10", markerUnits: "userSpaceOnUse", orient: "auto",
    }, svg("path", { d: "M0,0 L10,5 L0,10 z", class: `how-arrow ${k}` })))),
    ...STEPS.flatMap((s) => paths(s).map((p) => svg("path", {
      d: p.d, class: `how-edge${s === step ? " on" : ""}`,
      ...(p.arrow ? { "marker-end": `url(#how-arrow-${s === step ? "on" : "off"})` } : {}),
    }))));
  const nodes = Object.entries(NODES).map(([id, n]) => {
    const b = nodeBox(id), name = nodeName(id, sheet);
    return el("div", { class: `how-node store-${n.store}${on.has(id) ? " on" : ""}`,
      style: `left:${b.x}px;top:${b.y}px;width:${NODE_W}px;height:${NODE_H}px`, title: `${store(id).label}: ${name}` },
    el("small", {}, store(id).label), " ", el("code", {}, name));
  });
  const pills = STEPS.map((s) => {
    const b = pillBox(s);
    const style = `left:${b.x}px;top:${b.y}px;width:${b.w}px;height:${b.h}px`;
    return el("a", { class: `how-pill${s === step ? " on" : ""}`, href: link(s), title: s.label, style,
      ...(s === step ? { "aria-current": "step" } : {}) }, s.label);
  });
  return el("section", { class: "how-map", style: `--map-w:${MAP_W}px`, "aria-label": "Tables and steps" },
    el("h2", {}, "Tables and steps"),
    el("div", { class: "how-frame", style: `width:${MAP_W}px;height:${MAP_H}px` },
      el("div", { class: "how-world", style: `width:${MAP_W}px;height:${MAP_H}px;--ring:${RING}px` }, lines, ...nodes, ...pills)),
    el("p", { class: "how-legend" }, ...Object.entries(STORES).map(([key, s]) =>
      el("span", {}, el("b", { class: `store-${key}` }, s.label), s.note ? ` ${s.note}` : ""))));
}

// A CMS file is a large zip, so its heading asks before it downloads. The pop-over closes when the page scrolls.
function download(id, file, href) {
  const pop = el("div", { id, class: "how-download", popover: "" },
    el("p", {}, `This downloads the CMS ${file} file from cms.gov. It is a zip file of tens of megabytes.`),
    el("p", {}, el("a", { href }, "Download the zip file"), " ", el("button", { type: "button", popovertarget: id, popovertargetaction: "hide" }, "Cancel")));
  pop.addEventListener("beforetoggle", (e) => {
    if (e.newState !== "open") return;
    const r = document.querySelector(`[popovertarget="${id}"]`).getBoundingClientRect();
    pop.style.top = `${r.bottom + 4}px`;
    pop.style.left = `${Math.max(8, Math.min(r.left, innerWidth - 328))}px`;
  });
  document.addEventListener("scroll", () => pop.matches(":popover-open") && pop.hidePopover(), true);
  return pop;
}

// at says where each table's data is, as nodeHref takes it.
function lens(step, link, terms, example, trace, code, at) {
  const { sheet } = at;
  const chips = (near, cls, text) => near.length ? el("div", { class: `how-chips ${cls}` },
    ...near.map((s) => el("a", { href: link(s) }, text(s.label)))) : null;
  const downloads = [];
  // A table's heading says where its data lives, and opens the data when it has a URL.
  const heading = (id) => {
    const n = NODES[id], name = nodeName(id, sheet), href = nodeHref(id, at) ?? (example ? exampleOf(id).href : null);
    const where = el("small", { class: `how-store store-${n.store}` }, store(id).label);
    if (href && n.cms) {
      const warning = download(`how-download-${id}`, n.cms, href);
      downloads.push(warning);
      return [where, el("button", { type: "button", class: "how-source", popovertarget: warning.id, "aria-label": `${name}, download from cms.gov` },
        el("code", {}, name), " ↓")];
    }
    if (href && n.store === "d1") return [where, el("a", { class: "how-source", href, "aria-label": `${name}, opens in Tables` }, el("code", {}, name), " →")];
    if (href) return [where, el("a", { class: "how-source", href, target: "_blank", rel: "noopener",
      "aria-label": `${name}, opens in a new tab` }, el("code", {}, name), " ↗")];
    return [where, el("code", {}, name)];
  };
  const fromTo = example ? [example.before, example.after] : strip(step, trace);
  const para = (p) => el("p", {}, ...p.map((s) => typeof s === "string" ? s : term(terms[s[0]], s[1])));
  const tables = records(step, trace, sheet, code).map((r) => {
    const head = heading(r.node);
    const box = r.rows ? table(r.role, head, r.note, r.cols, r.rows, r.hi)
      : example ? rows(r.role, head, r.node, sheet, example.highlight[r.node] ?? [])
        : frame(r.role, head, r.note, trace ? el("p", { class: "how-none" }, "Not recorded in this build.") : null);
    return NODES[r.node].store === "d1" && at.sha ? scoped(box, r.node, at) : box;
  });
  return el("section", { class: "how-lens" },
    chips(before(step), "before", (l) => `↖ after: ${l}`),
    el("div", { class: "how-card" },
      el("h2", { class: "how-step", tabindex: "-1" }, step.label),
      fromTo ? el("p", { class: "how-strip" }, el("code", { class: "from" }, fromTo[0]), " becomes ", el("code", { class: "to" }, fromTo[1])) : null,
      ...step.paras.map(para), ...(example?.paras ?? []).map(para), workList(details(step, trace))),
    ...tables,
    ...downloads,
    traceRecord(step, trace),
    chips(after(step), "after", (l) => `next: ${l} ↘`));
}

const SCOPES = [["cell", "This cell"], ["plan", "This plan"], ["all", "All plans"]];

// A D1 table also shows the build's rows for the cell's plan or for every plan, loaded when asked.
function scoped(box, id, at) {
  const { year, sha, plan, load, pageHref } = at, name = nodeName(id, at.sheet);
  const [head, ...cellRows] = box.children;
  const status = el("p", { class: "how-none", role: "status" });
  const area = el("div", {}, ...cellRows);
  const pick = el("fieldset", { class: "how-scopes", "aria-label": `${name} rows` }, el("legend", {}, "Rows"), ...SCOPES.map(([value, label]) =>
    el("label", {}, el("input", { type: "radio", name: `how-scope-${id}`, value, ...(value === "cell" ? { checked: "" } : {}) }), ` ${label}`)));
  const chosen = () => pick.querySelector("input:checked").value;
  pick.addEventListener("change", async () => {
    const scope = chosen();
    status.textContent = "";
    if (scope === "cell") return area.replaceChildren(...cellRows);
    status.textContent = "Loading the table…";
    area.replaceChildren();
    const rows = await load(name);
    if (chosen() !== scope) return;
    const open = el("a", { href: format({ year, view: "tables", build: sha, table: name, plan: scope === "plan" ? plan : undefined }) }, "Open in Tables →");
    if (!rows) {
      status.textContent = `The ${name} table did not load.`;
      return area.replaceChildren(el("p", { class: "how-peek-pager" }, open));
    }
    const some = scope === "plan" ? shown(rows, { plan }) : rows;
    status.textContent = rowCount(some.length);
    peek(area, some, Object.keys(rows[0] ?? {}), pageHref, open);
  });
  box.replaceChildren(head, pick, status, area);
  return box;
}

// Shows rows a page at a time, with the pager above them so the keyboard reaches it first.
function peek(area, rows, cols, pageHref, open) {
  if (!rows.length) return area.replaceChildren(el("p", { class: "how-peek-pager" }, open));
  let page = 1;
  const tbody = el("tbody");
  const draw = () => {
    const p = pageOf(rows, page);
    tbody.replaceChildren(...p.rows.map((r) => bodyRow(r, cols, pageHref)));
    pages.show(p, rows.length);
  };
  const pages = pager("how-peek-pager", (by) => {
    page += by;
    draw();
  });
  pages.box.append(open);
  draw();
  area.replaceChildren(pages.box, el("div", { class: "how-scroll how-peek" },
    el("table", {}, el("thead", {}, el("tr", {}, ...cols.map((c) => el("th", {}, c)))), tbody)));
}

const STATUS = {
  traced: "Traced",
  none: "No step touched this cell",
  not_recorded: "Not recorded in this build",
};

function traceRecord(step, trace) {
  if (!trace) return el("div", { class: "how-trace" }, el("p", { class: "how-none" }, "This build has no trace for this cell."));
  const { status, ...record } = trace[step.record] ?? { status: "not_recorded" };
  // Closed by default: the strip above says the same in words.
  return el("details", { class: `how-trace ${status}` },
    el("summary", { class: "how-trace-head" }, el("strong", {}, "Raw trace record"), el("code", {}, step.record), el("span", {}, STATUS[status] ?? status)),
    status === "traced" ? el("div", { class: "how-scroll" }, el("pre", {}, JSON.stringify(record, null, 1))) : null);
}

const workList = (lines) => lines.length ? el("ul", { class: "how-details" }, ...lines.map((l) => el("li", {},
  l.href ? el("a", { href: l.href, target: "_blank", rel: "noopener" }, `${l.text} ↗`) : l.text))) : null;

// Hovering or focusing a term shows what it means and the code behind it. Clicking pins it open.
const term = (t, text) => hint(text, el("strong", {}, t.title), el("span", {}, t.text), t.code ? el("pre", {}, t.code) : null,
  el("a", { href: t.url, target: "_blank", rel: "noopener" }, `${t.where} ↗`));

// An example table's note names the example's own file when the node's name does not.
function rows(role, head, id, sheet, highlight) {
  const n = NODES[id], { name: file, note: about } = exampleOf(id);
  const note = file === nodeName(id, sheet) ? about : `${file} · ${about}`;
  if (n.table) return table(role, head, note, n.table.cols, n.table.rows, highlight);
  const hi = new Set(highlight);
  return frame(role, head, note, el("pre", {}, ...n.text.lines.map((l, i) => el("span", hi.has(i) ? { class: "hi" } : {}, l))));
}

function table(role, head, note, cols, body, highlight) {
  const hi = new Set(highlight);
  return frame(role, head, note, el("table", {},
    el("thead", {}, el("tr", {}, ...cols.map((c) => el("th", {}, c)))),
    el("tbody", {}, ...(body.length ? body.map((r, i) => el("tr", hi.has(i) ? { class: "hi" } : {}, ...r.map((c) => el("td", {}, c?.href ? linked(c.text, c.href) : c))))
      : [el("tr", {}, el("td", { colspan: cols.length }, "none"))]))));
}

const linked = (text, href) => href ? el("a", { href, target: "_blank", rel: "noopener" }, text) : text;

const frame = (role, head, note, body) => el("div", { class: `how-rows ${role.toLowerCase()}` },
  el("div", { class: "how-rows-head" }, el("strong", {}, role), ...head, el("span", {}, note)),
  body ? el("div", { class: "how-scroll" }, body) : null);
