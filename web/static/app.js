import * as pdfjsLib from "https://cdn.jsdelivr.net/npm/pdfjs-dist@4.10.38/build/pdf.min.mjs";
import { matchRanges } from "./highlight.js";

pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4.10.38/build/pdf.worker.min.mjs";

const SHEET_NAMES = { main: "Main chart", dvha: "Dental, vision, hearing & extras" };
const SECTIONS = {
  "MA-PD": "Medicare Advantage with drug coverage",
  "NO-PART-D": "Medicare Advantage without drug coverage",
  "C-SNP": "Chronic condition special needs plans",
};
const $ = (sel) => document.querySelector(sel);
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  e.append(...kids.filter((k) => k != null));
  return e;
};

// Keep in sync with PAGE_REF in web/build.py.
const PAGE_REF = /\b(EOC|SB|rider) pages? (\d+)/gi;

let site;
let pageObserver;
let plans;
const scrollTops = {};
let shownHash;

async function start() {
  site = await (await fetch("data.json")).json();
  plans = Object.fromEntries(site.plans.map((p) => [p.plan_id, p]));
  $("#prev").addEventListener("click", () => goTo(currentPage() - 1));
  $("#next").addEventListener("click", () => goTo(currentPage() + 1));
  $("#page").addEventListener("change", (e) => goTo(Number(e.target.value)));
  $("#close").addEventListener("click", closeViewer);
  window.addEventListener("hashchange", route);
  pageObserver = new IntersectionObserver(onVisible, { root: area(), rootMargin: "1500px 0px" });
  area().addEventListener("scroll", () => {
    if (!holders().length) return;
    if (document.activeElement !== $("#page")) $("#page").value = currentPage();
    viewer.anchor = centerAnchor();
  });
  new ResizeObserver(() => {
    if (!viewer.pdf || !area().clientWidth) return;
    if (area().clientWidth !== viewer.width) layoutPages();
    if (viewer.target) goTo(viewer.target.n, viewer.target.toCite);
    else if (viewer.anchor) restoreAnchor(viewer.anchor);
  }).observe(area());
  route();
}

function route() {
  const [, view, id, col] = location.hash.split("/");
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === (view || "main")));
  const content = $("#content");
  if (shownHash !== undefined) scrollTops[shownHash] = content.scrollTop;
  shownHash = location.hash;
  if (view === "ambiguities") content.replaceChildren(ambiguitiesView());
  else if (view === "plan" && plans[id]) content.replaceChildren(planPage(plans[id]));
  else content.replaceChildren(sheetView(site[view === "dvha" ? "dvha" : "main"]));
  content.scrollTop = scrollTops[location.hash] ?? 0;
  markOpenPlans();
  if (view !== "plan" && id) content.querySelector(`td[data-plan="${CSS.escape(id)}"][data-col="${CSS.escape(col ?? "")}"]`)?.click();
  if (view === "plan" && plans[id] && ($("#viewer").hidden || !site.docs[viewer.showing].plan_ids.includes(id))) {
    openDoc(plans[id].docs.find((d) => site.docs[d].kind === "SB"), 1, null, null);
  }
}

function sheetView(sheet) {
  const table = el("table", { class: "sheet" });
  table.append(el("thead", {}, el("tr", {}, el("th", { class: "plan" }, "Plan"),
    ...sheet.columns.map((c) => el("th", {}, c.label)))));
  const body = el("tbody");
  let section;
  for (const row of sheet.rows) {
    if (row.section !== section) {
      section = row.section;
      body.append(el("tr", { class: "section" }, el("th", { colspan: sheet.columns.length + 1 }, SECTIONS[section] || section)));
    }
    const plan = plans[row.plan_id];
    body.append(el("tr", { "data-plan": row.plan_id },
      el("th", { class: "plan" }, el("a", { href: `#/plan/${row.plan_id}` }, plan.plan_name), el("small", {}, row.plan_id)),
      ...sheet.columns.map((c) => valueCell(plan, c, row.cells[c.key]))));
  }
  table.append(body);
  return el("div", { class: "sheet-wrap" }, table);
}

