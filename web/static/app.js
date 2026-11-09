import * as pdfjsLib from "https://cdn.jsdelivr.net/npm/pdfjs-dist@4.10.38/build/pdf.min.mjs";
import { findAll, matchRanges, squash } from "./highlight.js";
import { ago } from "./ago.js";
import { parse, format } from "./permalink.js";
import { el } from "./dom.js";
import { howView, howLink, traceUrl } from "./how.js";
import { EXAMPLE, chain } from "./pipeline.js";

pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4.10.38/build/pdf.worker.min.mjs";

const SHEET_NAMES = { main: "Main chart", dvha: "Dental, vision, hearing & extras" };
// Keep in sync with KIND_NAMES in web/sheet_layout.py.
const KIND_NAMES = { question: "Open question", caveat: "Caveat", added: "Added fact" };
let kindFilter = "";
const $ = (sel) => document.querySelector(sel);

// Keep in sync with PAGE_REF in web/build.py.
const PAGE_REF = /\b(EOC|SB|rider) pages? (\d+)/gi;

let site;
let pageObserver;
let plans;
const scrollTops = {};
// The view that route() last rendered, and the cell picked in it.
let here;
// The hash that route() last showed or updateUrl() last wrote.
let routed;
let selection = null;
// Set by a click, so the URL change it makes adds a history entry.
let pushNext = false;

function showUpdated(built) {
  if (isNaN(built)) return;
  const label = $("#updated");
  label.title = built.toLocaleString(undefined, { dateStyle: "full", timeStyle: "long" });
  const refresh = () => { label.textContent = `Last updated ${ago(built, new Date())}`; };
  refresh();
  setInterval(refresh, 60000);
}

async function start() {
  site = await (await fetch("data.json")).json();
  plans = Object.fromEntries(site.plans.map((p) => [p.plan_id, p]));
  showUpdated(new Date(site.built));
  if (site.sheet_id) {
    $("#sheet-link").href = `https://docs.google.com/spreadsheets/d/${site.sheet_id}/edit`;
    $("#sheet-link").hidden = false;
  }
  $("#prev").addEventListener("click", () => goTo(currentPage() - 1));
  $("#next").addEventListener("click", () => goTo(currentPage() + 1));
  $("#page").addEventListener("change", (e) => goTo(Number(e.target.value)));
  $("#close").addEventListener("click", () => {
    pushNext = true;
    closeViewer();
  });
  $("#find-open").addEventListener("click", openFind);
  $("#find-query").addEventListener("input", search);
  $("#find-query").addEventListener("keydown", (e) => {
    if (e.key === "Enter") step(e.shiftKey ? -1 : 1);
  });
  $("#find").addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      e.preventDefault();
      closeFind();
    }
  });
  $("#find-prev").addEventListener("click", () => step(-1));
  $("#find-next").addEventListener("click", () => step(1));
  $("#find-close").addEventListener("click", closeFind);
  // A second Ctrl+F, from the find box, falls through to the browser's own find.
  document.addEventListener("keydown", (e) => {
    if (e.key.toLowerCase() !== "f" || !(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey) return;
    if ($("#viewer").hidden || !viewer.pdf || (!$("#find").hidden && $("#find").contains(document.activeElement))) return;
    e.preventDefault();
    openFind();
  });
  window.addEventListener("hashchange", route);
  pageObserver = new IntersectionObserver(onVisible, { root: area(), rootMargin: "1500px 0px" });
  area().addEventListener("scroll", () => {
    if (!holders().length) return;
    viewer.page = currentPage();
    if (document.activeElement !== $("#page")) $("#page").value = viewer.page;
    viewer.anchor = centerAnchor();
    updateUrl();
  });
  new ResizeObserver(() => {
    if (!viewer.pdf || !area().clientWidth) return;
    if (area().clientWidth !== viewer.width) layoutPages();
    if (viewer.target) goTo(viewer.target.n, viewer.target.focus);
    else if (viewer.anchor) restoreAnchor(viewer.anchor);
  }).observe(area());
  route();
}

