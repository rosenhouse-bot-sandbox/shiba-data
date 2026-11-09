// The pipeline view: a map of tables and steps, and a lens on one step.
import { el, svg } from "./dom.js";
import { format } from "./permalink.js";
import {
  EXAMPLE, EXAMPLE_LABEL, EXAMPLE_VALUE, NODES, STEPS, LINKS, NODE_W, NODE_H, MAP_W, MAP_H,
  nodeBox, pillBox, edge, before, after,
} from "./pipeline.js";

// The map is drawn at full size, then scaled to fit its rail.
const RAIL_W = 492;
const SCALE = RAIL_W / MAP_W;

export const howLink = (year, step) => format({ year, view: "how", ...EXAMPLE, step: step.id });
const shown = (id) => NODES[id].table ?? NODES[id].text;

export function howView(year, step, terms) {
  const at = STEPS.indexOf(step);
  const link = (s) => howLink(year, s);
  const prev = STEPS[at - 1], next = STEPS[at + 1];
  return el("div", { class: "how" },
    el("div", { class: "how-head" },
      el("span", {}, "Following one cell:"),
      el("span", { class: "how-cell" }, EXAMPLE_LABEL),
      el("code", { class: "how-value" }, EXAMPLE_VALUE),
      el("span", { class: "how-spacer" }),
      prev ? el("a", { class: "how-nav", href: link(prev), rel: "prev" }, "← Prev") : el("span", { class: "how-nav off" }, "← Prev"),
      el("span", { class: "how-count" }, `${at + 1} of ${STEPS.length}`),
      next ? el("a", { class: "how-nav primary", href: link(next), rel: "next" }, "Next →") : el("span", { class: "how-nav primary off" }, "Next →")),
    el("div", { class: "how-body" }, map(step, link), lens(step, link, terms)));
}

function map(step, link) {
  const on = new Set([step.from, step.to]);
  const lines = svg("svg", { width: MAP_W, height: MAP_H, "aria-hidden": "true" },
    svg("defs", {}, ...["off", "on"].map((k) => svg("marker", {
      id: `how-arrow-${k}`, viewBox: "0 0 10 10", refX: "9", refY: "5", markerWidth: "10", markerHeight: "10", markerUnits: "userSpaceOnUse", orient: "auto",
    }, svg("path", { d: "M0,0 L10,5 L0,10 z", class: `how-arrow ${k}` })))),
    ...[...LINKS.map(([f, t]) => ({ from: f, to: t, extra: true })), ...STEPS].map((s) => svg("path", {
      d: edge(s.from, s.to).d, class: `how-edge${s === step ? " on" : ""}${s.extra ? " extra" : ""}`,
      "marker-end": `url(#how-arrow-${s === step ? "on" : "off"})`,
    })));
  const nodes = Object.entries(NODES).map(([id, n]) => {
    const b = nodeBox(id);
    return el("div", {
      class: `how-node${on.has(id) ? " on" : ""}${n.source ? " source" : ""}`,
      style: `left:${b.x}px;top:${b.y}px;width:${NODE_W}px;height:${NODE_H}px`,
      title: `${n.kind}: ${n.label}`,
    }, el("small", {}, n.kind), el("code", {}, n.label));
  });
  const pills = STEPS.map((s) => {
    const b = pillBox(s);
    return el("a", { class: `how-pill${s === step ? " on" : ""}`, href: link(s), title: s.label,
      style: `left:${b.x}px;top:${b.y}px;width:${b.w}px;height:${b.h}px`,
      ...(s === step ? { "aria-current": "step" } : {}) }, s.label);
  });
  return el("section", { class: "how-map", "aria-label": "Tables and steps" },
    el("h2", {}, "Tables and steps"),
    el("div", { class: "how-frame", style: `width:${RAIL_W}px;height:${Math.ceil(MAP_H * SCALE)}px` },
      el("div", { class: "how-world", style: `width:${MAP_W}px;height:${MAP_H}px;transform:scale(${SCALE})` }, lines, ...nodes, ...pills)),
    el("p", { class: "how-legend" },
      el("span", { class: "source" }, "■"), " source ", el("span", {}, "■"), " table the pipeline writes"));
}

function lens(step, link, terms) {
  const chips = (steps, cls, text) => steps.length ? el("div", { class: `how-chips ${cls}` },
    ...steps.map((s) => el("a", { href: link(s) }, text(s.label)))) : null;
  const end = (id) => el("div", { class: `how-end${NODES[id].source ? " source" : ""}` },
    el("small", {}, NODES[id].kind), el("code", {}, shown(id).name));
  return el("section", { class: "how-lens" },
    chips(before(step), "before", (l) => `↖ after: ${l}`),
    el("div", { class: "how-edge-big" }, end(step.from), el("span", { class: "how-wire" }),
      el("h2", { class: "how-step", tabindex: "-1" }, step.label), el("span", { class: "how-wire to" }), end(step.to)),
    el("div", { class: "how-card" },
      el("p", { class: "how-strip" }, el("code", { class: "from" }, step.before), " becomes ", el("code", { class: "to" }, step.after)),
      ...step.paras.map((p) => el("p", {}, ...p.map((s) => typeof s === "string" ? s : term(terms[s[0]], s[1]))))),
    rows("Input", step.from, step.highlight[0], step.none?.[0]),
    rows("Output", step.to, step.highlight[1], step.none?.[1]),
    el("div", { class: "how-trace" }, el("p", { class: "how-none" }, "Loading the cell's trace…")),
    chips(after(step), "after", (l) => `next: ${l} ↘`));
}