function valueCell(plan, column, cell) {
  const td = el("td", {
    "data-plan": plan.plan_id,
    "data-col": column.key,
    class: [cell.cites.length ? "cited" : "", cell.comment ? "commented" : "", /^[●◐]$/.test(cell.value) ? "dot" : ""].join(" "),
    title: cell.comment?.text || (cell.cites.length ? "Click to see the plan document page" : "From CMS plan data. Click to open the plan's Summary of Benefits."),
    onclick: () => {
      document.querySelectorAll(".selected").forEach((s) => s.classList.remove("selected"));
      td.classList.add("selected");
      openCell(plan, column, cell);
      td.scrollIntoView({ block: "nearest", inline: "nearest" });
    },
  });
  cell.value.split(" | ").forEach((line, i) => td.append(i ? el("br") : "", line));
  return td;
}

const cellHeader = (plan, column, cell) => el("div", {}, el("b", {}, `${plan.plan_name}: ${column.label} = ${oneLine(cell.value)}`),
  cell.comment ? el("p", { class: "comment" }, ...commentText(plan, column, cell)) : null);

// Links each "EOC page N" in a comment to page N of the plan's document of that kind.
function commentText(plan, column, cell) {
  const { text } = cell.comment;
  const parts = [];
  let at = 0;
  for (const ref of text.matchAll(PAGE_REF)) {
    const doc = plan.docs.find((d) => site.docs[d].kind === ref[1].toUpperCase());
    parts.push(text.slice(at, ref.index), el("a", {
      href: "#",
      onclick: (e) => {
        e.preventDefault();
        const note = e.target.closest("#source-note") ? $("#source-note").firstElementChild : el("div", {}, cellHeader(plan, column, cell));
        openDoc(doc, Number(ref[2]), null, note);
      },
    }, ref[0]));
    at = ref.index + ref[0].length;
  }
  parts.push(text.slice(at));
  return parts;
}

const commentSource = (cell, note) => {
  const { doc, page, quote } = cell.comment;
  return el("p", { class: "comment-source" }, "Comment source: ",
    el("a", { href: "#", onclick: (e) => { e.preventDefault(); openDoc(doc, page, quote, note); } }, `${site.docs[doc].kind} page ${page}`),
    `: “${quote}”`);
};

function openComment(plan, column, cell) {
  const note = el("div", {}, cellHeader(plan, column, cell));
  note.append(commentSource(cell, note), el("p", {}, planFinderLink(plan)));
  openDoc(cell.comment.doc, cell.comment.page, cell.comment.quote, note);
}

function openCell(plan, column, cell) {
  const header = cellHeader(plan, column, cell);
  if (cell.cites.length) {
    const cite = cell.cites[0];
    const note = citeNote(header, cell);
    note.append(el("p", {}, planFinderLink(plan)));
    openDoc(cite.doc, cite.page, cite.quote, note, cell.cites);
  } else if (cell.comment) {
    openComment(plan, column, cell);
  } else {
    const sb = plan.docs.find((d) => site.docs[d].kind === "SB");
    openDoc(sb, 1, null, el("div", {}, header, el("p", {},
      cell.value ? "This value comes from the CMS 2027 Plan Benefit Package data, which has no page to point to. "
        : "The CMS 2027 Plan Benefit Package data has no entry for this benefit. ",
      "The plan's Summary of Benefits is shown for reference."), el("p", {}, planFinderLink(plan))));
  }
}

const planFinderLink = (plan) => el("a", { href: plan.plan_finder_url, target: "_blank", rel: "noopener" }, "View this plan on Medicare.gov ↗");

const oneLine = (value) => value.split(" | ").join("; ");

function citeNote(header, cell) {
  const note = el("div", {}, header);
  if (!cell.value) note.append(el("p", {}, "The plan document shows the plan does not cover this as a routine benefit:"));
  cell.cites.forEach((c, i) => {
    const doc = site.docs[c.doc];
    note.append(el("p", { class: "cite" },
      el("a", { href: "#", onclick: (e) => { e.preventDefault(); openDoc(c.doc, c.page, c.quote, note, cell.cites); } },
        `${doc.kind} page ${c.page}`),
      c.line ? ` (line ${c.line})` : "", `: “${c.quote}”`));
  });
  if (cell.comment) note.append(commentSource(cell, note));
  if (cell.pbp != null) {
    note.append(el("p", { class: "pbp" }, cell.pbp ? `CMS plan data says “${oneLine(cell.pbp)}”. The plan document overrides it.`
      : "CMS plan data leaves this blank. The plan document fills it in."));
  }
  return note;
}