function route() {
  routed = location.hash;
  howTicket++;
  let state = parse(location.hash, site.year);
  const otherYear = state.year !== site.year && state.year;
  if (otherYear || (state.view === "plan" && !plans[state.plan])) {
    state = { year: site.year, view: "main" };
    history.replaceState(null, "", format(state));
    routed = location.hash;
  }
  if (otherYear) hideViewer();
  if (state.view === "how") return routeHow(state);
  const { view } = state;
  const plan = view === "plan" && plans[state.plan];
  const key = `${view}/${plan ? plan.plan_id : ""}`;
  document.querySelectorAll("header nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
  const content = $("#content");
  const sameView = key === here?.key && !otherYear;
  if (!sameView) {
    if (here) scrollTops[here.key] = content.scrollTop;
    content.replaceChildren(view === "notes" ? notesView() : plan ? planPage(plan) : sheetView(view));
    if (otherYear) content.prepend(el("p", { class: "warn" }, `That link was for ${otherYear} plans. This site shows ${site.year} plans.`));
    content.scrollTop = scrollTops[key] ?? 0;
  }
  here = { key, view, plan: state.plan };
  markOpenPlans();
  const at = state.kind && { kind: state.kind, page: state.page };
  // Links from before column ids name the column by its key.
  const column = sheetOf(state)?.columns.find((c) => c.id === state.column || c.key === state.column);
  const td = column && content.querySelector(
    `td[data-sheet="${state.sheet}"][data-plan="${CSS.escape(state.plan)}"][data-col="${CSS.escape(column.key)}"]`);
  if (td) {
    pick(td);
    openCell(plans[td.dataset.plan], column, site[state.sheet].rows.find((r) => r.plan_id === td.dataset.plan).cells[column.key], at);
  } else if (plan) {
    unpick();
    const doc = plan.docs.find((d) => site.docs[d].kind === at?.kind);
    openDoc(doc || planSb(plan), doc ? at.page : 1, null, null);
  } else if (sameView && selection) {
    // Back from a cell to its view with no cell picked.
    closeViewer();
  } else {
    unpick();
  }
  updateUrl();
}

// A link may name any sheet, but only a sheet the site shows has cells.
const sheetOf = (state) => Object.hasOwn(SHEET_NAMES, state.sheet) ? site[state.sheet] : null;

// An unknown cell opens the example cell, and a step the cell skips opens its first step.
let howTicket = 0;
async function routeHow(state) {
  hideViewer();
  const ticket = ++howTicket, asked = location.hash;
  // Links from before column ids name the column by its key.
  const asColumn = sheetOf(state)?.columns.find((c) => c.id === state.column || c.key === state.column);
  const known = asColumn && site[state.sheet].rows.some((r) => r.plan_id === state.plan);
  const { sheet, plan } = known ? state : EXAMPLE;
  const column = known ? asColumn : site.main.columns.find((c) => c.id === EXAMPLE.column);
  document.querySelectorAll("header nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === "how"));
  const content = $("#content");
  const map = content.querySelector(".how-map");
  const mapTop = map?.scrollTop ?? 0;
  if (!map) {
    if (here) scrollTops[here.key] = content.scrollTop;
    content.replaceChildren(el("p", { class: "how-loading" }, "Loading the cell's trace…"));
  }
  here = { key: "how", view: "how" };
  const trace = await traceOf(sheet, plan, column.key);
  if (ticket !== howTicket || location.hash !== asked) return;
  const steps = chain(trace);
  const step = steps.find((s) => s.id === state.step) ?? steps[0];
  const value = site[sheet].rows.find((r) => r.plan_id === plan).cells[column.key].value;
  const cell = { sheet, plan, column: column.id, label: `${plans[plan].plan_name} · ${column.label}`, value };
  const hash = howLink(site.year, cell, step);
  if (location.hash !== hash) history.replaceState(null, "", hash);
  routed = location.hash;
  content.replaceChildren(howView({ year: site.year, cell, step, steps, terms: site.terms, trace }));
  if (state.plan && !known) content.prepend(el("p", { class: "warn" }, "That link names no cell, so this shows the example cell."));
  content.querySelector(".how-map").scrollTop = mapTop;
  if (map) content.querySelector(".how-step").focus({ preventScroll: true });
}

// A failed load is not kept, so the next visit tries again.
const traces = {};
const traceOf = (sheet, plan, columnKey) => {
  const url = traceUrl(site.year, sheet, plan, columnKey);
  return traces[url] ??= fetch(url).then((r) => r.ok ? r.json() : null).catch(() => null)
    .then((trace) => trace ?? (delete traces[url], null));
};

const planSb = (plan) => plan.docs.find((d) => site.docs[d].kind === "SB");

function pick(td) {
  unpick();
  td.classList.add("selected");
  selection = td;
  td.scrollIntoView({ block: "nearest", inline: "nearest" });
  linkHow();
}

function unpick() {
  document.querySelectorAll(".selected").forEach((s) => s.classList.remove("selected"));
  selection = null;
  linkHow();
}

// The ? beside a cell's note and the header's "How it's made" open the last step of the selected cell's pipeline view.
function linkHow() {
  const { sheet, plan, col } = selection?.dataset ?? {};
  const href = selection ? format({ year: site.year, view: "how", sheet, plan, column: site[sheet].columns.find((c) => c.key === col).id, step: "publish" }) : "#/how";
  $("#how-this").hidden = !selection;
  $("#how-this").href = href;
  $("header nav a[data-view=how]").href = href;
}

// The document and page that opening the selected cell, or the plan page, shows first.
function defaultDoc() {
  if (selection) {
    const { plan, sheet, col } = selection.dataset;
    const cell = site[sheet].rows.find((r) => r.plan_id === plan).cells[col];
    const first = cell.cites[0] || cell.comment;
    return first ? { doc: first.doc, page: first.page } : { doc: planSb(plans[plan]), page: 1 };
  }
  return here.view === "plan" ? { doc: planSb(plans[here.plan]), page: 1 } : null;
}

// Points the URL at the selected cell and the shown page.
function updateUrl() {
  const push = pushNext;
  pushNext = false;
  // A link changed the hash, and its hashchange event has not yet run route().
  if (!here || here.view === "how" || location.hash !== routed) return;
  const state = { year: site.year, view: here.view, plan: here.plan };
  if (selection) {
    const { plan, sheet, col } = selection.dataset;
    Object.assign(state, { plan, sheet, column: site[sheet].columns.find((c) => c.key === col).id });
  }
  const fallback = defaultDoc();
  if (!$("#viewer").hidden && viewer.showing && (viewer.showing !== fallback?.doc || viewer.page !== fallback?.page)) {
    Object.assign(state, { kind: site.docs[viewer.showing].kind, page: viewer.page });
  }
  const hash = format(state);
  if (hash !== location.hash) history[push ? "pushState" : "replaceState"](null, "", hash);
  routed = location.hash;
}

function sheetView(name) {
  const sheet = site[name];
  const table = el("table", { class: "sheet" });
  table.append(el("thead", {}, el("tr", {}, el("th", { class: "plan" }, "Plan"),
    ...sheet.columns.map((c) => el("th", {}, c.label)))));
  const body = el("tbody");
  let section;
  for (const row of sheet.rows) {
    if (row.section !== section) {
      section = row.section;
      body.append(el("tr", { class: "section" }, el("th", { colspan: sheet.columns.length + 1 }, el("span", {}, site.sections[section] || section))));
    }
    const plan = plans[row.plan_id];
    body.append(el("tr", { "data-plan": row.plan_id },
      el("th", { class: "plan" }, planLink(plan), el("small", {}, row.plan_id)),
      ...sheet.columns.map((c) => valueCell(name, plan, c, row.cells[c.key]))));
  }
  table.append(body);
  return el("div", { class: "sheet-wrap" }, table);
}

// Links to the plan's page, keeping the page of its document that the viewer shows.
function planLink(plan) {
  const hash = () => {
    const open = !$("#viewer").hidden && site.docs[viewer.showing]?.plan_ids.includes(plan.plan_id);
    return format({ year: site.year, view: "plan", plan: plan.plan_id, ...(open && { kind: site.docs[viewer.showing].kind, page: viewer.page }) });
  };
  const a = el("a", { href: format({ year: site.year, view: "plan", plan: plan.plan_id }), onclick: () => { a.href = hash(); } }, plan.plan_name);
  return a;
}

// Runs a link's action as a click that adds a history entry.
const clicked = (action) => (e) => {
  e.preventDefault();
  pushNext = true;
  action(e);
};

function valueCell(sheet, plan, column, cell) {
  const td = el("td", {
    "data-sheet": sheet,
    "data-plan": plan.plan_id,
    "data-col": column.key,
    class: [cell.cites.length && "cited", cell.comment && "commented", cell.comment?.kind, /^[●◐]$/.test(cell.value) && "dot"]
      .filter(Boolean).join(" "),
    title: (cell.comment && `${KIND_NAMES[cell.comment.kind]}: ${cell.comment.text}`) || (cell.cites.length ? "Click to see the plan document page" : "From CMS plan data. Click to open the plan's Summary of Benefits."),
    onclick: () => {
      pick(td);
      pushNext = true;
      openCell(plan, column, cell);
    },
  });
  cell.value.split(" | ").forEach((line, i) => td.append(i ? el("br") : "", line));
  return td;
}

const cellHeader = (plan, column, cell) => el("div", {}, el("b", {}, `${plan.plan_name}: ${column.label} = ${oneLine(cell.value)}`),
  cell.comment ? el("p", { class: `comment ${cell.comment.kind}` }, el("b", {}, `${KIND_NAMES[cell.comment.kind]}: `),
    ...commentText(plan, column, cell)) : null);

// Links each "EOC page N" in a comment to page N of the plan's document of that kind.
function commentText(plan, column, cell) {
  const { text } = cell.comment;
  const parts = [];
  let at = 0;
  for (const ref of text.matchAll(PAGE_REF)) {
    const doc = plan.docs.find((d) => site.docs[d].kind === ref[1].toUpperCase());
    parts.push(text.slice(at, ref.index), el("a", {
      href: "#",
      onclick: clicked((e) => {
        if (e.target.closest("#source-note")) return openDoc(doc, Number(ref[2]), null, $("#source-note").firstElementChild);
        pick(e.target.closest("tr").querySelector("td[data-col]"));
        openCell(plan, column, cell, { kind: ref[1].toUpperCase(), page: Number(ref[2]) });
      }),
    }, ref[0]));
    at = ref.index + ref[0].length;
  }
  parts.push(text.slice(at));
  return parts;
}

const commentSource = (cell, note) => {
  const { doc, page, quote } = cell.comment;
  return el("p", { class: "comment-source" }, "Comment source: ",
    el("a", { href: "#", onclick: clicked(() => openDoc(doc, page, quote, note)) }, `${site.docs[doc].kind} page ${page}`),
    `: “${quote}”`);
};

// Opens the cell's first citation, or else its comment's source, or else the plan's SB.
// at ({ kind, page }) opens that page of the plan's document of that kind instead.
function openCell(plan, column, cell, at = null) {
  const header = cellHeader(plan, column, cell);
  let note;
  if (cell.cites.length) {
    note = citeNote(header, cell);
    note.append(medicareGov(plan, column));
  } else if (cell.comment) {
    note = el("div", {}, header);
    note.append(commentSource(cell, note), ...cmsFields(cell), medicareGov(plan, column));
  } else {
    note = el("div", {}, header, el("p", {},
      cell.value ? `This value comes from CMS ${site.year} plan data, which has no page to point to. `
        : `The CMS ${site.year} Plan Benefit Package data has no entry for this benefit. `,
      "The plan's Summary of Benefits is shown for reference."), ...cmsFields(cell), medicareGov(plan, column));
  }
  const first = cell.cites[0] || cell.comment || { doc: planSb(plan), page: 1, quote: null };
  const doc = plan.docs.find((d) => site.docs[d].kind === at?.kind);
  if (!doc) return openDoc(first.doc, first.page, first.quote, note, cell.cites);
  const quote = [...cell.cites, cell.comment].find((q) => q?.doc === doc && q.page === at.page)?.quote ?? null;
  openDoc(doc, at.page, quote, note, cell.cites);
}

const newTab = (href, text) => el("a", { href, target: "_blank", rel: "noopener" }, text);

const medicareGov = (plan, column) => el("p", {}, newTab(plan.plan_finder_url, "View this plan on Medicare.gov ↗"),
  column.medicare_gov ? ` ${column.medicare_gov}` : null);

function cmsFields(cell) {
  if (!cell.cms) return [];
  const byFile = Map.groupBy(cell.cms, (f) => f.file);
  return [...byFile].map(([file, fields]) => el("div", { class: "cms" },
    file === "Landscape" ? newTab(site.cms_files.Landscape, "CMS Landscape file ↗")
      : newTab(site.cms_files.PBP, `CMS Plan Benefit Package file, ${file} ↗`),
    el("ul", {}, ...fields.map((f) => el("li", {}, f.title ? `${f.title} (${f.field})` : f.field,
      ` = ${f.value}`, f.meaning ? ` (${f.meaning})` : "")))));
}

const oneLine = (value) => value.split(" | ").join("; ");

function citeNote(header, cell) {
  const note = el("div", {}, header);
  if (!cell.value.trim()) note.append(el("p", {}, "The plan document shows why this is blank:"));
  cell.cites.forEach((c, i) => {
    const doc = site.docs[c.doc];
    note.append(el("p", { class: "cite" },
      el("a", { href: "#", onclick: clicked(() => openDoc(c.doc, c.page, c.quote, note, cell.cites)) },
        `${doc.kind} page ${c.page}`),
      c.line ? ` (line ${c.line})` : "", `: “${c.quote}”`));
  });
  if (cell.comment) note.append(commentSource(cell, note));
  if (cell.pbp != null) {
    note.append(el("p", { class: "pbp" }, cell.pbp
      ? `CMS plan data shows ${cell.pbp === "●" ? "this benefit is covered" : oneLine(cell.pbp)}. The plan document overrides it.`
      : "CMS plan data leaves this blank. The plan document fills it in."));
  }
  return note;
}

function notesView() {
  const rows = Object.keys(SHEET_NAMES).flatMap((sheet) => site[sheet].rows.flatMap((r) =>
    site[sheet].columns.filter((c) => r.cells[c.key].comment).map((c) => noteRow(sheet, plans[r.plan_id], c, r.cells[c.key]))));
  const applyFilter = () => rows.forEach((r) => { r.hidden = Boolean(kindFilter) && r.dataset.kind !== kindFilter; });
  const filter = el("select", { id: "kind-filter", onchange: () => { kindFilter = filter.value; applyFilter(); } },
    el("option", { value: "" }, "All kinds"), ...Object.entries(KIND_NAMES).map(([k, name]) => el("option", { value: k }, name)));
  filter.value = kindFilter;
  applyFilter();
  return el("div", { class: "notes-page" }, el("h2", {}, "Notes"), el("label", {}, "Show ", filter),
    el("table", { class: "sheet notes" },
      el("thead", {}, el("tr", {}, ...["Plan", "Benefit", "Value", "Kind", "Note", "Links"].map((h) => el("th", {}, h)))),
      el("tbody", {}, ...rows)));
}

function noteRow(sheet, plan, column, cell) {
  const { doc, page, kind } = cell.comment;
  const cellHash = format({ year: site.year, view: sheet, plan: plan.plan_id, sheet, column: column.id });
  const value = valueCell(sheet, plan, column, cell);
  return el("tr", { "data-plan": plan.plan_id, "data-kind": kind },
    el("th", {}, planLink(plan), el("small", {}, plan.plan_id)),
    el("td", { class: "text" }, column.label),
    value,
    el("td", { class: "text" }, KIND_NAMES[kind]),
    el("td", { class: "text comment-text" }, ...commentText(plan, column, cell)),
    el("td", { class: "text links" },
      el("a", { href: "#", onclick: clicked(() => {
        pick(value);
        openCell(plan, column, cell, { kind: site.docs[doc].kind, page });
      }) }, `${site.docs[doc].kind} page ${page}`),
      el("br"),
      el("a", { href: cellHash, onclick: (e) => { if (location.hash === cellHash) { e.preventDefault(); route(); } } },
        `Show in ${SHEET_NAMES[sheet]}`)));
}

function planPage(plan) {
  const docRows = plan.docs.map((id) => {
    const d = site.docs[id];
    return el("tr", {},
      el("td", {}, el("a", { href: "#", onclick: clicked(() => { unpick(); openDoc(id, 1, null, null); }) }, kindName(d.kind))),
      el("td", {}, `${d.pages} pages`),
      el("td", {}, el("a", { href: d.url, target: "_blank", rel: "noopener" }, "carrier's copy ↗")));
  });
  const facts = [
    ["Plan ID", plan.plan_id], ["Organization", plan.organization], ["Type", plan.plan_type],
    ["Star rating", plan.overall_star_rating], ["Part D deductible", plan.part_d_deductible],
    ["Chronic conditions (C-SNP)", plan.c_snp_conditions.replace(/([a-z])([A-Z])/g, "$1 $2").replaceAll(",", ", ")],
    ["Medicare Plan Finder", newTab(plan.plan_finder_url, "View this plan on Medicare.gov ↗")],
  ];
  return el("div", { class: "plan-page" },
    el("h2", {}, plan.plan_name),
    el("dl", {}, ...facts.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)])),
    el("h3", {}, "Plan documents"), el("table", { class: "docs" }, el("tbody", {}, ...docRows)),
    ...Object.keys(SHEET_NAMES).map((sheet) => benefitTable(sheet, plan)));
}