export const traceUrl = (year, column) => `trace/${year}/${EXAMPLE.sheet}/${EXAMPLE.plan}/${column}`;

const STATUS = {
  traced: "Traced",
  none: "No step touched this cell",
  not_traced_yet: "Not traced yet",
  not_recorded: "Not recorded in this build",
};

export function traceRecord(step, trace) {
  if (!trace) return el("div", { class: "how-trace" }, el("p", { class: "how-none" }, "This build has no trace for this cell."));
  const { status, ...record } = trace[step.record] ?? { status: "not_recorded" };
  return el("div", { class: `how-trace ${status}` },
    el("div", { class: "how-trace-head" }, el("strong", {}, "Trace"), el("code", {}, step.record), el("span", {}, STATUS[status] ?? status)),
    status === "traced" ? el("div", { class: "how-scroll" }, el("pre", {}, JSON.stringify(record, null, 1))) : null);
}

let pops = 0;
// The one open pop-over, if any.
let opened = null;

const MARGIN = 8;

// Hovering or focusing a term shows what it means and the code behind it. Clicking pins it open.
function term(t, text) {
  const id = `how-pop-${++pops}`;
  const button = el("button", { type: "button", class: "how-term", "aria-expanded": "false", "aria-controls": id }, text);
  const pop = el("div", { class: "how-pop", id },
    el("strong", {}, t.title), el("span", {}, t.text),
    t.code ? el("pre", {}, t.code) : null,
    el("a", { href: t.url, target: "_blank", rel: "noopener" }, `${t.where} ↗`));
  const box = el("span", { class: "how-term-box" }, button, pop);
  let pinned = false;
  const close = () => {
    pinned = false;
    box.classList.remove("open");
    button.setAttribute("aria-expanded", "false");
    if (opened?.box === box) opened = null;
  };
  const open = () => {
    if (opened?.box !== box) opened?.close();
    opened = { box, close };
    box.classList.add("open");
    button.setAttribute("aria-expanded", "true");
    place(pop, button.getBoundingClientRect());
  };
  const leave = () => pinned || box.contains(document.activeElement) || close();
  box.addEventListener("mouseenter", open);
  box.addEventListener("mouseleave", leave);
  button.addEventListener("focus", open);
  box.addEventListener("focusout", (e) => pinned || box.contains(e.relatedTarget) || close());
  button.addEventListener("click", () => {
    if (pinned) return close();
    open();
    pinned = true;
  });
  return box;
}

// Places a pop-over under its term, or above it when there is no room, inside the window.
function place(pop, at) {
  const { innerWidth: w, innerHeight: h } = window;
  pop.style.maxWidth = `${w - 2 * MARGIN}px`;
  const { width, height } = pop.getBoundingClientRect();
  pop.style.left = `${Math.max(MARGIN, Math.min(at.left, w - width - MARGIN))}px`;
  const below = at.bottom + 4;
  pop.style.top = `${below + height <= h - MARGIN ? below : Math.max(MARGIN, at.top - height - 4)}px`;
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") opened?.close();
});
document.addEventListener("click", (e) => {
  if (opened && !opened.box.contains(e.target)) opened.close();
});
document.addEventListener("scroll", (e) => opened && !opened.box.contains(e.target) && opened.close(), true);

function rows(role, id, highlight, none) {
  const n = NODES[id], hi = new Set(highlight);
  const mark = (i) => hi.has(i) ? { class: "hi" } : {};
  const body = n.table
    ? (n.table.rows.length ? el("table", {},
        el("thead", {}, el("tr", {}, ...n.table.cols.map((c) => el("th", {}, c)))),
        el("tbody", {}, ...n.table.rows.map((r, i) => el("tr", mark(i), ...r.map((c) => el("td", {}, c)))))) : null)
    : el("pre", {}, ...n.text.lines.map((l, i) => el("span", mark(i), l)));
  const { name, note } = shown(id);
  return el("div", { class: `how-rows ${role.toLowerCase()}` },
    el("div", { class: "how-rows-head" }, el("strong", {}, role), el("code", {}, name), el("span", {}, note)),
    none ? el("p", { class: "how-none" }, none) : body ? el("div", { class: "how-scroll" }, body) : null);
}
