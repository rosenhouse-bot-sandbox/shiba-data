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
let plans;

async function start() {
  site = await (await fetch("data.json")).json();
  plans = Object.fromEntries(site.plans.map((p) => [p.plan_id, p]));
  const picker = $("#plan-picker");
  for (const p of site.plans) picker.append(el("option", { value: p.plan_id }, p.plan_name));
  picker.addEventListener("change", () => {
    if (picker.value) location.hash = `#/plan/${picker.value}`;
  });
  $("#prev").addEventListener("click", () => showPage(viewer.page - 1));
  $("#next").addEventListener("click", () => showPage(viewer.page + 1));
  $("#page").addEventListener("change", (e) => showPage(Number(e.target.value)));
  $("#close").addEventListener("click", closeViewer);
  window.addEventListener("hashchange", route);
  new ResizeObserver(() => viewer.pending ? showPage(...viewer.pending) : showPage(viewer.page)).observe($("#page-area"));
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
    class: [cell.cites.length ? "cited" : "", /^[●◐]$/.test(cell.value) ? "dot" : ""].join(" "),
    title: cell.cites.length ? "Click to see the plan document page" : "From CMS plan data. Click to open the plan's Summary of Benefits.",
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
  const what = `${plan.plan_name}: ${column.label} = ${oneLine(cell.value)}`;
  if (cell.cites.length) {
    const cite = cell.cites[0];
    openDoc(cite.doc, cite.page, cite.quote, citeNote(what, cell));
  } else {
    const sb = plan.docs.find((d) => site.docs[d].kind === "SB");
    openDoc(sb, 1, null, el("div", {}, el("b", {}, what), el("p", {},
      cell.value ? "This value comes from the CMS 2027 Plan Benefit Package data, which has no page to point to. "
        : "The CMS 2027 Plan Benefit Package data has no entry for this benefit. ",
      "The plan's Summary of Benefits is shown for reference.")));
  }
}

const oneLine = (value) => value.split(" | ").join("; ");

function citeNote(what, cell) {
  const note = el("div", {}, el("b", {}, what));
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

const viewer = { doc: null, loading: null, pdf: null, page: 1, cite: null, renderId: 0, pending: null };

async function openDoc(docId, page, quote, note) {
  const doc = site.docs[docId];
  $("#viewer").hidden = false;
  $("#doc-title").textContent = `${kindName(doc.kind)} · ${doc.plan_ids.map((p) => plans[p]?.plan_name || p).join("; ")}`;
  $("#doc-source").href = doc.url;
  $("#source-note").replaceChildren(...[note, doc.changed ? el("p", { class: "warn" },
    "The carrier has changed this file since the data was extracted. Page numbers may be off.") : null].filter(Boolean));
  viewer.cite = quote ? { page, quote } : null;
  viewer.renderId++;
  if (!doc.file) {
    viewer.doc = viewer.pdf = null;
    $("#page-area").replaceChildren(el("p", { class: "missing" }, "No copy of this document is hosted here. ",
      el("a", { href: doc.url, target: "_blank", rel: "noopener" }, "Open the carrier's copy ↗")));
    return;
  }
  if (viewer.doc !== docId) {
    viewer.doc = docId;
    viewer.pdf = null;
    viewer.loading = pdfjsLib.getDocument(doc.file).promise;
  }
  const pdf = await viewer.loading;
  if (viewer.doc !== docId) return;
  viewer.pdf = pdf;
  $("#page-count").textContent = `of ${pdf.numPages}`;
  showPage(page, true);
}

function closeViewer() {
  $("#viewer").hidden = true;
  document.querySelectorAll(".selected").forEach((s) => s.classList.remove("selected"));
}

async function showPage(n, scrollToCite = false) {
  const { pdf, doc } = viewer;
  if (!pdf) return;
  n = Math.min(Math.max(1, n || 1), pdf.numPages);
  const id = ++viewer.renderId;
  viewer.pending = [n, scrollToCite];
  const page = await pdf.getPage(n);
  const area = $("#page-area");
  const base = page.getViewport({ scale: 1 });
  const viewport = page.getViewport({ scale: (area.clientWidth - 24) / base.width });
  const ratio = window.devicePixelRatio || 1;
  const canvas = el("canvas");
  canvas.width = Math.floor(viewport.width * ratio);
  canvas.height = Math.floor(viewport.height * ratio);
  canvas.style.width = `${viewport.width}px`;
  canvas.style.height = `${viewport.height}px`;
  const text = el("div", { class: "textLayer" });
  const holder = el("div", { class: "page" }, canvas, text);
  holder.style.setProperty("--scale-factor", viewport.scale);
  holder.style.width = `${viewport.width}px`;
  holder.style.height = `${viewport.height}px`;

  await page.render({ canvasContext: canvas.getContext("2d"), viewport, transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : null }).promise;
  const content = await page.getTextContent();
  const layer = new pdfjsLib.TextLayer({ textContentSource: content, container: text, viewport });
  await layer.render();
  if (id !== viewer.renderId || pdf !== viewer.pdf) return;
  viewer.pending = null;
  viewer.page = n;
  $("#page").value = n;
  area.replaceChildren(holder);
  area.dataset.shown = `${doc} ${n}`;
  if (viewer.cite?.page === n) {
    const mark = highlight(layer.textDivs, content.items.filter((i) => "str" in i), viewer.cite.quote);
    if (!scrollToCite) return;
    if (mark) mark.scrollIntoView({ block: "center" });
    else $("#source-note").append(el("p", { class: "warn" }, "Could not find the quoted text on this page."));
  } else if (scrollToCite) {
    area.scrollTop = 0;
  }
}

function highlight(divs, items, quote) {
  let first = null;
  for (const { item, start, end } of matchRanges(items.map((i) => i.str), quote)) {
    const div = divs[item];
    const s = items[item].str;
    const mark = el("mark", {}, s.slice(start, end));
    div.replaceChildren(s.slice(0, start), mark, s.slice(end));
    first ||= mark;
  }
  return first;
}

start();