function benefitTable(name, plan) {
  const sheet = site[name];
  const row = sheet.rows.find((r) => r.plan_id === plan.plan_id);
  return el("section", {}, el("h3", {}, SHEET_NAMES[name]), el("table", { class: "benefits" }, el("tbody", {},
    ...sheet.columns.map((c) => el("tr", {}, el("th", {}, c.label), valueCell(name, plan, c, row.cells[c.key]))))));
}

const kindName = (k) => ({ SB: "Summary of Benefits", EOC: "Evidence of Coverage", RIDER: "Optional rider" })[k] || k;

const viewer = {
  showing: null, page: null, doc: null, loading: null, pdf: null, sizes: [], cite: null, quotes: [], target: null, anchor: null, width: 0,
  texts: null, searchRun: null, hits: [], hit: -1,
};
const area = () => $("#page-area");
const holders = () => [...area().querySelectorAll(".page")];

// Scrolls to the quote on page, and highlights it along with any other quotes in the same document.
async function openDoc(docId, page, quote, note, otherQuotes = []) {
  const doc = site.docs[docId];
  if (viewer.doc !== docId) closeFind();
  viewer.showing = docId;
  viewer.page = page;
  $("#viewer").hidden = false;
  updateUrl();
  markOpenPlans();
  $("#doc-title").textContent = `${kindName(doc.kind)} · ${doc.plan_ids.map((p) => plans[p]?.plan_name || p).join("; ")}`;
  $("#doc-source").href = doc.url;
  $("#source-note").replaceChildren(...(note ? [note] : []));
  viewer.cite = quote ? { page, quote } : null;
  viewer.quotes = [viewer.cite, ...otherQuotes.filter((q) => q.doc === docId)].filter(Boolean);
  if (viewer.doc !== docId) {
    viewer.doc = docId;
    viewer.pdf = null;
    area().replaceChildren(el("p", { class: "notice" }, "Loading…"));
    $("#page-count").textContent = "";
    viewer.loading = loadSizes(doc.file);
  }
  let loaded;
  try {
    loaded = await viewer.loading;
  } catch {
    if (viewer.doc !== docId) return;
    viewer.doc = null;
    area().replaceChildren(el("p", { class: "notice" }, "This document failed to load. ",
      el("a", { href: doc.url, target: "_blank", rel: "noopener" }, "Open the carrier's copy ↗")));
    return;
  }
  const { pdf, sizes } = loaded;
  if (viewer.doc !== docId) return;
  if (viewer.pdf !== pdf) {
    viewer.pdf = pdf;
    viewer.sizes = sizes;
    layoutPages();
  } else {
    holders().forEach(markPage);
  }
  goTo(page, "cite");
}

