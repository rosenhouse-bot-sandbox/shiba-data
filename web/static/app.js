import * as pdfjsLib from "https://cdn.jsdelivr.net/npm/pdfjs-dist@4.10.38/build/pdf.min.mjs";
import { matchRanges } from "./highlight.js";

pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4.10.38/build/pdf.worker.min.mjs";

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

let site;
let pageObserver;
let plans;

async function start() {
  site = await (await fetch("data.json")).json();
  plans = Object.fromEntries(site.plans.map((p) => [p.plan_id, p]));
  const picker = $("#plan-picker");
  for (const p of site.plans) picker.append(el("option", { value: p.plan_id }, p.plan_name));
  picker.addEventListener("change", () => {
    if (picker.value) location.hash = `#/plan/${picker.value}`;
  });
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
  const [, view, id] = location.hash.split("/");
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === (view || "main")));
  $("#plan-picker").value = view === "plan" ? id : "";
  const content = $("#content");
  content.replaceChildren(view === "plan" && plans[id] ? planPage(plans[id]) : sheetView(site[view === "dvha" ? "dvha" : "main"]));
  content.scrollTop = 0;
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
    body.append(el("tr", {},
      el("th", { class: "plan" }, el("a", { href: `#/plan/${row.plan_id}` }, plan.plan_name), el("small", {}, row.plan_id)),
      ...sheet.columns.map((c) => valueCell(plan, c, row.cells[c.key]))));
  }
  table.append(body);
  return el("div", { class: "sheet-wrap" }, table);
}

function valueCell(plan, column, cell) {
  const td = el("td", {
    class: [cell.cites.length ? "cited" : "", cell.comment ? "commented" : "", /^[●◐]$/.test(cell.value) ? "dot" : ""].join(" "),
    title: cell.comment || (cell.cites.length ? "Click to see the plan document page" : "From CMS plan data. Click to open the plan's Summary of Benefits."),
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

function openCell(plan, column, cell) {
  const header = el("div", {}, el("b", {}, `${plan.plan_name}: ${column.label} = ${oneLine(cell.value)}`),
    cell.comment ? el("p", { class: "comment" }, cell.comment) : null);
  if (cell.cites.length) {
    const cite = cell.cites[0];
    const note = citeNote(header, cell);
    note.append(el("p", {}, planFinderLink(plan)));
    openDoc(cite.doc, cite.page, cite.quote, note);
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
  cell.cites.forEach((c, i) => {
    const doc = site.docs[c.doc];
    note.append(el("p", {},
      el("a", { href: "#", onclick: (e) => { e.preventDefault(); openDoc(c.doc, c.page, c.quote, note); } },
        `${doc.kind} page ${c.page}`),
      c.line ? ` (line ${c.line})` : "", `: “${c.quote}”`));
  });
  if (cell.pbp != null) {
    note.append(el("p", { class: "pbp" }, cell.pbp ? `CMS plan data says “${oneLine(cell.pbp)}”. The plan document overrides it.`
      : "CMS plan data leaves this blank. The plan document fills it in."));
  }
  return note;
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
    benefitTable("Main chart", site.main, plan),
    benefitTable("Dental, vision, hearing & extras", site.dvha, plan));
}

function benefitTable(title, sheet, plan) {
  const row = sheet.rows.find((r) => r.plan_id === plan.plan_id);
  return el("section", {}, el("h3", {}, title), el("table", { class: "benefits" }, el("tbody", {},
    ...sheet.columns.map((c) => el("tr", {}, el("th", {}, c.label), valueCell(plan, c, row.cells[c.key]))))));
}

const kindName = (k) => ({ SB: "Summary of Benefits", EOC: "Evidence of Coverage", RIDER: "Optional rider" })[k] || k;

const viewer = { doc: null, loading: null, pdf: null, sizes: [], cite: null, target: null, anchor: null, width: 0 };
const area = () => $("#page-area");
const holders = () => [...area().querySelectorAll(".page")];

async function openDoc(docId, page, quote, note) {
  const doc = site.docs[docId];
  $("#viewer").hidden = false;
  $("#doc-title").textContent = `${kindName(doc.kind)} · ${doc.plan_ids.map((p) => plans[p]?.plan_name || p).join("; ")}`;
  $("#doc-source").href = doc.url;
  $("#source-note").replaceChildren(...[note, doc.changed ? el("p", { class: "warn" },
    "The carrier has changed this file since the data was extracted. Page numbers may be off.") : null].filter(Boolean));
  viewer.cite = quote ? { page, quote } : null;
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
function layoutPages() {
  viewer.width = area().clientWidth;
  const width = viewer.width - 24;
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
  if (viewer.cite?.page === Number(holder.dataset.page)) highlight(divs, items, viewer.cite.quote);
}

function closeViewer() {
  $("#viewer").hidden = true;
  document.querySelectorAll(".selected").forEach((s) => s.classList.remove("selected"));
}

function highlight(divs, items, quote) {
  for (const { item, start, end } of matchRanges(items.map((i) => i.str), quote)) {
    const div = divs[item];
    const s = items[item].str;
    div.replaceChildren(s.slice(0, start), el("mark", {}, s.slice(start, end)), s.slice(end));
  }
}

start();
