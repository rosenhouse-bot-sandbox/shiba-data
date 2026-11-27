// The tables view: one table of a build that D1 keeps, filtered, sorted and paged in the browser.
import { el } from "./dom.js";
import { format } from "./permalink.js";

export const PAGE_SIZE = 100;

// The pipeline's tables in its order, each with what a row holds.
export const TABLES = {
  plans: "One row per plan, from the CMS Landscape file.",
  landscape_reads: "The Landscape fields read for each plan.",
  documents: "The URL used for each plan's SB and EOC.",
  pbp_facts: "Facts code made from the CMS PBP files.",
  document_facts: "Facts Claude read from the PDFs, after checks. One row per fact and page.",
  cms_sources: "Which CMS field fed which sheet column.",
  presented: "One row per citation in the sheets.",
  main_chart: "The main sheet.",
  dvha: "The dental, vision, hearing and extras sheet.",
};

export const ordered = (names) => {
  const known = Object.keys(TABLES);
  return [...known.filter((n) => names.includes(n)), ...names.filter((n) => !known.includes(n)).toSorted()];
};

const plansOf = (row) => (row.plan_id ?? row.plan_ids ?? "").split(";");

// The rows that match the plan, the sheet's column, and the search. A filter applies only to a table with its field.
export function shown(rows, { plan, sheet, column, query }) {
  const words = query?.trim().toLowerCase();
  return rows.filter((r) => (!plan || plansOf(r).includes(plan))
    && (!column || !("column" in r) || (r.column === column && (!("sheet" in r) || r.sheet === sheet)))
    && (!words || Object.values(r).some((v) => v.toLowerCase().includes(words))));
}

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });
const NUMBER = /^(?=\D*\d)\$?-?(\d{1,3}(,\d{3})+|\d*)(\.\d+)?%?$/;
const number = (v) => Number(v.replace(/[$,%]/g, ""));
// The collator reads "$1,980" as 1, so a text sort drops each thousands separator first.
const unseparated = (v) => v.replace(/(\d),(?=\d{3}\b)/g, "$1");

// Sorts by one column. A column whose every value is a number, an amount or a percentage sorts as numbers.
// Blanks sort last either way.
export function sortRows(rows, col, direction) {
  const factor = direction === "descending" ? -1 : 1;
  const values = rows.map((r) => r[col] ?? "");
  const numeric = values.some(Boolean) && values.every((v) => !v || NUMBER.test(v));
  const order = (a, b) => numeric ? number(a) - number(b) : collator.compare(unseparated(a), unseparated(b));
  return rows.map((r, i) => [values[i], r]).sort(([a], [b]) => !a || !b ? !a - !b : factor * order(a, b)).map(([, r]) => r);
}

export function pageOf(rows, page) {
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const at = Math.min(Math.max(1, page), pages);
  const start = (at - 1) * PAGE_SIZE;
  return { page: at, pages, first: rows.length ? start + 1 : 0, last: Math.min(start + PAGE_SIZE, rows.length), rows: rows.slice(start, start + PAGE_SIZE) };
}

export const rowCount = (n) => `${n.toLocaleString("en-US")} ${n === 1 ? "row" : "rows"}`;

// The state with no plan or column that matches no row, and no column for a table without one.
export function known(state, rows) {
  const plans = new Set(rows.flatMap(plansOf));
  const plan = plans.has(state.plan) ? state.plan : undefined;
  const column = rows.some((r) => r.column === state.column && (!("sheet" in r) || r.sheet === state.sheet)) ? state.column : undefined;
  return { ...state, plan, sheet: column && state.sheet, column };
}