async function loadSizes(file) {
  const pdf = await pdfjsLib.getDocument(file).promise;
  const pages = await Promise.all(Array.from({ length: pdf.numPages }, (_, i) => pdf.getPage(i + 1)));
  return { pdf, sizes: pages.map((p) => p.getViewport({ scale: 1 })) };
}

// Each page gets an empty box of its final size, so scroll positions are stable while pages render.
// Pages fit the pane at 100% zoom and grow with browser zoom, like the page's text.
// Chrome and Firefox report the zoom as the ratio of the window's width to the page's width.
const browserZoom = () => Math.max(1, Math.round((window.outerWidth / window.innerWidth) * 20) / 20 || 1);

function layoutPages() {
  viewer.width = area().clientWidth;
  const width = (viewer.width - 24) * browserZoom();
  pageObserver.disconnect();
  area().replaceChildren(...viewer.sizes.map((size, i) => {
    const holder = el("div", { class: "page", "data-page": i + 1 });
    holder.style.width = `${width}px`;
    holder.style.height = `${(size.height * width) / size.width}px`;
    return holder;
  }));
  holders().forEach((h) => pageObserver.observe(h));
  $("#page-count").textContent = `of ${viewer.sizes.length}`;
}

// focus is "cite" or "find" to scroll to the cited quote or the current search match once the page renders.
function goTo(n, focus = null) {
  const all = holders();
  if (!viewer.pdf || !all.length) return;
  n = Math.min(Math.max(1, n || 1), all.length);
  viewer.target = { n, focus };
  viewer.page = n;
  updateUrl();
  const holder = all[n - 1];
  area().scrollTop = holder.offsetTop - 12;
  $("#page").value = n;
  if (holder.text) arrive(holder);
  else renderPage(holder);
}