function ambiguitiesView() {
  const rows = Object.keys(SHEET_NAMES).flatMap((sheet) => site[sheet].rows.flatMap((r) =>
    site[sheet].columns.filter((c) => r.cells[c.key].comment).map((c) => ambiguityRow(sheet, plans[r.plan_id], c, r.cells[c.key]))));
  return el("div", { class: "ambiguities-page" }, el("h2", {}, "Ambiguities"),
    el("table", { class: "sheet ambiguities" },
      el("thead", {}, el("tr", {}, ...["Plan", "Benefit", "Value", "Comment", "Links"].map((h) => el("th", {}, h)))),
      el("tbody", {}, ...rows)));
}

function ambiguityRow(sheet, plan, column, cell) {
  const { doc, page } = cell.comment;
  const cellHash = `#/${sheet}/${plan.plan_id}/${column.key}`;
  return el("tr", { "data-plan": plan.plan_id },
    el("th", {}, el("a", { href: `#/plan/${plan.plan_id}` }, plan.plan_name), el("small", {}, plan.plan_id)),
    el("td", { class: "text" }, column.label),
    valueCell(plan, column, cell),
    el("td", { class: "text comment-text" }, ...commentText(plan, column, cell)),
    el("td", { class: "text links" },
      el("a", { href: "#", onclick: (e) => { e.preventDefault(); openComment(plan, column, cell); } }, `${site.docs[doc].kind} page ${page}`),
      el("br"),
      el("a", { href: cellHash, onclick: (e) => { if (location.hash === cellHash) { e.preventDefault(); route(); } } },
        `Show in ${SHEET_NAMES[sheet]}`)));
}

function planPage(plan) {
  const docRows = plan.docs.map((id) => {
    const d = site.docs[id];
    return el("tr", {},
      el("td", {}, el("a", { href: "#", onclick: (e) => { e.preventDefault(); openDoc(id, 1, null, null); } }, kindName(d.kind))),
      el("td", {}, `${d.pages} pages`),
      el("td", {}, d.retrieved ? `copied ${d.retrieved}` : "not copied"),
      el("td", {}, el("a", { href: d.url, target: "_blank", rel: "noopener" }, "carrier's copy ↗")),
      el("td", { class: "warn" }, d.changed ? "The carrier has changed this file since the data was extracted." : ""));
  });
  const facts = [
    ["Plan ID", plan.plan_id], ["Organization", plan.organization], ["Type", plan.plan_type],
    ["Star rating", plan.overall_star_rating], ["Part D deductible", plan.part_d_deductible],
    ["Chronic conditions (C-SNP)", plan.c_snp_conditions.replace(/([a-z])([A-Z])/g, "$1 $2").replaceAll(",", ", ")],
    ["Medicare Plan Finder", planFinderLink(plan)],
  ];
  return el("div", { class: "plan-page" },
    el("h2", {}, plan.plan_name),
    el("dl", {}, ...facts.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)])),
    el("h3", {}, "Plan documents"), el("table", { class: "docs" }, el("tbody", {}, ...docRows)),
    ...Object.keys(SHEET_NAMES).map((sheet) => benefitTable(SHEET_NAMES[sheet], site[sheet], plan)));
}

function benefitTable(title, sheet, plan) {
  const row = sheet.rows.find((r) => r.plan_id === plan.plan_id);
  return el("section", {}, el("h3", {}, title), el("table", { class: "benefits" }, el("tbody", {},
    ...sheet.columns.map((c) => el("tr", {}, el("th", {}, c.label), valueCell(plan, c, row.cells[c.key]))))));
}

const kindName = (k) => ({ SB: "Summary of Benefits", EOC: "Evidence of Coverage", RIDER: "Optional rider" })[k] || k;