const csvValue = (v) => /[",\r\n]/.test(v) ? `"${v.replaceAll('"', '""')}"` : v;
export const toCsv = (cols, rows) => [cols, ...rows.map((r) => cols.map((c) => r[c] ?? ""))].map((r) => `${r.map(csvValue).join(",")}\r\n`).join("");

// Each table's search, sort, page and hidden columns, kept while the visitor moves between tables.
const views = {};

// at is { year, state, table, rows, builds, sha, gitTables, planName, columnLabel, pageHref }.
// builds is the Worker's builds.json. gitTables lists { name, href } of the tables that stay in git.
export function tablesView(at) {
  const { year, state, table, rows, builds, sha, gitTables, planName, columnLabel, pageHref } = at;
  const view = views[table] ??= { query: "", sort: null, page: 1, hidden: new Set() };
  // Another build or filter starts again at the first page.
  const shownAt = [sha, state.plan, state.sheet, state.column].join("|");
  if (view.at !== shownAt) Object.assign(view, { at: shownAt, page: 1 });
  const cols = Object.keys(rows[0] ?? {});
  const filters = { plan: state.plan, sheet: state.sheet, column: state.column };
  const link = (change) => format({ year, view: "tables", build: state.build, table, ...filters, ...change });
  const hasColumn = cols.includes("column");

  const list = el("nav", { class: "tables-list", "aria-label": "Tables" },
    el("h2", { class: "store-d1" }, "In D1"),
    el("ul", {}, ...ordered(builds.builds.find((b) => b.sha === sha).tables).map((name) => el("li", {},
      el("a", { href: link({ table: name }), ...(name === table ? { "aria-current": "page" } : {}) },
        el("code", {}, name))))),
    el("h2", { class: "store-git" }, "In git"),
    el("ul", {}, ...gitTables.map((t) => el("li", {},
      el("a", { href: t.href, target: "_blank", rel: "noopener", "aria-label": `${t.name}, opens GitHub in a new tab` }, el("code", {}, t.name), " ↗")))),
    el("p", {}, "How it's made links to page text and model answers, which are files rather than tables."));

  const age = (b) => new Intl.RelativeTimeFormat(undefined, { numeric: "auto" }).format(Math.round((b.loaded - Date.now()) / 3600000), "hour");
  const buildPick = el("select", { id: "tables-build" }, ...builds.builds.filter((b) => b.tables.includes(table)).map((b) => {
    const label = `${b.sha.slice(0, 7)}${b.sha === builds.deployed ? " · on the site now" : ""} · loaded ${age(b)}`;
    return el("option", { value: b.sha, ...(b.sha === sha ? { selected: "" } : {}) }, label);
  }));
  // A menu's change replaces the history entry, since arrow keys change a closed menu once per option they pass.
  buildPick.addEventListener("change", () => location.replace(link({ build: buildPick.value })));

  const planIds = [...new Set(rows.flatMap(plansOf))].filter(Boolean).toSorted(collator.compare);
  const planPick = select("tables-plan", "Plan", [["", "All plans"], ...planIds.map((p) => [p, `${p} · ${planName(p)}`])], state.plan ?? "",
    (v) => location.replace(link({ plan: v || undefined })));
  // A table without a sheet field, like cms_sources, holds the main sheet's columns.
  const columnKeys = hasColumn ? [...new Set(rows.map((r) => `${r.sheet ?? "main"}/${r.column}`))] : [];
  const columnPick = hasColumn ? select("tables-column", "Column", [["", "All columns"],
    ...columnKeys.map((k) => [k, columnLabel(...k.split("/"))])], state.column ? `${state.sheet}/${state.column}` : "",
  (v) => { const [s, c] = v ? v.split("/") : []; location.replace(link({ sheet: s, column: c })); }) : null;

  const search = el("input", { type: "search", id: "tables-search", placeholder: "Search every column", value: view.query });
  search.addEventListener("input", () => {
    view.query = search.value;
    view.page = 1;
    refresh();
  });

  const chooser = el("details", { class: "tables-columns" }, el("summary", {}),
    el("fieldset", {}, el("legend", {}, "Show columns"), ...cols.map((c) => {
      const box = el("input", { type: "checkbox", value: c, ...(view.hidden.has(c) ? {} : { checked: "" }) });
      box.addEventListener("change", () => {
        if (box.checked) view.hidden.delete(c);
        else view.hidden.add(c);
        if (view.sort?.col === c) view.sort = null;
        refresh();
      });
      return el("label", {}, box, " ", el("code", {}, c));
    })));

  const download = el("button", { type: "button" }, "Download CSV");
  download.addEventListener("click", () => {
    const url = URL.createObjectURL(new Blob([toCsv(visible(), sorted())], { type: "text/csv" }));
    el("a", { href: url, download: `${table}-${sha.slice(0, 7)}.csv` }).click();
    setTimeout(() => URL.revokeObjectURL(url));
  });

  // Narrow screens show rows as cards with no header row, so they sort with this instead.
  const sortPick = select("tables-sort", "Sort", [], "", (v) => sortBy(...(v ? v.split(" ") : [])));

  const captionId = "tables-caption";
  const thead = el("thead"), tbody = el("tbody");
  const status = el("p", { class: "tables-count", role: "status" });
  const prev = el("button", { type: "button" }, "← Prev"), next = el("button", { type: "button" }, "Next →");
  const where = el("span");
  prev.addEventListener("click", () => turn(-1));
  next.addEventListener("click", () => turn(1));

  const visible = () => cols.filter((c) => !view.hidden.has(c));
  const matching = () => shown(rows, { ...filters, query: view.query });
  const sorted = () => view.sort ? sortRows(matching(), view.sort.col, view.sort.direction) : matching();
  function sortBy(col, direction) {
    view.sort = col ? { col, direction } : null;
    view.page = 1;
    refresh();
  }
  function turn(by) {
    view.page += by;
    refresh();
    // A button that the last or first page disables gives focus to the other.
    if (document.activeElement === document.body || document.activeElement?.disabled) (by > 0 ? prev : next).focus();
    status.scrollIntoView({ block: "nearest" });
  }

  function refresh() {
    const shownCols = visible(), all = sorted(), page = pageOf(all, view.page);
    view.page = page.page;
    chooser.querySelector("summary").textContent = `Columns · ${shownCols.length} of ${cols.length}`;
    // The last shown column stays.
    chooser.querySelectorAll("input").forEach((box) => { box.disabled = shownCols.length === 1 && box.checked; });
    const refocus = thead.contains(document.activeElement);
    thead.replaceChildren(el("tr", {}, ...shownCols.map((c) => {
      const on = view.sort?.col === c;
      const button = el("button", { type: "button" }, el("code", {}, c), el("span", { class: "tables-arrow", "aria-hidden": "true" }));
      button.addEventListener("click", () => sortBy(c, on && view.sort.direction === "ascending" ? "descending" : "ascending"));
      return el("th", { scope: "col", ...(on ? { "aria-sort": view.sort.direction } : {}) }, button);
    })));
    // Keeps focus on the header button that sorted.
    if (refocus && view.sort) thead.querySelectorAll("button")[shownCols.indexOf(view.sort.col)]?.focus();
    sortPick.querySelector("select").replaceChildren(el("option", { value: "" }, "table order"), ...shownCols.flatMap((c) => ["ascending", "descending"].map((d) =>
      el("option", { value: `${c} ${d}`, ...(view.sort?.col === c && view.sort.direction === d ? { selected: "" } : {}) },
        `${c} ${d === "ascending" ? "▲" : "▼"}`))));
    tbody.replaceChildren(...page.rows.map((r) => {
      const tr = el("tr");
      tr.append(...shownCols.map((c) => {
        const value = r[c] ?? "", href = (c === "page" || c === "pdf_page") && value ? pageHref(r, value) : null;
        return el("td", { "data-col": c }, href ? el("div", {}, el("a", { href }, value)) : value.length > LONG ? more(tr, value) : el("div", {}, value));
      }));
      return tr;
    }));
    if (!page.rows.length) tbody.append(el("tr", {}, el("td", { colspan: shownCols.length || 1 }, "No rows match.")));
    const of = filters.plan || filters.column || view.query.trim() ? ` of ${rows.length.toLocaleString("en-US")} match` : "";
    status.textContent = of ? `${all.length.toLocaleString("en-US")}${of}` : rowCount(all.length);
    where.textContent = `Rows ${page.first.toLocaleString("en-US")}–${page.last.toLocaleString("en-US")} of ${all.length.toLocaleString("en-US")}`;
    prev.disabled = page.page === 1;
    next.disabled = page.page === page.pages;
  }
  refresh();

  return el("div", { class: "tables" }, list,
    el("section", { class: "tables-main" },
      el("div", { class: "tables-head" },
        el("h2", {}, el("code", {}, table)), el("span", {}, TABLES[table] ?? ""),
        el("label", { class: "tables-build" }, "Build ", buildPick)),
      el("div", { class: "tables-filters" }, planPick, columnPick,
        el("label", { class: "tables-search" }, "Find ", search), chooser, sortPick, download),
      status,
      el("div", { class: "tables-scroll", role: "region", tabindex: "0", "aria-labelledby": captionId },
        el("table", {}, el("caption", { id: captionId }, `${table} rows`), thead, tbody)),
      el("div", { class: "tables-pager" }, prev, where, next)));
}

// A value longer than this shows its start, and a button shows the whole row's values.
const LONG = 40;
function more(tr, value) {
  const button = el("button", { type: "button", class: "tables-more", "aria-expanded": "false", title: value }, value);
  button.addEventListener("click", () => {
    const open = tr.classList.toggle("open");
    tr.querySelectorAll(".tables-more").forEach((b) => b.setAttribute("aria-expanded", String(open)));
  });
  return button;
}

function select(id, label, options, value, change) {
  const pick = el("select", { id }, ...options.map(([v, text]) => el("option", { value: v, ...(v === value ? { selected: "" } : {}) }, text)));
  pick.addEventListener("change", () => change(pick.value));
  return el("label", {}, `${label} `, pick);
}