function currentPage() {
  const line = area().scrollTop + area().clientHeight / 3;
  const all = holders();
  const i = all.findIndex((h) => h.offsetTop + h.offsetHeight > line);
  return i < 0 ? all.length : i + 1;
}

// The point at the middle of the view, as a page and a fraction of its height, so a resize can keep it there.
function centerAnchor() {
  const line = area().scrollTop + area().clientHeight / 2;
  const holder = holders().find((h) => h.offsetTop + h.offsetHeight > line) || holders().at(-1);
  return { n: Number(holder.dataset.page), frac: (line - holder.offsetTop) / holder.offsetHeight };
}

function restoreAnchor({ n, frac }) {
  const holder = holders()[n - 1];
  if (holder) area().scrollTop = holder.offsetTop + frac * holder.offsetHeight - area().clientHeight / 2;
}

function onVisible(entries) {
  for (const { target: holder, isIntersecting } of entries) {
    if (isIntersecting) renderPage(holder);
    else {
      holder.generation = (holder.generation || 0) + 1;
      holder.task?.cancel();
      holder.rendering = holder.text = holder.task = null;
      holder.replaceChildren();
    }
  }
}

function renderPage(holder) {
  const generation = holder.generation;
  holder.rendering ||= drawPage(holder).catch(() => {
    if (generation === holder.generation) holder.rendering = null;
  });
}