const viewer = { showing: null, doc: null, loading: null, pdf: null, sizes: [], cite: null, quotes: [], target: null, anchor: null, width: 0 };
const area = () => $("#page-area");
const holders = () => [...area().querySelectorAll(".page")];

// Scrolls to the quote on page, and highlights it along with any other quotes in the same document.
async function openDoc(docId, page, quote, note, otherQuotes = []) {
  const doc = site.docs[docId];
  viewer.showing = docId;
  $("#viewer").hidden = false;
  markOpenPlans();
  $("#doc-title").textContent = `${kindName(doc.kind)} · ${doc.plan_ids.map((p) => plans[p]?.plan_name || p).join("; ")}`;
  $("#doc-source").href = doc.url;
  $("#source-note").replaceChildren(...[note, doc.changed ? el("p", { class: "warn" },
    "The carrier has changed this file since the data was extracted. Page numbers may be off.") : null].filter(Boolean));
  viewer.cite = quote ? { page, quote } : null;
  viewer.quotes = [viewer.cite, ...otherQuotes.filter((q) => q.doc === docId)].filter(Boolean);
  if (!doc.file) {
    viewer.doc = viewer.pdf = null;
    area().replaceChildren(el("p", { class: "notice" }, "No copy of this document is hosted here. ",
      el("a", { href: doc.url, target: "_blank", rel: "noopener" }, "Open the carrier's copy ↗")));
    return;
  }
  if (viewer.doc !== docId) {
    viewer.doc = docId;
    viewer.pdf = null;
    area().replaceChildren(el("p", { class: "notice" }, "Loading…"));
    $("#page-count").textContent = "";
    viewer.loading = loadSizes(doc.file);
  }
  const { pdf, sizes } = await viewer.loading;
  if (viewer.doc !== docId) return;
  if (viewer.pdf !== pdf) {
    viewer.pdf = pdf;
    viewer.sizes = sizes;
    layoutPages();
  } else {
    holders().forEach(markPage);
  }
  goTo(page, true);
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

function goTo(n, toCite = false) {
  const all = holders();
  if (!viewer.pdf || !all.length) return;
  n = Math.min(Math.max(1, n || 1), all.length);
  viewer.target = { n, toCite };
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
  if (!target.toCite || viewer.cite?.page !== target.n) return;
  const mark = holder.querySelector("mark");
  if (mark) mark.scrollIntoView({ block: "center" });
  else $("#source-note").append(el("p", { class: "warn" }, "Could not find the quoted text on this page."));
}

function markPage(holder) {
  if (!holder.text) return;
  const { divs, items } = holder.text;
  divs.forEach((d, i) => (d.textContent = items[i].str));
  const quotes = viewer.quotes.filter((q) => q.page === Number(holder.dataset.page)).map((q) => q.quote);
  highlight(divs, items, [...new Set(quotes)]);
}

function closeViewer() {
  $("#viewer").hidden = true;
  document.querySelectorAll(".selected").forEach((s) => s.classList.remove("selected"));
  markOpenPlans();
}

function markOpenPlans() {
  const open = $("#viewer").hidden || !viewer.showing ? [] : site.docs[viewer.showing].plan_ids;
  document.querySelectorAll("tr[data-plan]").forEach((tr) => tr.classList.toggle("open-plan", open.includes(tr.dataset.plan)));
}

function highlight(divs, items, quotes) {
  const strs = items.map((i) => i.str);
  const lefts = items.map((i) => i.transform[4]);
  const byItem = new Map();
  for (const quote of quotes) {
    for (const r of matchRanges(strs, quote, lefts)) byItem.set(r.item, [...(byItem.get(r.item) ?? []), r]);
  }
  for (const [item, ranges] of byItem) {
    const s = strs[item];
    const parts = [];
    let at = 0;
    for (const { start, end } of ranges.sort((a, b) => a.start - b.start)) {
      if (start < at) continue;
      parts.push(s.slice(at, start), el("mark", {}, s.slice(start, end)));
      at = end;
    }
    divs[item].replaceChildren(...parts, s.slice(at));
  }
}

start();
