// The pipeline view: a map of tables and steps, and a lens on one step.
import { el, svg } from "./dom.js";
import { format } from "./permalink.js";
import {
  EXAMPLE, EXAMPLE_LABEL, EXAMPLE_VALUE, NODES, STEPS, LINKS, NODE_W, NODE_H, MAP_W, MAP_H,
  nodeBox, pillBox, edge, before, after,
} from "./pipeline.js";

// The map is drawn at full size, then scaled to fit its rail.
const RAIL_W = 432;
const SCALE = RAIL_W / MAP_W;

export function howView(year, step) {
  const at = STEPS.indexOf(step);
  const link = (s) => format({ year, view: "how", ...EXAMPLE, step: s.id });
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
    el("div", { class: "how-body" }, map(step, link), lens(step, link)));
}

function map(step, link) {
  const on = new Set([step.from, step.to]);
  const lines = svg("svg", { width: MAP_W, height: MAP_H, "aria-hidden": "true" },
    svg("defs", {}, ...["off", "on"].map((k) => svg("marker", {
      id: `how-arrow-${k}`, viewBox: "0 0 10 10", refX: "9", refY: "5", markerWidth: "7", markerHeight: "7", orient: "auto",
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
    }, el("small", {}, n.kind), el("code", {}, n.label));
  });
  const pills = STEPS.map((s) => {
    const b = pillBox(s);
    return el("a", { class: `how-pill${s === step ? " on" : ""}`, href: link(s), style: `left:${b.x}px;top:${b.y}px;width:${b.w}px;height:${b.h}px`,
      ...(s === step ? { "aria-current": "step" } : {}) }, s.label);
  });
  return el("nav", { class: "how-map", "aria-label": "Tables and steps" },
    el("h2", {}, "Tables and steps"),
    el("div", { style: `height:${Math.ceil(MAP_H * SCALE)}px` },
      el("div", { class: "how-world", style: `width:${MAP_W}px;height:${MAP_H}px;transform:scale(${SCALE})` }, lines, ...nodes, ...pills)),
    el("p", { class: "how-legend" },
      el("span", { class: "source" }, "■"), " source ", el("span", {}, "■"), " table the pipeline writes"));
}

function lens(step, link) {
  const chips = (steps, cls, text) => steps.length ? el("div", { class: `how-chips ${cls}` },
    ...steps.map((s) => el("a", { href: link(s) }, text(s.label)))) : null;
  const end = (id) => el("div", { class: `how-end${NODES[id].source ? " source" : ""}` },
    el("small", {}, NODES[id].kind), el("code", {}, (NODES[id].table ?? NODES[id].text).name));
  return el("section", { class: "how-lens", "aria-live": "polite" },
    chips(before(step), "before", (l) => `↖ after: ${l}`),
    el("div", { class: "how-edge-big" }, end(step.from), el("span", { class: "how-wire" }),
      el("h2", { class: "how-step" }, step.label), el("span", { class: "how-wire to" }), end(step.to)),
    el("div", { class: "how-card" },
      el("p", { class: "how-strip" }, el("code", { class: "from" }, step.before), " becomes ", el("code", { class: "to" }, step.after)),
      ...step.paras.map((p) => el("p", {}, ...p.map(segment)))),
    rows("Input", step.from, step.highlight[0], step.none?.[0]),
    rows("Output", step.to, step.highlight[1], step.none?.[1]),
    chips(after(step), "after", (l) => `next: ${l} ↘`));
}

const segment = (s) => typeof s === "string" ? s : el("span", { class: "how-term", "data-term": s[0] }, s[1]);

function rows(role, id, highlight, none) {
  const n = NODES[id], hi = new Set(highlight);
  const mark = (i) => hi.has(i) ? { class: "hi" } : {};
  const body = n.table
    ? (n.table.rows.length ? el("table", {},
        el("thead", {}, el("tr", {}, ...n.table.cols.map((c) => el("th", {}, c)))),
        el("tbody", {}, ...n.table.rows.map((r, i) => el("tr", mark(i), ...r.map((c) => el("td", {}, c)))))) : null)
    : el("pre", {}, ...n.text.lines.map((l, i) => el("span", mark(i), l)));
  const { name, note } = n.table ?? n.text;
  return el("div", { class: `how-rows ${role.toLowerCase()}` },
    el("div", { class: "how-rows-head" }, el("strong", {}, role), el("code", {}, name), el("span", {}, note)),
    none ? el("p", { class: "how-none" }, none) : body ? el("div", { class: "how-scroll" }, body) : null);
}