async function drawPage(holder) {
  const generation = holder.generation;
  const n = Number(holder.dataset.page);
  const page = await viewer.pdf.getPage(n);
  const viewport = page.getViewport({ scale: holder.clientWidth / page.getViewport({ scale: 1 }).width });
  const ratio = window.devicePixelRatio || 1;
  const canvas = el("canvas");
  canvas.width = Math.floor(viewport.width * ratio);
  canvas.height = Math.floor(viewport.height * ratio);
  canvas.style.width = `${viewport.width}px`;
  canvas.style.height = `${viewport.height}px`;
  const text = el("div", { class: "textLayer" });
  holder.style.setProperty("--scale-factor", viewport.scale);
  holder.task = page.render({ canvasContext: canvas.getContext("2d"), viewport, transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : null });
  await holder.task.promise;
  const content = await page.getTextContent();
  const layer = new pdfjsLib.TextLayer({ textContentSource: content, container: text, viewport });
  await layer.render();
  if (generation !== holder.generation) return;
  holder.replaceChildren(canvas, text);
  holder.text = { divs: layer.textDivs, items: content.items.filter((i) => "str" in i) };
  markPage(holder);
  arrive(holder);
}

// Finishes a goTo once its page has rendered.
function arrive(holder) {
  const target = viewer.target;
  if (!holder.isConnected || target?.n !== Number(holder.dataset.page)) return;
  viewer.target = null;
  area().dataset.shown = `${viewer.doc} ${target.n}`;
  if (target.focus === "find") holder.querySelector("mark.current")?.scrollIntoView({ block: "center" });
  if (target.focus !== "cite" || viewer.cite?.page !== target.n) return;
  const mark = holder.querySelector("mark.cite");
  if (mark) mark.scrollIntoView({ block: "center" });
  else $("#source-note").append(el("p", { class: "warn" }, "Could not find the quoted text on this page."));
}

function markPage(holder) {
  if (!holder.text) return;
  const { divs, items } = holder.text;
  const n = Number(holder.dataset.page);
  const strs = items.map((i) => i.str);
  const lefts = items.map((i) => i.transform[4]);
  const quotes = new Set(viewer.quotes.filter((q) => q.page === n).map((q) => q.quote));
  const marks = [...quotes].flatMap((q) => matchRanges(strs, q, lefts).map((r) => ({ ...r, cls: "cite" })));
  viewer.hits.forEach((h, i) => {
    if (h.page === n) marks.push(...h.ranges.map((r) => ({ ...r, cls: i === viewer.hit ? "found current" : "found" })));
  });
  divs.forEach((d, i) => d.replaceChildren(...markText(strs[i], marks.filter((m) => m.item === i))));
}

// Splits s at every mark's edges, wrapping each piece that a mark covers in a <mark> with the covering marks' classes.
function markText(s, marks) {
  const cuts = [...new Set([0, s.length, ...marks.flatMap((m) => [m.start, m.end])])].sort((a, b) => a - b);
  return cuts.slice(1).map((end, i) => {
    const start = cuts[i];
    const over = marks.filter((m) => m.start < end && m.end > start);
    return over.length ? el("mark", { class: over.map((m) => m.cls).join(" ") }, s.slice(start, end)) : s.slice(start, end);
  });
}

function openFind() {
  if (!viewer.pdf) return;
  $("#find").hidden = false;
  $("#find-query").select();
  $("#find-query").focus();
}

function closeFind() {
  $("#find").hidden = true;
  $("#find").contains(document.activeElement) && document.activeElement.blur();
  $("#find-count").textContent = "";
  viewer.searchRun = null;
  viewer.hits = [];
  viewer.hit = -1;
  holders().forEach(markPage);
}

function pageTexts() {
  const pdf = viewer.pdf;
  if (viewer.texts?.pdf !== pdf) {
    viewer.texts = { pdf, items: Promise.all(Array.from({ length: pdf.numPages }, async (_, i) => {
      const items = (await (await pdf.getPage(i + 1)).getTextContent()).items.filter((item) => "str" in item);
      return { strs: items.map((item) => item.str), lefts: items.map((item) => item.transform[4]) };
    })) };
    viewer.texts.items.catch(() => (viewer.texts = null));
  }
  return viewer.texts.items;
}

// Finds the query on every page and moves to the first match at or after the current match's page, or else the shown page.
async function search() {
  const query = $("#find-query").value;
  const run = (viewer.searchRun = {});
  let hits = [];
  if (squash(query)) {
    $("#find-count").textContent = "Searching…";
    const texts = await pageTexts().catch(() => null);
    if (viewer.searchRun !== run) return;
    if (!texts) {
      $("#find-count").textContent = "Search failed";
      return;
    }
    hits = texts.flatMap(({ strs, lefts }, i) => findAll(strs, query, lefts).map((ranges) => ({ page: i + 1, ranges })));
  }
  const from = viewer.hits[viewer.hit]?.page ?? currentPage();
  viewer.hits = hits;
  viewer.hit = hits.length ? Math.max(0, hits.findIndex((h) => h.page >= from)) : -1;
  showHit();
}

function step(by) {
  if (!viewer.hits.length) return search();
  viewer.hit = (viewer.hit + by + viewer.hits.length) % viewer.hits.length;
  showHit();
}

function showHit() {
  const { hits, hit } = viewer;
  $("#find-count").textContent = hits.length ? `${hit + 1} of ${hits.length}` : squash($("#find-query").value) ? "No matches" : "";
  holders().forEach(markPage);
  if (hit >= 0) goTo(hits[hit].page, "find");
}

function closeViewer() {
  hideViewer();
  updateUrl();
}

function hideViewer() {
  $("#viewer").hidden = true;
  delete area().dataset.shown;
  closeFind();
  unpick();
  markOpenPlans();
}

function markOpenPlans() {
  const open = $("#viewer").hidden || !viewer.showing ? [] : site.docs[viewer.showing].plan_ids;
  document.querySelectorAll("tr[data-plan]").forEach((tr) => tr.classList.toggle("open-plan", open.includes(tr.dataset.plan)));
}

start();
