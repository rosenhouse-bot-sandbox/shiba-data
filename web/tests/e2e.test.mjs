// Drives the built site in Chromium. Usage: SITE=<build dir> DOCS=<dir of <sha256>.pdf> [FAILURES=<dir>] node --test web/tests/e2e.test.mjs
// With FAILURES, each failed test leaves a screenshot and the HTML of each of its pages there.
import { test, before, after, afterEach } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { chromium, devices } from "playwright";
import { NODES, STEPS, MIN_GAP, outputs } from "../static/pipeline.js";

const { SITE, DOCS, FAILURES } = process.env;
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json", ".pdf": "application/pdf" };
let server, browser, page, base;
let opened = [];

async function newPage(options) {
  const p = await browser.newPage(options);
  opened.push(p);
  return p;
}

const site = JSON.parse(fs.readFileSync(path.join(SITE, "data.json")));
// Like Cloudflare, which adds the headers that _headers lists for /* to every asset.
const [rule, ...headerLines] = fs.readFileSync(path.join(SITE, "_headers"), "utf8").trim().split("\n");
assert.equal(rule, "/*");
const HEADERS = Object.fromEntries(headerLines.map((l) => l.match(/^ {2}([\w-]+): (.+)$/).slice(1)));

before(async () => {
  server = http.createServer((req, res) => {
    const name = decodeURIComponent(new URL(req.url, "http://x").pathname);
    // Like the pdxplans Worker, which serves docs/ from R2 and each trace from its static file.
    const file = name.startsWith("/docs/") ? path.join(DOCS, path.basename(name))
      : name.startsWith("/trace/") ? path.join(SITE, `${name}.json`) : path.join(SITE, name.replace(/\/$/, "/index.html"));
    fs.readFile(file, (err, body) => {
      res.writeHead(err ? 404 : 200, { ...HEADERS, "Content-Type": TYPES[path.extname(file)] || "application/octet-stream" });
      res.end(body);
    });
  });
  await new Promise((r) => server.listen(0, r));
  base = `http://localhost:${server.address().port}/`;
  const proxy = process.env.HTTPS_PROXY ? { server: process.env.HTTPS_PROXY, bypass: "localhost" } : undefined;
  browser = await chromium.launch({ proxy });
  page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
});

afterEach(async (t) => {
  try {
    if (FAILURES && !t.passed) {
      fs.mkdirSync(FAILURES, { recursive: true });
      for (const [i, p] of [page, ...opened].filter((p) => !p.isClosed()).entries()) {
        const name = path.join(FAILURES, `${t.name.replace(/\W+/g, "-")}-${i}`);
        await p.screenshot({ path: `${name}.png`, timeout: 10000 }).catch(() => {});
        fs.writeFileSync(`${name}.html`, await p.content().catch((e) => String(e)));
      }
    }
  } finally {
    for (const p of opened) await p.close();
    opened = [];
  }
}, { timeout: 60000 });

after(async () => {
  await browser?.close();
  server?.close();
});

const shown = (doc, n) => page.waitForSelector(`#page-area[data-shown="${doc} ${n}"]`);
const docOf = (planId, kind) => Object.entries(site.docs).find(([, d]) => d.kind === kind && d.plan_ids.includes(planId))[0];
const row = (planId) => page.locator("table.sheet tr", { has: page.locator("small", { hasText: planId }) });
const UNCITED = "td:not(.cited):not(.commented)";

test("the header names the plan year and counties", async () => {
  await page.goto(`${base}#/main`);
  await page.waitForSelector("table.sheet");
  assert.equal(await page.title(), "Main chart – pdxplans.org – 2027 Medicare Advantage plans");
  assert.equal(await page.textContent("h1"), "pdxplans.org – 2027 Medicare Advantage plans for Multnomah & Clackamas");
});

test("the header links to the Google Sheet in a new tab", async () => {
  await page.goto(`${base}#/main`);
  await page.waitForSelector("table.sheet");
  const link = page.locator("#sheet-link");
  assert.equal(await link.getAttribute("href"), `https://docs.google.com/spreadsheets/d/${site.sheet_id}/edit`);
  assert.equal(await link.getAttribute("target"), "_blank");
  assert.equal((await link.textContent()).trim(), "View in Google Sheets ↗");
  assert.ok(await link.locator("svg").isVisible());
});

// The light page is white; the dark page is not.
const isDark = async (p) => (await p.evaluate(() => getComputedStyle(document.body).backgroundColor)) !== "rgb(255, 255, 255)";

async function openSheet(options) {
  const p = await newPage(options);
  await p.goto(`${base}#/main`);
  await p.waitForSelector("table.sheet");
  return p;
}

test("appearance follows the system by default, and the menu says which it is", async () => {
  const fresh = await openSheet({ colorScheme: "dark" });
  assert.ok(await isDark(fresh));
  await fresh.getByRole("button", { name: "Appearance" }).click();
  assert.ok(await fresh.getByRole("radio", { name: "System (dark)" }).isChecked());
  await fresh.emulateMedia({ colorScheme: "light" });
  assert.ok(await fresh.getByRole("radio", { name: "System (light)" }).isChecked());
  assert.ok(!await isDark(fresh));
});

test("a chosen appearance overrides the system and is remembered until System is chosen", async () => {
  const fresh = await openSheet({ colorScheme: "light" });
  const button = fresh.getByRole("button", { name: "Appearance" });
  await button.click();
  await fresh.getByRole("radio", { name: "Dark" }).check();
  assert.ok(await isDark(fresh));
  assert.ok(await button.locator(".moon").isVisible());
  assert.ok(!await button.locator(".sun").isVisible());
  await fresh.reload();
  await fresh.waitForSelector("table.sheet");
  assert.ok(await isDark(fresh));
  await button.click();
  assert.ok(await fresh.getByRole("radio", { name: "Dark" }).isChecked());
  await fresh.getByRole("radio", { name: /^System/ }).check();
  assert.ok(!await isDark(fresh));
  assert.equal(await fresh.evaluate(() => localStorage.getItem("color-scheme")), null);
});

test("an appearance chosen in one tab applies in the others", async () => {
  const context = await browser.newContext({ colorScheme: "light" });
  try {
    const [one, other] = [await context.newPage(), await context.newPage()];
    for (const p of [one, other]) await p.goto(`${base}#/main`);
    await one.getByRole("button", { name: "Appearance" }).click();
    await one.getByRole("radio", { name: "Dark" }).check();
    await other.waitForFunction(() => getComputedStyle(document.body).backgroundColor !== "rgb(255, 255, 255)");
  } finally {
    await context.close();
  }
});

test("the appearance menu opens under its button and closes when the window resizes", async () => {
  const fresh = await openSheet({ viewport: { width: 1300, height: 700 } });
  const button = fresh.getByRole("button", { name: "Appearance" });
  const menu = fresh.locator("#appearance-menu");
  await button.click();
  const b = await button.boundingBox();
  const m = await menu.boundingBox();
  assert.ok(m.y >= b.y + b.height && m.y < b.y + b.height + 10, `menu top ${m.y}, button bottom ${b.y + b.height}`);
  assert.ok(Math.abs(m.x + m.width - (b.x + b.width)) < 1, "menu's right edge lines up with the button's");
  await fresh.setViewportSize({ width: 700, height: 700 });
  await menu.waitFor({ state: "hidden" });
});

test("a saved appearance applies before the app script runs, and a bad one is ignored", async () => {
  const fresh = await newPage({ colorScheme: "light" });
  await fresh.addInitScript(() => localStorage.setItem("color-scheme", "dark"));
  await fresh.route("**/app.js", (route) => route.abort());
  await fresh.goto(`${base}#/main`, { waitUntil: "domcontentloaded" });
  assert.ok(await isDark(fresh));
  const bad = await openSheet({ colorScheme: "dark" });
  await bad.evaluate(() => localStorage.setItem("color-scheme", "bogus"));
  await bad.reload();
  await bad.getByRole("button", { name: "Appearance" }).click();
  assert.ok(await bad.getByRole("radio", { name: "System (dark)" }).isChecked());
});

test("sheets are grouped under named sections", async () => {
  await page.goto(`${base}#/main`);
  assert.equal(await page.textContent("tr.section th"), "Medicare Advantage with drug coverage");
});

test("section labels stay in view when the sheet scrolls sideways", async () => {
  const narrow = await newPage({ viewport: { width: 400, height: 800 } });
  await narrow.goto(`${base}#/main`);
  await narrow.waitForSelector("table.sheet");
  await narrow.evaluate(() => { document.querySelector("#content").scrollLeft = 1000; });
  const plan = await narrow.locator("tbody th.plan a").first().boundingBox();
  const label = await narrow.locator("tr.section th > *").first().boundingBox();
  assert.equal(label.x, plan.x);
  await narrow.close();
});

test("a spreadsheet link to a cited cell opens its quote", async () => {
  await page.goto(`${base}#/main/H2001-045-0/H_inpatient`);
  await shown(docOf("H2001-045-0", "EOC"), 14);
  assert.match((await page.locator(".textLayer mark").allTextContents()).join(" "), /\$1,980 copayment/);
});

test("a cited cell and its pipeline view load under the content security policy", async () => {
  const fresh = await newPage();
  await fresh.addInitScript(() => {
    window.violations = [];
    document.addEventListener("securitypolicyviolation", (e) => window.violations.push(`${e.violatedDirective} ${e.blockedURI}`));
  });
  const response = await fresh.goto(`${base}#/main/H2001-045-0/H_inpatient`);
  assert.match(response.headers()["content-security-policy"], /default-src 'self'/);
  await fresh.waitForSelector(`#page-area[data-shown="${docOf("H2001-045-0", "EOC")} 14"] .textLayer mark`);
  await fresh.locator("#how-this").click();
  await fresh.waitForSelector(".how-lens");
  assert.deepEqual(await fresh.evaluate(() => window.violations), []);
});

test("a cell opens from the keyboard", async () => {
  await page.goto(`${base}#/main`);
  await row("H2001-045-0").locator("td.cited", { hasText: "$1,980" }).getByRole("link").focus();
  await page.keyboard.press("Enter");
  await shown(docOf("H2001-045-0", "EOC"), 14);
  assert.match(page.url(), /#\/2027\/main\/H2001-045-0\/inpatient$/);
});

test("a blank cell's link has a box to show focus", async () => {
  await page.goto(`${base}#/main`);
  const box = await page.locator('td[data-col] > a[aria-label="Blank"]').first().boundingBox();
  assert.ok(box.width > 0 && box.height > 0);
});

test("every link is a permalink that opens what clicking it shows", async () => {
  const clicking = await newPage();
  await clicking.goto(`${base}#/notes`);
  await clicking.locator("td.cited").first().click();
  await clicking.waitForSelector("#page-area[data-shown]");
  assert.equal(await clicking.locator('a[href="#"], a:not([href])').count(), 0);
  const link = clicking.locator("#source-note p.comment-source a");
  const href = await link.getAttribute("href");
  const [, plan, kind, n] = href.match(/^#\/2027\/notes\/\w+\/([^/]+)\/\w+\/(\w+)\/(\d+)$/);
  const target = `#page-area[data-shown="${docOf(plan, kind)} ${n}"]`;
  await link.click();
  await clicking.waitForSelector(target);
  const fresh = await newPage();
  await fresh.goto(`${base}${href}`);
  await fresh.waitForSelector(target);
});

test("icon buttons have names", async () => {
  await page.goto(`${base}#/main/H2001-045-0/H_inpatient`);
  for (const name of ["Previous page", "Next page", "Close document", "Find in document"]) {
    assert.equal(await page.getByRole("button", { name, exact: true }).count(), 1, name);
  }
});

test("the window title names the view", async () => {
  await page.goto(`${base}#/notes`);
  await page.waitForSelector("table.notes");
  assert.equal(await page.title(), "Notes – pdxplans.org – 2027 Medicare Advantage plans");
  await page.goto(`${base}#/plan/H2001-045-0`);
  await page.waitForSelector(".plan-page");
  assert.equal(await page.title(), `${site.plans.find((p) => p.plan_id === "H2001-045-0").plan_name} – pdxplans.org – 2027 Medicare Advantage plans`);
});

test("sheet headers name their rows and columns", async () => {
  await page.goto(`${base}#/main`);
  await page.waitForSelector("table.sheet");
  assert.equal(await page.locator("table.sheet thead th:not([scope=col])").count(), 0);
  assert.equal(await page.locator("table.sheet tbody th.plan:not([scope=row])").count(), 0);
});

test("hiding the viewer forgets the shown page", async () => {
  await page.goto(`${base}#/main/H2001-045-0/H_inpatient`);
  await shown(docOf("H2001-045-0", "EOC"), 14);
  await page.goto(`${base}#/main`);
  assert.equal(await page.locator("#page-area[data-shown]").count(), 0);
});

test("clicking a cited cell highlights the quote on its page", async () => {
  await page.goto(`${base}#/main`);
  await row("H2001-045-0").locator("td.cited", { hasText: "$1,980" }).click();
  await shown(docOf("H2001-045-0", "EOC"), 14);
  assert.match((await page.locator(".textLayer mark").allTextContents()).join(" "), /\$1,980 copayment/);
});

test("clicking a DVHA cell with an EOC citation highlights the quote", async () => {
  const [cite] = site.dvha.rows.find((r) => r.plan_id === "H3805-048-0").cells.J_extra_benefits.cites;
  await page.goto(`${base}#/dvha`);
  await page.locator('table.sheet td[data-plan="H3805-048-0"][data-col="J_extra_benefits"]').click();
  await shown(cite.doc, cite.page);
  assert.match((await page.locator(".textLayer mark").allTextContents()).join(" "), /Meal benefit/);
});

test("clicking an uncited cell opens the summary of benefits with a note", async () => {
  await page.goto(`${base}#/main`);
  await row("H3805-048-0").locator(UNCITED).first().click();
  await shown(docOf("H3805-048-0", "SB"), 1);
  assert.match(await page.textContent("#source-note"), /CMS 2027 plan data/);
  assert.match(await page.textContent("#doc-title"), /^Summary of Benefits/);
});

test("scrolling the document moves to the next page", async () => {
  await page.goto(`${base}#/main`);
  await row("H3805-048-0").locator(UNCITED).first().click();
  await shown(docOf("H3805-048-0", "SB"), 1);
  await page.$eval("#page-area", (area) => area.scrollBy(0, area.querySelector(".page").offsetHeight + 50));
  await page.waitForFunction(() => document.querySelector("#page").value === "2");
  await page.waitForSelector('#page-area .page[data-page="2"] canvas');
});

test("arrows and the page box move between pages", async () => {
  await page.click("#next");
  await shown(docOf("H3805-048-0", "SB"), 3);
  await page.click("#prev");
  await shown(docOf("H3805-048-0", "SB"), 2);
  await page.focus("#page");
  await page.$eval("#page-area", (area) => area.scrollBy(0, area.clientHeight * 2));
  await page.waitForTimeout(300);
  assert.equal(await page.inputValue("#page"), "2", "scrolling must not overwrite the page box while it has focus");
  await page.fill("#page", "5");
  await page.press("#page", "Enter");
  await shown(docOf("H3805-048-0", "SB"), 5);
});

test("only pages near the view keep a canvas", async () => {
  const eoc = docOf("H2001-045-0", "EOC");
  await page.goto(`${base}#/plan/H2001-045-0`);
  await page.locator("table.docs a", { hasText: "Evidence of Coverage" }).click();
  await shown(eoc, 1);
  for (let i = 0; i < 20; i++) {
    await page.$eval("#page-area", (area) => area.scrollBy(0, area.clientHeight * 2));
    await page.waitForTimeout(50);
  }
  await page.waitForTimeout(1000);
  assert.ok(await page.locator("#page-area canvas").count() <= 10);
});

test("resizing keeps the cited quote in view", async () => {
  await page.goto(`${base}#/main`);
  await row("H2923-009-0").locator("td").nth(site.main.columns.findIndex((c) => c.key === "U_naturopath")).click();
  await page.locator("#source-note p.cite a", { hasText: "EOC" }).first().click();
  await shown(docOf("H2923-009-0", "EOC"), 71);
  await page.setViewportSize({ width: 1600, height: 600 });
  await page.waitForTimeout(1500);
  const visible = await page.$eval("#page-area", (area) => {
    const a = area.getBoundingClientRect();
    const m = area.querySelector("mark").getBoundingClientRect();
    return m.top >= a.top && m.bottom <= a.bottom;
  });
  await page.setViewportSize({ width: 1600, height: 1000 });
  assert.ok(visible);
});

test("a column header says what the column shows on hover, and a click pins it", async () => {
  await page.goto(`${base}#/main`);
  const column = site.main.columns.find((c) => c.key === "M_part_b_drugs");
  const box = page.locator("table.sheet thead .term-box", { has: page.locator(".term", { hasText: column.label }) });
  const pop = box.locator(".term-pop");
  assert.equal(await pop.isVisible(), false);
  await box.locator(".term").hover();
  assert.equal(await pop.textContent(), column.about);
  await box.locator(".term").click();
  await page.mouse.move(0, 0);
  assert.ok(await pop.isVisible());
  await page.keyboard.press("Escape");
  assert.equal(await pop.isVisible(), false);
});

test("color marks a comment, shown on hover and in the note", async () => {
  await page.goto(`${base}#/main`);
  const index = site.main.columns.findIndex((c) => c.key === "K_tests_labs");
  const cell = row("H5439-019-0").locator("td").nth(index);
  assert.match(await cell.getAttribute("class"), /commented/);
  assert.match(await cell.getAttribute("title"), /EKG/);
  assert.equal(await page.locator("td.commented").count(), site.main.rows.flatMap((r) => Object.values(r.cells)).filter((c) => c.comment).length);
  const background = (td) => td.evaluate((e) => getComputedStyle(e).backgroundColor);
  assert.notEqual(await background(row("H2001-045-0").locator("td.cited").first()), await background(cell));
  await cell.click();
  assert.match(await page.textContent("#source-note .comment"), /EKG/);
  const { doc, page: n, quote } = site.main.rows.find((r) => r.plan_id === "H5439-019-0").cells.K_tests_labs.comment;
  await shown(doc, n);
  await page.$eval("#page-area", (area) => { area.scrollTop = 0; delete area.dataset.shown; });
  await page.locator("#source-note .comment-source a", { hasText: `EOC page ${n}` }).click();
  await shown(doc, n);
  const squash = (t) => t.replace(/\s+/g, "").toLowerCase();
  assert.equal(squash((await page.locator(".textLayer mark").allTextContents()).join("")), squash(quote));
});

test("opening a plan shows its summary of benefits, unless one of its documents is open", async () => {
  await page.goto(`${base}#/main`);
  await row("H3805-048-0").locator(UNCITED).first().click();
  await shown(docOf("H3805-048-0", "SB"), 1);
  await page.locator("table.sheet th.plan a", { hasText: "DEVOTED CORE 001" }).click();
  await shown(docOf("H2923-001-0", "SB"), 1);
  await page.locator("table.docs a", { hasText: "Evidence of Coverage" }).click();
  await shown(docOf("H2923-001-0", "EOC"), 1);
  await page.click("nav a[data-view=main]");
  await page.locator("table.sheet th.plan a", { hasText: "DEVOTED CORE 001" }).click();
  await page.waitForSelector(".plan-page");
  assert.match(await page.textContent("#doc-title"), /^Evidence of Coverage/);
});

test("the page has no plan dropdown, citation corners or footer", async () => {
  await page.goto(`${base}#/main`);
  assert.equal(await page.locator("nav select, footer").count(), 0);
  const corner = await page.locator("td.cited").first().evaluate((td) => getComputedStyle(td, "::after").content);
  assert.equal(corner, "none");
});

const allCells = (sheet) => site[sheet].rows.flatMap((r) => Object.entries(r.cells).map(([col, cell]) => ({ plan_id: r.plan_id, col, cell })));
const cellTd = (planId, col) => page.locator(`.sheet-wrap td[data-plan="${planId}"][data-col="${col}"]`);

test("Notes lists every comment with links to its document page and cell", async () => {
  const comments = ["main", "dvha"].flatMap(allCells).filter(({ cell }) => cell.comment);
  await page.goto(`${base}#/main`);
  await page.click("nav a[data-view=notes]");
  const rows = page.locator("table.notes tbody tr");
  await rows.first().waitFor();
  assert.equal(await rows.count(), comments.length);
  const wellcare = rows.filter({ has: page.locator('td[data-plan="H5439-019-0"][data-col="K_tests_labs"]') });
  assert.match(await wellcare.textContent(), /EKGs/);
  await wellcare.locator("td.links a", { hasText: "EOC page 90" }).click();
  await shown(docOf("H5439-019-0", "EOC"), 90);
  await wellcare.locator("td.links a", { hasText: "Show in Main chart" }).click();
  await page.waitForSelector(".sheet-wrap td.selected");
  assert.match(await cellTd("H5439-019-0", "K_tests_labs").getAttribute("class"), /selected/);
});

test("going back to Notes keeps the scroll position", async () => {
  await page.goto(`${base}#/notes`);
  const target = page.locator("table.notes tbody tr").last();
  await target.scrollIntoViewIfNeeded();
  const before = await page.$eval("#content", (c) => c.scrollTop);
  assert.ok(before > 0);
  await target.locator("td.links a", { hasText: "Show in" }).click();
  await page.waitForSelector(".sheet-wrap td.selected");
  await page.goBack();
  await page.waitForSelector("table.notes");
  assert.equal(await page.$eval("#content", (c) => c.scrollTop), before);
});

test("a cited cell's note links to its comment's page", async () => {
  const { plan_id, col, cell } = allCells("main").find(({ cell }) => cell.cites.length && cell.comment);
  await page.goto(`${base}#/main`);
  await cellTd(plan_id, col).click();
  await page.$eval("#page-area", (area) => delete area.dataset.shown);
  await page.locator("#source-note p.comment-source a").click();
  await shown(cell.comment.doc, cell.comment.page);
});

test("page references in comment text open that page", async () => {
  const fresh = await newPage({ viewport: { width: 1600, height: 1000 } });
  await fresh.route("**/data.json", (route) => {
    const edited = structuredClone(site);
    edited.main.rows.find((r) => r.plan_id === "H5439-019-0").cells.K_tests_labs.comment.text = "See EOC page 82 for EKGs.";
    route.fulfill({ json: edited });
  });
  await fresh.goto(`${base}#/main`);
  await fresh.locator('table.sheet td[data-plan="H5439-019-0"][data-col="K_tests_labs"]').click();
  await fresh.waitForSelector(`#page-area[data-shown="${docOf("H5439-019-0", "EOC")} 90"]`);
  await fresh.locator("#source-note .comment a", { hasText: "EOC page 82" }).click();
  await fresh.waitForSelector(`#page-area[data-shown="${docOf("H5439-019-0", "EOC")} 82"]`);
  await fresh.close();
});

test("the open document's plan row is highlighted until the viewer closes", async () => {
  await page.goto(`${base}#/main`);
  const sb = docOf("H3805-048-0", "SB");
  await row("H3805-048-0").locator(UNCITED).first().click();
  await shown(sb, 1);
  assert.deepEqual((await page.locator("table.sheet tr.open-plan small").allTextContents()).sort(), [...site.docs[sb].plan_ids].sort());
  await page.click("#close");
  assert.equal(await page.locator("tr.open-plan").count(), 0);
});

test("a quote running down one column of a two-column table is highlighted", async () => {
  const fresh = await newPage({ viewport: { width: 1600, height: 1000 } });
  const eoc = docOf("H2406-070-0", "EOC");
  const quote = "$0 copayment or a colonoscopy at an outpatient hospital.";
  await fresh.route("**/data.json", (route) => {
    const edited = structuredClone(site);
    const cell = edited.main.rows.find((r) => r.plan_id === "H2406-070-0").cells.C_premium;
    cell.cites = [{ line: null, value: cell.value, doc: eoc, page: 86, quote }];
    route.fulfill({ json: edited });
  });
  await fresh.goto(`${base}#/main`);
  await fresh.locator('table.sheet td[data-plan="H2406-070-0"][data-col="C_premium"]').click();
  await fresh.waitForSelector(`#page-area[data-shown="${eoc} 86"]`);
  const squash = (t) => t.replace(/\s+/g, "").toLowerCase();
  assert.equal(squash((await fresh.locator(".textLayer mark").allTextContents()).join("")), squash(quote));
  await fresh.close();
});

test("every quote a cell cites on the shown page is highlighted", async () => {
  const { cites } = site.main.rows.find((r) => r.plan_id === "H3805-048-0").cells.J_outpatient_rehab;
  assert.equal(new Set(cites.map((c) => `${c.doc} ${c.page}`)).size, 1);
  await page.goto(`${base}#/main`);
  await page.locator('table.sheet td[data-plan="H3805-048-0"][data-col="J_outpatient_rehab"]').click();
  await shown(cites[0].doc, cites[0].page);
  const squash = (t) => t.replace(/\s+/g, "").toLowerCase();
  const marked = squash((await page.locator(".textLayer mark").allTextContents()).join(""));
  for (const c of cites) assert.ok(marked.includes(squash(c.quote)), `${c.quote} in ${marked}`);
});

test("a note in Notes shows only the citations on the pages it names", async () => {
  const kindPage = (q) => `${site.docs[q.doc].kind} ${q.page}`;
  const { plan_id, col, cell } = allCells("main").find(({ cell }) =>
    cell.comment && new Set(cell.cites.map(kindPage)).size >= 3 && cell.cites.some((c) => kindPage(c) === kindPage(cell.comment)));
  const named = cell.cites.find((c) => kindPage(c) !== kindPage(cell.comment));
  const pages = new Set([kindPage(cell.comment), kindPage(named)]);
  const expected = cell.cites.filter((c) => pages.has(kindPage(c)));
  const fresh = await newPage();
  await fresh.route("**/data.json", (route) => {
    const edited = structuredClone(site);
    // The range's first page holds no citation, so only its last page names the citations.
    edited.main.rows.find((r) => r.plan_id === plan_id).cells[col].comment.text =
      `See ${site.docs[named.doc].kind.toLowerCase()} pages ${named.page - 1}-${named.page}.`;
    route.fulfill({ json: edited });
  });
  assert.ok(!pages.has(`${site.docs[named.doc].kind} ${named.page - 1}`) && !cell.cites.some((c) => kindPage(c) === `${site.docs[named.doc].kind} ${named.page - 1}`));
  await fresh.goto(`${base}#/notes`);
  await fresh.locator(`table.notes td[data-plan="${plan_id}"][data-col="${col}"]`).click();
  await fresh.waitForSelector(`#page-area[data-shown="${cell.comment.doc} ${cell.comment.page}"]`);
  assert.deepEqual(await fresh.locator("#source-note p.cite").allTextContents(),
    expected.map((c) => `${kindPage(c).replace(" ", " page ")}${c.line ? ` (line ${c.line})` : ""}: “${c.quote}”`));
  assert.ok(expected.length < cell.cites.length);
  assert.equal(await fresh.locator("#source-note p.comment-source").count(), 1);
  assert.equal(await fresh.locator("#source-note a", { hasText: "Show this cell's citations in Main chart" }).getAttribute("href"),
    `#/2027/main/${plan_id}/${col.replace(/^[A-Z]+_/, "")}`);
  await fresh.locator("#source-note p.comment a").click();
  await fresh.waitForSelector(`#page-area[data-shown="${named.doc} ${named.page - 1}"]`);
  await fresh.locator("#next").click();
  await fresh.waitForSelector(`#page-area[data-shown="${named.doc} ${named.page}"] .textLayer mark`);
});

test("a note in Notes links to the cell's citations only when it hides some", async () => {
  const kindPage = (q) => `${site.docs[q.doc].kind} ${q.page}`;
  const cells = allCells("main").filter(({ cell }) => cell.comment && cell.cites.length);
  const fresh = await newPage();
  await fresh.route("**/data.json", (route) => {
    const edited = structuredClone(site);
    const [hidesAll, hidesNone] = cells.map(({ plan_id, col }) => edited.main.rows.find((r) => r.plan_id === plan_id).cells[col]);
    hidesAll.comment.text = "Note.";
    hidesAll.comment.page = Math.max(...hidesAll.cites.map((c) => c.page)) + 1;
    hidesNone.comment.text = "Note.";
    hidesNone.cites = hidesNone.cites.filter((c) => kindPage(c) === kindPage(hidesNone.comment));
    route.fulfill({ json: edited });
  });
  await fresh.goto(`${base}#/notes`);
  const link = fresh.locator("#source-note a", { hasText: "Show this cell's citations" });
  await fresh.locator(`table.notes td[data-plan="${cells[0].plan_id}"][data-col="${cells[0].col}"]`).click();
  await fresh.waitForSelector("#source-note p.comment-source");
  assert.equal(await fresh.locator("#source-note p.cite").count(), 0);
  assert.equal(await link.count(), 1);
  await fresh.locator(`table.notes td[data-plan="${cells[1].plan_id}"][data-col="${cells[1].col}"]`).click();
  await fresh.waitForSelector(`#source-note b:has-text("${site.plans.find((p) => p.plan_id === cells[1].plan_id).plan_name}")`);
  assert.equal(await link.count(), 0);
});

test("browser zoom enlarges the document pages", async () => {
  const pageWidthRatio = async (zoom) => {
    const fresh = await newPage({ viewport: { width: 1600, height: 1000 } });
    // Chrome reports browser zoom as the ratio of the window's width to the page's width.
    if (zoom) await fresh.addInitScript((z) => Object.defineProperty(window, "outerWidth", { get: () => window.innerWidth * z }), zoom);
    await fresh.goto(`${base}#/main`);
    await fresh.locator(`table.sheet tr:has(small:text("H3805-048-0")) ${UNCITED}`).first().click();
    await fresh.waitForSelector(`#page-area[data-shown="${docOf("H3805-048-0", "SB")} 1"]`);
    const ratio = await fresh.$eval("#page-area", (area) => area.querySelector(".page").offsetWidth / area.clientWidth);
    await fresh.close();
    return ratio;
  };
  const plain = await pageWidthRatio();
  const zoomed = await pageWidthRatio(1.5);
  assert.ok(plain < 1, `${plain}`);
  assert.ok(Math.abs(zoomed / plain - 1.5) < 0.05, `${zoomed / plain}`);
});

test("header says when the site was last updated", async () => {
  const fresh = await newPage({ timezoneId: "America/Los_Angeles" });
  await fresh.route("**/data.json", (route) =>
    route.fulfill({ json: { ...site, built: new Date(Date.now() - 3 * 3600000).toISOString() } }));
  await fresh.clock.install();
  await fresh.goto(`${base}#/main`);
  const label = fresh.locator("header #updated");
  await label.filter({ hasText: "Last updated" }).waitFor();
  assert.equal(await label.textContent(), "Last updated 3 hours ago");
  assert.match(await label.getAttribute("title"), /\b(PDT|PST)\b/);
  await fresh.clock.runFor(60 * 60000);
  assert.equal(await label.textContent(), "Last updated 4 hours ago");
  await fresh.close();
});

test("each note kind has its own color, and the Notes filter shows caveats", async () => {
  const fresh = await newPage({ viewport: { width: 1600, height: 1000 } });
  await fresh.goto(`${base}#/main`);
  const background = (locator) => locator.evaluate((e) => getComputedStyle(e).backgroundColor);
  const question = fresh.locator("table.sheet td.commented.question").first();
  const caveat = fresh.locator("table.sheet td.commented.caveat").first();
  const contradiction = fresh.locator("table.sheet td.commented.contradiction").first();
  const lavender = await background(caveat);
  const colors = new Set([lavender, await background(question), await background(contradiction)]);
  assert.equal(colors.size, 3);
  assert.match(await caveat.getAttribute("title"), /^Caveat: /);
  assert.match(await contradiction.getAttribute("title"), /^Volunteer chart differs: /);
  await question.click();
  assert.equal(await background(fresh.locator("#source-note .comment")), await background(question));
  assert.match(await fresh.textContent("#source-note .comment"), /^Open question: /);
  await caveat.click();
  assert.equal(await background(fresh.locator("#source-note .comment")), lavender);
  assert.equal(await background(caveat), lavender, "stays lavender in the open plan's row");
  await contradiction.click();
  assert.equal(await background(fresh.locator("#source-note .comment")), await background(contradiction));
  await fresh.click("nav a[data-view=notes]");
  const rows = fresh.locator("table.notes tbody tr");
  await fresh.selectOption("#kind-filter", "caveat");
  const notes = ["main", "dvha"].flatMap((sheet) => site[sheet].rows.flatMap((r) => Object.values(r.cells)))
    .filter((c) => c.comment?.kind === "caveat");
  const shown = await rows.filter({ visible: true }).allTextContents();
  assert.ok(notes.length > 0);
  assert.equal(shown.length, notes.length);
  assert.ok(shown.every((t) => t.includes("Caveat")));
  await rows.filter({ visible: true }).first().locator("a", { hasText: "Show in" }).click();
  await fresh.goBack();
  assert.equal(await fresh.locator("#kind-filter").inputValue(), "caveat");
  assert.equal(await rows.filter({ visible: true }).count(), notes.length);
  await fresh.selectOption("#kind-filter", "");
  assert.equal(await rows.filter({ visible: true }).count(), await rows.count());
  await fresh.close();
});

test("plan page lists the plan's documents", async () => {
  await page.goto(`${base}#/plan/H2001-045-0`);
  const docs = await page.locator("table.docs").textContent();
  assert.match(docs, /Summary of Benefits/);
  assert.match(docs, /Evidence of Coverage/);
});

test("every citation's and comment's quote is highlighted in full on its page", { timeout: 1_200_000 }, async () => {
  const squash = (t) => t.replace(/\s+/g, "").toLowerCase();
  const wrong = [];
  for (const sheet of ["main", "dvha"]) {
    await page.goto(`${base}#/${sheet}`);
    for (const r of site[sheet].rows) {
      for (const [col, cell] of Object.entries(r.cells)) {
        const sources = cell.cites.length ? cell.cites : cell.comment ? [cell.comment] : [];
        if (!sources.length) continue;
        await row(r.plan_id).locator("td").nth(site[sheet].columns.findIndex((c) => c.key === col)).click();
        for (const [i, c] of sources.entries()) {
          if (i) {
            // Two cites can share a page, so clear the marker before the next render sets it.
            await page.$eval("#page-area", (area) => delete area.dataset.shown);
            await page.locator("#source-note p.cite a").nth(i).click();
          }
          await shown(c.doc, c.page);
          // Quotes running down neighbouring columns interleave in page order, so also join each column alone.
          const marks = await page.$$eval(".textLayer mark", (ms) => ms.map((m) => [m.parentElement.style.left, m.textContent]));
          const columns = Object.values(Object.groupBy(marks, ([left]) => left));
          const joined = [marks, ...columns].map((ms) => squash(ms.map(([, t]) => t).join("")));
          if (!joined.some((j) => j.includes(squash(c.quote)))) wrong.push(`${sheet} ${r.plan_id} ${col} ${c.doc} p${c.page}`);
        }
      }
    }
  }
  assert.deepEqual(wrong, []);
});

test("a slow document never shows the previous document's pages", async () => {
  const fresh = await newPage({ viewport: { width: 1600, height: 1000 } });
  const slow = docOf("H7006-018-0", "SB");
  await fresh.route(`**/${site.docs[slow].file}`, async (route) => {
    await new Promise((r) => setTimeout(r, 2000));
    await route.continue();
  });
  await fresh.goto(`${base}#/main`);
  const rowIn = (p, planId) => p.locator("table.sheet tr", { has: p.locator("small", { hasText: planId }) });
  await rowIn(fresh, "H3805-048-0").locator(UNCITED).first().click();
  await fresh.waitForSelector(`#page-area[data-shown="${docOf("H3805-048-0", "SB")} 1"]`);
  const slowCell = rowIn(fresh, "H7006-018-0").locator(UNCITED).first();
  await slowCell.evaluate((td) => {
    document.querySelector("#next").click();
    td.click();
  });
  await fresh.waitForTimeout(1000);
  assert.equal(await fresh.locator("#page-area canvas").count(), 0);
  assert.match(await fresh.textContent("#page-area"), /Loading/);
  await fresh.waitForSelector(`#page-area[data-shown="${slow} 1"]`);
  await fresh.close();
});

test("the viewer links to the carrier when a document fails to load", async () => {
  const fresh = await newPage({ viewport: { width: 1600, height: 1000 } });
  const [missing] = site.plans.find((p) => p.plan_id === "H2001-045-0").docs;
  await fresh.route(`**/${site.docs[missing].file}`, (route) => route.fulfill({ status: 404, body: "Not found" }));
  await fresh.goto(`${base}#/plan/H2001-045-0`);
  await fresh.locator("table.docs a", { hasText: kindName(site.docs[missing].kind) }).click();
  await fresh.waitForFunction(() => /failed to load/.test(document.querySelector("#page-area").textContent));
  assert.equal(await fresh.getAttribute("#page-area a", "href"), site.docs[missing].url);
  await fresh.close();
});

test("a plan page links to its Medicare Plan Finder page", async () => {
  const plan = site.plans.find((p) => p.plan_id === "H3805-048-0");
  await page.goto(`${base}#/plan/${plan.plan_id}`);
  const link = page.locator(".plan-page a", { hasText: "View this plan on Medicare.gov" });
  assert.equal(await link.getAttribute("href"), plan.plan_finder_url);
});

test("a clicked cell's note links to the plan on Medicare.gov", async () => {
  const plan = site.plans.find((p) => p.plan_id === "H2001-045-0");
  await page.goto(`${base}#/main`);
  for (const cell of [row(plan.plan_id).locator("td.cited").first(), row(plan.plan_id).locator("td:not(.cited)").first()]) {
    await cell.click();
    const link = page.locator("#source-note a", { hasText: "View this plan on Medicare.gov" });
    assert.equal(await link.getAttribute("href"), plan.plan_finder_url);
  }
});

test("an uncited cell lists the CMS fields behind it and where Medicare.gov shows it", async () => {
  for (const plan of ["H7006-021-0", "H3817-008-1"]) {
    await page.goto(`${base}#/main/${plan}/O_medical_deductible`);
    const note = page.locator("#source-note");
    assert.match(await note.textContent(), /\(pbp_d_(inn|ann)_deduct_yn\) = 2 \(No\)/);
    assert.match(await note.textContent(), /View this plan on Medicare\.gov ↗ It shows this as “Health deductible”\./);
    assert.equal(await note.locator("a", { hasText: "pbp_Section_D" }).getAttribute("href"), site.cms_files.PBP);
  }
});

test("the Extra Help premium lists its Landscape columns", async () => {
  await page.goto(`${base}#/dvha/H3805-048-0/D_premium_full_extra_help`);
  const note = page.locator("#source-note");
  assert.match(await note.textContent(), /Part D Low Income Beneficiary Premium Amount = \$0\.00/);
  assert.equal(await note.locator("a", { hasText: "CMS Landscape file" }).getAttribute("href"), site.cms_files.Landscape);
  assert.match(await note.textContent(), /choose “Extra Help \(with drug costs\)”\. The search results then show this as the “Monthly Premium”\./);
});

test("a blank uncited cell says CMS data has no entry", async () => {
  const [plan, col] = site.dvha.rows.flatMap((r) =>
    Object.entries(r.cells).filter(([, c]) => c.value === "" && !c.cites.length).map(([col]) => [r.plan_id, col]))[0];
  await page.goto(`${base}#/dvha`);
  const index = site.dvha.columns.findIndex((c) => c.key === col);
  await row(plan).locator("td").nth(index).click();
  assert.match(await page.textContent("#source-note"), /has no entry for this benefit/);
});

test("a cited blank cell says the document shows why", async () => {
  await page.goto(`${base}#/main`);
  const index = site.main.columns.findIndex((c) => c.key === "U_naturopath");
  await row("H2056-003-0").locator("td").nth(index).click();
  assert.match(await page.textContent("#source-note"), /shows why this is blank/);
});

test("a link followed while the document scrolls still opens its sheet", async () => {
  const [cite] = site.dvha.rows.find((r) => r.plan_id === "H3805-048-0").cells.J_extra_benefits.cites;
  await page.goto(`${base}#/dvha`);
  await page.locator('table.sheet td[data-plan="H3805-048-0"][data-col="J_extra_benefits"]').click();
  await shown(cite.doc, cite.page);
  await page.evaluate(() => {
    location.hash = "#/main";
    document.querySelector("#page-area").dispatchEvent(new Event("scroll"));
  });
  await page.waitForFunction(() => document.querySelector("nav a.active")?.dataset.view === "main");
  assert.doesNotMatch(await page.evaluate(() => location.hash), /dvha/);
});

const openEoc = async (planId) => {
  await page.goto(`${base}#/plan/${planId}`);
  await page.locator("table.docs a", { hasText: "Evidence of Coverage" }).click();
  await shown(docOf(planId, "EOC"), 1);
};
const findCount = (text) => page.waitForFunction((t) => document.querySelector("#find-count").textContent === t, text);
const currentMark = () => page.locator(".textLayer mark.found.current").first().textContent();

test("Ctrl+F finds text on a page that has not rendered yet", async () => {
  await openEoc("H2001-045-0");
  await page.keyboard.press("Control+f");
  assert.equal(await page.evaluate(() => document.activeElement.id), "find-query");
  await page.keyboard.type("Naturopath");
  await findCount("1 of 1");
  await shown(docOf("H2001-045-0", "EOC"), 124);
  assert.match(await currentMark(), /naturopath/i);
});

test("Enter and Shift+Enter step through matches from the current page, wrapping at the ends", async () => {
  const eoc = docOf("H2001-045-0", "EOC");
  await page.keyboard.press("Escape");
  assert.equal(await page.isHidden("#find"), true);
  assert.equal(await page.locator(".textLayer mark.found").count(), 0);
  await page.fill("#page", "50");
  await page.press("#page", "Enter");
  await shown(eoc, 50);
  await page.keyboard.press("Meta+f");
  assert.equal(await page.inputValue("#find-query"), "Naturopath");
  await page.keyboard.type("acupuncture");
  await shown(eoc, 55);
  const total = Number((await page.textContent("#find-count")).match(/^\d+ of (\d+)$/)[1]);
  await findCount(`2 of ${total}`);
  await page.keyboard.press("Enter");
  await shown(eoc, 57);
  await findCount(`3 of ${total}`);
  await page.keyboard.press("Shift+Enter");
  await page.keyboard.press("Shift+Enter");
  await page.keyboard.press("Shift+Enter");
  await shown(eoc, 124);
  await findCount(`${total} of ${total}`);
  assert.match(await currentMark(), /acupuncture/i);
});

test("the find box says when nothing matches", async () => {
  await page.fill("#find-query", "zzqxv");
  await findCount("No matches");
});

test("a cited quote still scrolls into view and keeps its highlight while find is open", async () => {
  await page.goto(`${base}#/main`);
  const cell = row("H2001-045-0").locator("td.cited", { hasText: "$1,980" });
  await cell.click();
  const eoc = docOf("H2001-045-0", "EOC");
  await shown(eoc, 14);
  await page.keyboard.press("Control+f");
  await page.keyboard.type("1,980 copayment");
  await page.waitForSelector('.page[data-page="14"] mark.cite.found');
  await page.fill("#find-query", "Your costs in 2027");
  await page.waitForSelector('.page[data-page="14"] mark.found.current');
  await page.$eval("#page-area", (area) => {
    area.scrollTop = 0;
    delete area.dataset.shown;
  });
  await page.setViewportSize({ width: 1600, height: 500 });
  await cell.click();
  await shown(eoc, 14);
  const visible = await page.$eval("#page-area", (area) => {
    const a = area.getBoundingClientRect();
    const m = area.querySelector("mark.cite").getBoundingClientRect();
    return m.top >= a.top && m.bottom <= a.bottom;
  });
  await page.setViewportSize({ width: 1600, height: 1000 });
  assert.ok(visible);
});

test("reopening find keeps the query but shows no stale count", async () => {
  await page.click("#find-next");
  await page.keyboard.press("Escape");
  await page.keyboard.press("Control+f");
  assert.equal(await page.isVisible("#find"), true);
  assert.equal(await page.textContent("#find-count"), "");
  assert.equal(await page.inputValue("#find-query"), "Your costs in 2027");
});

test("opening another document closes the find box", async () => {
  await page.goto(`${base}#/main`);
  await row("H3805-048-0").locator(UNCITED).first().click();
  await shown(docOf("H3805-048-0", "SB"), 1);
  assert.equal(await page.isHidden("#find"), true);
});

test("closing the viewer hides it", async () => {
  await page.click("#close");
  assert.equal(await page.isHidden("#viewer"), true);
});

const kindName = (k) => ({ SB: "Summary of Benefits", EOC: "Evidence of Coverage" })[k];

const hash = () => page.evaluate(() => location.hash);
const hashIs = (h) => page.waitForFunction((h) => location.hash === h, h);

test("permalink: clicking a cell puts it in the URL, and the URL reopens it", async () => {
  await page.goto(`${base}#/main`);
  await cellTd("H3805-041-0", "F_primary_care").click();
  await shown(docOf("H3805-041-0", "EOC"), 12);
  assert.equal(await hash(), "#/2027/main/H3805-041-0/primary_care");
  await page.goto(`${base}#/dvha`);
  await page.goto(`${base}#/2027/main/H3805-041-0/primary_care`);
  await shown(docOf("H3805-041-0", "EOC"), 12);
  assert.equal(await page.locator("table.sheet td.selected").getAttribute("data-col"), "F_primary_care");
  assert.match((await page.locator(".textLayer mark.cite").allTextContents()).join(" "), /\$0 copayment/);
});

test("permalink: another citation's page goes in the URL and reopens with its quote", async () => {
  await page.goto(`${base}#/main`);
  await cellTd("H3805-041-0", "F_primary_care").click();
  await page.locator("#source-note p.cite a", { hasText: "EOC page 82" }).first().click();
  await shown(docOf("H3805-041-0", "EOC"), 82);
  await hashIs("#/2027/main/H3805-041-0/primary_care/EOC/82");
  await page.goto(`${base}#/dvha`);
  await page.goto(`${base}#/2027/main/H3805-041-0/primary_care/EOC/82`);
  await shown(docOf("H3805-041-0", "EOC"), 82);
  assert.equal(await page.locator("td.selected").getAttribute("data-col"), "F_primary_care");
  assert.match((await page.locator('.page[data-page="82"] mark.cite').allTextContents()).join(" "), /\$0 copayment/);
});

test("permalink: scrolling the document updates the page in the URL", async () => {
  await page.goto(`${base}#/2027/main/H3805-041-0/primary_care`);
  await shown(docOf("H3805-041-0", "EOC"), 12);
  await page.click("#next");
  await hashIs("#/2027/main/H3805-041-0/primary_care/EOC/13");
  await page.click("#prev");
  await hashIs("#/2027/main/H3805-041-0/primary_care");
});

test("permalink: Back returns to the previous cell", async () => {
  await page.goto(`${base}#/main`);
  await cellTd("H3805-041-0", "F_primary_care").click();
  await cellTd("H3805-041-0", "G_specialist").click();
  await hashIs("#/2027/main/H3805-041-0/specialist");
  await page.goBack();
  await hashIs("#/2027/main/H3805-041-0/primary_care");
  await page.waitForSelector('td.selected[data-col="F_primary_care"]');
  await shown(docOf("H3805-041-0", "EOC"), 12);
});

test("permalink: closing the viewer drops the cell from the URL", async () => {
  await page.goto(`${base}#/2027/main/H3805-041-0/primary_care`);
  await shown(docOf("H3805-041-0", "EOC"), 12);
  await page.click("#close");
  await hashIs("#/2027/main");
});

test("permalink: a plan page cell keeps the plan page", async () => {
  await page.goto(`${base}#/plan/H3805-041-0`);
  await page.locator('table.benefits td[data-col="F_primary_care"]').first().click();
  await hashIs("#/2027/plan/H3805-041-0/main/primary_care");
  await page.goto(`${base}#/main`);
  await page.goto(`${base}#/2027/plan/H3805-041-0/main/primary_care`);
  await shown(docOf("H3805-041-0", "EOC"), 12);
  assert.ok(await page.isVisible("div.plan-page"));
  assert.equal(await page.locator("td.selected").getAttribute("data-col"), "F_primary_care");
});

test("permalink: a plan page document link puts the page in the URL", async () => {
  await page.goto(`${base}#/2027/plan/H3805-041-0/EOC/5`);
  await shown(docOf("H3805-041-0", "EOC"), 5);
  await page.locator("table.docs a", { hasText: "Summary of Benefits" }).click();
  await hashIs("#/2027/plan/H3805-041-0");
});

test("permalink: a Notes cell keeps the Notes page and links to the sheet", async () => {
  const { plan_id, col } = allCells("dvha").find(({ cell }) => cell.comment);
  const id = col.replace(/^[A-Z]+_/, "");
  await page.goto(`${base}#/notes`);
  const tr = page.locator("table.notes tr", { has: page.locator(`td[data-col="${col}"]`) }).filter({ hasText: plan_id }).first();
  await tr.locator(`td[data-col="${col}"]`).click();
  await hashIs(`#/2027/notes/dvha/${plan_id}/${id}`);
  assert.equal(await tr.locator("td.links a", { hasText: "Show in" }).getAttribute("href"), `#/2027/dvha/${plan_id}/${id}`);
});

test("permalink: a link to another year says so and opens no cell", async () => {
  await page.goto(`${base}#/2027/main/H3805-041-0/primary_care`);
  await shown(docOf("H3805-041-0", "EOC"), 12);
  await page.goto(`${base}#/2026/main/H3805-041-0/primary_care`);
  await hashIs("#/2027/main");
  assert.match(await page.textContent("#content"), /That link was for 2026 plans\. This site shows 2027 plans\./);
  assert.equal(await page.locator("td.selected").count(), 0);
  assert.equal(await page.isHidden("#viewer"), true);
});

test("permalink: paging through the document adds no history entries", async () => {
  await page.goto(`${base}#/2027/main/H3805-041-0/primary_care`);
  await shown(docOf("H3805-041-0", "EOC"), 12);
  const entries = await page.evaluate(() => history.length);
  await page.click("#next");
  await page.click("#next");
  await hashIs("#/2027/main/H3805-041-0/primary_care/EOC/14");
  assert.equal(await page.evaluate(() => history.length), entries);
});

test("permalink: Back after closing the viewer reopens the cell", async () => {
  await page.goto(`${base}#/main`);
  await cellTd("H3805-041-0", "F_primary_care").click();
  await page.click("#close");
  await hashIs("#/2027/main");
  await page.goBack();
  await hashIs("#/2027/main/H3805-041-0/primary_care");
  await shown(docOf("H3805-041-0", "EOC"), 12);
});

test("permalink: Back to a plan page shows its summary of benefits", async () => {
  await page.goto(`${base}#/2027/plan/H3805-041-0`);
  await shown(docOf("H3805-041-0", "SB"), 1);
  await page.locator('table.benefits td[data-col="F_primary_care"]').first().click();
  await shown(docOf("H3805-041-0", "EOC"), 12);
  await page.goBack();
  await shown(docOf("H3805-041-0", "SB"), 1);
  assert.equal(await hash(), "#/2027/plan/H3805-041-0");
});

test("permalink: an old Ambiguities link opens Notes, and a page link in a note points the URL at its row's cell", async () => {
  const fresh = await newPage({ viewport: { width: 1600, height: 1000 } });
  await fresh.route("**/data.json", (route) => {
    const edited = structuredClone(site);
    edited.main.rows.find((r) => r.plan_id === "H5439-019-0").cells.K_tests_labs.comment.text = "See EOC page 82 for EKGs.";
    route.fulfill({ json: edited });
  });
  await fresh.goto(`${base}#/2027/ambiguities/main/H2001-045-0/part_b_drugs`);
  await fresh.waitForSelector("td.selected");
  await fresh.locator('tr:has(td[data-plan="H5439-019-0"][data-col="K_tests_labs"]) td.comment-text a').click();
  await fresh.waitForSelector(`#page-area[data-shown="${docOf("H5439-019-0", "EOC")} 82"]`);
  await fresh.waitForFunction(() => location.hash === "#/2027/notes/main/H5439-019-0/tests_labs/EOC/82");
  await fresh.close();
});

// A full load, so the lens on screen is the new one.
async function openHow(p, path) {
  await p.goto("about:blank");
  await p.goto(`${base}#/2027/how${path && `/${path}`}`);
  await p.waitForSelector(".how-lens");
}

test("pipeline view: the nav link opens the example cell's first step", async () => {
  await page.goto(`${base}#/main`);
  await page.click("nav a[data-view=how]");
  await page.waitForSelector(".how-lens");
  assert.match(page.url(), /#\/2027\/how\/main\/H1036-153-0\/ambulance\/list-plans$/);
  assert.equal(await page.textContent(".how-step"), "List the plans");
});

test("pipeline view: Next steps through the example cell's steps, each showing its input and output rows", async () => {
  await openHow(page, "");
  const labels = [];
  // The example cell has no note, so Write notes outputs no rows.
  const hasOutputRows = (label) => outputs(STEPS.find((s) => s.label === label)).some((id) => NODES[id].table?.rows.length ?? true);
  for (;;) {
    labels.push(await page.textContent(".how-step"));
    for (const side of ["input", "output"]) {
      if (side === "output" && !hasOutputRows(labels.at(-1))) continue;
      assert.ok(await page.locator(`.how-rows.${side} :is(tbody tr, pre span)`).count(), `${labels.at(-1)} ${side}`);
    }
    const next = page.locator("a.how-nav[rel=next]");
    if (!(await next.count())) break;
    await next.click();
    await page.waitForFunction((n) => document.querySelector(".how-count")?.textContent.startsWith(`${n} `), labels.length + 1);
  }
  assert.equal(labels.length, 10);
  assert.equal(labels.at(-1), "Publish");
});

test("pipeline view: a step on the map opens in the lens, and Back returns", async () => {
  await openHow(page, "main/H1036-153-0/ambulance/check-facts");
  await page.click(".how-pill:text-is('Apply column rules')");
  await page.waitForFunction(() => document.querySelector(".how-step")?.textContent === "Apply column rules");
  assert.equal(await page.locator(".how-node.on").count(), 6);
  assert.equal(await page.locator(".how-rows.input .hi").count(), 5);
  assert.equal(await page.evaluate(() => document.activeElement.className), "how-step");
  await page.goBack();
  await page.waitForFunction(() => document.querySelector(".how-step")?.textContent === "Check facts");
});

test("pipeline view: a step with three inputs and three outputs lights them all, joining and splitting at its one label", async () => {
  await openHow(page, "main/H1036-153-0/ambulance/column-rules");
  assert.equal(await page.locator(".how-node.on").count(), 6);
  assert.equal(await page.locator(".how-edge.on").count(), 6);
  assert.equal(await page.locator(".how-pill.on").count(), 1);
  assert.equal(await page.locator(".how-pill").count(), 10);
  assert.equal(await page.locator(".how-edge[marker-end]").count(), 12);
});

test("pipeline view: a table heading says where its data lives and opens it, in a new tab when it is elsewhere", async () => {
  await openHow(page, "main/H1036-153-0/ambulance/find-pdfs");
  const head = (name) => page.locator(".how-rows-head", { has: page.locator(`code:text-is("${name}")`) });
  const source = (name) => head(name).locator(".how-source");
  assert.equal(await head("links").locator(".how-store").textContent(), "In git");
  assert.equal(await source("links").getAttribute("aria-label"), "links, opens in a new tab");
  assert.match(await source("links").getAttribute("href"), /^https:\/\/github\.com\/.+\/blob\/[0-9a-f]{40}\/data\/2027\/links\.csv$/);
  assert.equal(await source("links").getAttribute("target"), "_blank");
  assert.equal(await head("plans").locator(".how-store").textContent(), "In D1");
  assert.equal(await source("plans").getAttribute("href"), `#/2027/tables/${DEPLOYED}/plans/H1036-153-0`);
  assert.equal(await source("plans").getAttribute("aria-label"), "plans, opens in Tables");
  assert.equal(await source("plans").getAttribute("target"), null);
  await openHow(page, "main/H1036-153-0/ambulance/read-facts");
  assert.equal(await source("model answers").count(), 0);
  await openHow(page, "main/H1036-153-0/ambulance/publish");
  assert.equal(await source("main_chart").getAttribute("href"), `#/2027/tables/${DEPLOYED}/main_chart/H1036-153-0`);
  assert.equal(await source("presented").getAttribute("href"), `#/2027/tables/${DEPLOYED}/presented/H1036-153-0/main/AB_ambulance`);
  assert.equal(await source("pdxplans.org").getAttribute("aria-label"), "pdxplans.org, opens in a new tab");
  assert.match(await page.textContent(".how-legend"), /In git.*In R2.*In D1.*Website/);
});

test("pipeline view: the map's boxes open nothing", async () => {
  await openHow(page, "main/H1036-153-0/ambulance/find-pdfs");
  assert.equal(await page.locator(".how-map :is(a, button):not(.how-pill)").count(), 0);
});

test("pipeline view: a CMS table heading warns before it downloads a zip file", async () => {
  await openHow(page, "main/H1036-153-0/ambulance/cms-facts");
  const url = page.url();
  await page.locator(".how-rows-head .how-source", { has: page.locator('code:text-is("CMS PBP tables")') }).click();
  const warning = page.locator(".how-download:popover-open");
  assert.match(await warning.textContent(), /zip file/);
  assert.equal(await warning.getByRole("link").getAttribute("href"), site.cms_files.PBP);
  assert.equal(page.url(), url);
  await page.keyboard.press("Escape");
  assert.equal(await warning.count(), 0);
});

test("pipeline view: the CMS download warning closes when the detail scrolls", async () => {
  await page.setViewportSize({ width: 1300, height: 500 });
  try {
    await openHow(page, "main/H1036-153-0/ambulance/cms-facts");
    await page.locator(".how-rows-head .how-source", { has: page.locator('code:text-is("CMS PBP tables")') }).click();
    assert.equal(await page.locator(".how-download:popover-open").count(), 1);
    await page.locator(".how-lens").evaluate((e) => e.scrollBy(0, 100));
    await page.waitForFunction(() => !document.querySelector(".how-download:popover-open"));
  } finally {
    await page.setViewportSize({ width: 1600, height: 1000 });
  }
});

test("pipeline view: Find PDFs shows the URLs each source offered the plan and marks the winners", async () => {
  await openHow(page, "main/H3805-048-0/ambulance/find-pdfs");
  const offered = (name) => page.locator(".how-rows.input", { has: page.locator(`.how-rows-head code:text-is("${name}")`) });
  assert.deepEqual(await offered("found").locator("tbody tr.hi td:nth-child(1)").allTextContents(), ["RIDER", "EOC", "SB"]);
  assert.equal(await offered("links").locator("tbody tr").count(), 2);
  assert.equal(await offered("links").locator("tbody tr.hi").count(), 0);
});

test("pipeline view: every step's tables are the ones the map lights", async () => {
  for (const cell of ["main/H1036-153-0/ambulance", "dvha/H1036-153-0/vision"]) {
    for (const { id: step } of STEPS) {
      await openHow(page, `${cell}/${step}`);
      const lit = await page.locator(".how-node.on code").allTextContents();
      const tables = await page.locator(".how-rows-head code").allTextContents();
      assert.deepEqual(tables.toSorted(), lit.toSorted(), `${cell} ${step}`);
    }
  }
});

test("pipeline view: at phone width the lens sits below the map at full width", async () => {
  await page.setViewportSize({ width: 390, height: 800 });
  try {
    await openHow(page, "main/H1036-153-0/ambulance/column-rules");
    const lens = await page.locator(".how-lens").boundingBox();
    assert.ok(lens.width > 350, `lens is ${lens.width}px wide`);
  } finally {
    await page.setViewportSize({ width: 1600, height: 1000 });
  }
});

test("pipeline view: at every width, boxes on the map above one another keep a minimum gap, counting a selected node's ring", async () => {
  for (const width of [1600, 900, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    try {
      await openHow(page, "main/H1036-153-0/ambulance/list-plans");
      const boxes = await page.$$eval(".how-node, .how-pill", (els) => {
        const ring = Math.max(...[...document.querySelectorAll(".how-node.on")].map((e) =>
          Number(getComputedStyle(e).boxShadow.match(/0px 0px 0px ([\d.]+)px/)?.[1] ?? 0)));
        const scale = document.querySelector(".how-world").getBoundingClientRect().width / document.querySelector(".how-world").offsetWidth;
        return els.map((e) => {
          const r = e.getBoundingClientRect();
          return { name: e.textContent, x: r.x, y: r.y, w: r.width, h: r.height, ring: e.matches(".how-node") ? ring * scale : 0 };
        });
      });
      for (const [i, a] of boxes.entries()) for (const b of boxes.slice(i + 1)) {
        if (a.x >= b.x + b.w || b.x >= a.x + a.w) continue;
        const gap = Math.max(b.y - (a.y + a.h), a.y - (b.y + b.h)) - a.ring - b.ring;
        assert.ok(gap >= MIN_GAP, `${width}px wide: ${a.name} and ${b.name} are ${gap.toFixed(1)}px apart`);
      }
    } finally {
      await page.setViewportSize({ width: 1600, height: 1000 });
    }
  }
});

test("pipeline view: the map scrolls to show the selected step", async () => {
  await openHow(page, "main/H1036-153-0/ambulance/publish");
  const map = await page.locator(".how-map").boundingBox(), pill = await page.locator(".how-pill.on").boundingBox();
  assert.ok(pill.y >= map.y && pill.y + pill.height <= map.y + map.height, `Publish label at ${pill.y}px, map shows ${map.y}-${map.y + map.height}px`);
});

test("pipeline view: the map scrolls to show every table the selected step reads and writes, when they fit", async () => {
  await page.setViewportSize({ width: 1600, height: 1200 });
  try {
    await openHow(page, "main/H1036-153-0/ambulance/publish");
    await page.click(".how-pill:text-is('Read CMS fields')");
    await page.waitForFunction(() => document.querySelector(".how-step")?.textContent === "Read CMS fields");
    const map = await page.locator(".how-map").boundingBox();
    for (const box of [...await page.locator(".how-node.on").all(), page.locator(".how-pill.on")]) {
      const b = await box.boundingBox();
      assert.ok(b.y >= map.y && b.y + b.height <= map.y + map.height, `${await box.textContent()} at ${b.y}px, map shows ${map.y}-${map.y + map.height}px`);
    }
  } finally {
    await page.setViewportSize({ width: 1600, height: 1000 });
  }
});

test("pipeline view: an unknown step opens the first step", async () => {
  await openHow(page, "main/H1036-153-0/ambulance/nope");
  assert.equal(await page.textContent(".how-step"), "List the plans");
});

test("pipeline view: hovering a term shows its code, linked at the build's commit; clicking pins it and Escape closes it", async () => {
  await openHow(page, "main/H1036-153-0/ambulance/column-rules");
  const box = page.locator(".term-box", { has: page.locator("button", { hasText: "Ambulance rule" }) });
  const pop = box.locator(".term-pop");
  await box.hover();
  assert.ok(await pop.isVisible());
  assert.match(await pop.locator("pre").textContent(), /^def ambulance\(/);
  assert.match(await pop.locator("a").getAttribute("href"), /\/blob\/[0-9a-f]{7,40}\/pipeline\/present\.py#L\d+-L\d+$/);
  await page.mouse.move(0, 0);
  assert.ok(!(await pop.isVisible()));
  await box.locator("button").click();
  await page.mouse.move(0, 0);
  assert.ok(await pop.isVisible());
  assert.equal(await box.locator("button").getAttribute("aria-expanded"), "true");
  await page.keyboard.press("Escape");
  assert.ok(!(await pop.isVisible()));
});

test("pipeline view: a term's pop-over stays inside the window, and opening another closes it", async () => {
  await page.setViewportSize({ width: 1000, height: 700 });
  try {
    await openHow(page, "main/H1036-153-0/ambulance/check-facts");
    for (const name of ["quote check", "decoys", "reviewer"]) {
      await page.locator(".term", { hasText: name }).first().focus();
      const pops = page.locator(".term-pop:visible");
      assert.equal(await pops.count(), 1, name);
      const r = await pops.boundingBox();
      assert.ok(r.x >= 0 && r.x + r.width <= 1000 && r.y >= 0 && r.y + r.height <= 700, `${name}: ${JSON.stringify(r)}`);
    }
    await page.locator(".term", { hasText: "reviewer" }).first().click();
    await page.mouse.click(5, 690);
    assert.equal(await page.locator(".term-pop:visible").count(), 0);
  } finally {
    await page.setViewportSize({ width: 1600, height: 1000 });
  }
});

test("pipeline view: Extract page text links each PDF and text file to its blob", async () => {
  await openHow(page, "main/H1036-153-0/ambulance/extract-text");
  const hrefs = (side) => page.locator(`.how-rows.${side} td a`).evaluateAll((as) => as.map((a) => a.getAttribute("href")));
  assert.deepEqual((await hrefs("input")).map((h) => h.slice(0, 13)), ["docs/ce13e925", "docs/64e05773"]);
  assert.deepEqual((await hrefs("output")).map((h) => h.slice(0, 14)), ["blobs/6ebca98d", "blobs/d50cc84c"]);
  assert.match(await page.locator(".how-rows.output a.how-source").getAttribute("href"), /^blobs\/6ebca98d[0-9a-f]{56}\.txt$/);
});

test("pipeline view: each step shows its record from the cell's trace", async () => {
  await openHow(page, "main/H1036-153-0/ambulance/column-rules");
  assert.match(await page.textContent(".how-trace-head"), /rule\s*Traced/);
  assert.ok(!(await page.locator(".how-trace pre").isVisible()));
  await page.click(".how-trace summary");
  assert.match(await page.textContent(".how-trace pre"), /"set_aside"/);
  await openHow(page, "main/H1036-153-0/ambulance/read-facts");
  await page.waitForFunction(() => document.querySelector(".how-trace-head")?.textContent.includes("Not recorded in this build"));
  assert.equal(await page.locator(".how-trace pre").count(), 0);
});

test("pipeline view: a cell with no trace says so, and the next step loads it again", async () => {
  const fresh = await browser.newPage();
  opened.push(fresh);
  let fail = true;
  await fresh.route("**/trace/**", (route) => fail ? route.fulfill({ status: 404, body: "Not found" }) : route.continue());
  await fresh.goto(`${base}#/2027/how/main/H1036-153-0/ambulance/publish`);
  await fresh.waitForFunction(() => document.querySelector(".how-trace")?.textContent.includes("This build has no trace for this cell."));
  fail = false;
  await fresh.click("a.how-nav[rel=prev]");
  await fresh.waitForFunction(() => document.querySelector(".how-step")?.textContent === "Write notes");
  await fresh.waitForFunction(() => document.querySelector(".how-trace-head")?.textContent.includes("No step touched this cell"));
});

test("pipeline view: a record's status reads in words, and a record the trace lacks reads as not recorded", async () => {
  const fresh = await browser.newPage();
  opened.push(fresh);
  await fresh.route("**/trace/**", async (route) => {
    const trace = await (await route.fetch()).json();
    delete trace.rule;
    trace.plan = { status: "none" };
    await route.fulfill({ json: trace });
  });
  const head = async (step) => {
    await openHow(fresh, `main/H1036-153-0/ambulance/${step}`);
    return fresh.textContent(".how-trace-head");
  };
  assert.match(await head("column-rules"), /rule\s*Not recorded in this build/);
  assert.match(await head("list-plans"), /plan\s*No step touched this cell/);
});

test("pipeline view: a main-sheet cell's detail links to its pipeline view from a ? in its corner, at its last step", async () => {
  await page.goto("about:blank");
  await page.goto(`${base}#/2027/main/H5216-048-0/premium`);
  const link = page.locator("#how-this");
  assert.equal(await link.textContent(), "?");
  assert.equal(await link.getAttribute("title"), "How was this cell computed?");
  const [note, q] = [await page.locator("#source-note").boundingBox(), await link.boundingBox()];
  assert.ok(q.x + q.width <= note.x + note.width && q.x + q.width > note.x + note.width - 30, JSON.stringify([note, q]));
  assert.ok(q.y + q.height <= note.y + note.height && q.y + q.height > note.y + note.height - 30, JSON.stringify([note, q]));
  await link.click();
  await page.waitForSelector(".how-lens");
  assert.match(page.url(), /#\/2027\/how\/main\/H5216-048-0\/premium\/publish$/);
  assert.match(await page.textContent(".how-cell"), /Premium/);
});

test("pipeline view: a DVHA cell's detail links to its pipeline view, which shows the DVHA sheet and rule", async () => {
  await page.goto("about:blank");
  await page.goto(`${base}#/2027/dvha/H1036-153-0/vision`);
  await page.click("#how-this");
  await page.waitForSelector(".how-lens");
  assert.match(page.url(), /#\/2027\/how\/dvha\/H1036-153-0\/vision\/publish$/);
  assert.match(await page.textContent(".how-cell"), /Vision/);
  assert.ok((await page.locator(".how-pill").allTextContents()).includes("Apply column rules"));
  await openHow(page, "dvha/H1036-153-0/vision/column-rules");
  assert.deepEqual(await page.locator(".how-rows-head code").allTextContents(), ["document_facts", "rule code", "pbp_facts", "presented", "dvha", "caveats"]);
  assert.match(await page.textContent(".how-strip"), /becomes line 1 /);
  const code = page.locator(".how-rows", { has: page.locator('.how-rows-head code:text-is("rule code")') });
  assert.equal(await code.locator("td").first().textContent(), "G_vision in DVHA");
});

test("pipeline view: How it's made opens the selected cell's last step, or the example cell when none is selected", async () => {
  await page.goto("about:blank");
  await page.goto(`${base}#/2027/dvha/H1036-153-0/vision`);
  await page.click("nav a[data-view=how]");
  await page.waitForSelector(".how-lens");
  assert.match(page.url(), /#\/2027\/how\/dvha\/H1036-153-0\/vision\/publish$/);
  await page.goto(`${base}#/2027/main`);
  await page.waitForSelector("td[data-col]");
  assert.equal(await page.getAttribute("nav a[data-view=how]", "href"), "#/how");
});

test("pipeline view: a plan's page, which has no cell, has no ? link", async () => {
  await page.goto(`${base}#/2027/plan/H1036-153-0`);
  await page.waitForSelector("#viewer:not([hidden])");
  assert.ok(!(await page.locator("#how-this").isVisible()));
});

test("pipeline view: says it is loading, and a cell picked meanwhile stays", async () => {
  const fresh = await browser.newPage();
  opened.push(fresh);
  let release;
  const held = new Promise((r) => { release = r; });
  await fresh.route("**/trace/**", async (route) => { await held; await route.continue(); });
  await fresh.goto(`${base}#/2027/main`);
  await fresh.waitForSelector("td[data-col]");
  await fresh.click("nav a[data-view=how]");
  await fresh.waitForSelector(".how-loading");
  await fresh.evaluate(() => { location.hash = "#/2027/main"; });
  await fresh.waitForSelector("td[data-col]");
  release();
  await fresh.waitForTimeout(300);
  assert.equal(await fresh.locator(".how-lens").count(), 0);
  assert.match(fresh.url(), /#\/2027\/main$/);
});

test("a Notes link that names no sheet shows Notes", async () => {
  const fresh = await newPage();
  const errors = [];
  fresh.on("pageerror", (e) => errors.push(e.message));
  await fresh.goto(`${base}#/2027/notes/docs/H1036-153-0/ambulance`);
  await fresh.waitForSelector(".notes-page");
  assert.deepEqual(errors, []);
});

test("pipeline view: a link to no cell shows the example cell and says so", async () => {
  await openHow(page, "main/NOPE/ambulance/publish");
  assert.match(await page.textContent(".warn"), /names no cell/);
  assert.match(page.url(), /H1036-153-0\/ambulance\/publish$/);
  await openHow(page, "dvha/H1036-153-0/ambulance/publish");
  assert.match(page.url(), /how\/main\/H1036-153-0\/ambulance\/publish$/);
  await openHow(page, "docs/H1036-153-0/ambulance/publish");
  assert.match(await page.textContent(".warn"), /names no cell/);
});

test("pipeline view: a link may name the column by its key", async () => {
  await openHow(page, "main/H5216-048-0/C_premium");
  assert.match(page.url(), /H5216-048-0\/premium\/list-plans$/);
  assert.equal(await page.locator(".warn").count(), 0);
});

test("pipeline view: a replayed trace shows the reader prompt, each fact's verdicts, the rule's code and the facts it set aside", async () => {
  const fresh = await browser.newPage();
  opened.push(fresh);
  const replay = fs.readFileSync(path.join(path.dirname(new URL(import.meta.url).pathname), "fixtures/replay_trace.json"));
  await fresh.route("**/trace/**", (route) => route.fulfill({ body: replay, contentType: "application/json" }));
  const work = async (step) => {
    await openHow(fresh, `main/H1036-153-0/ambulance/${step}`);
    return fresh.locator(".how-details li").allTextContents();
  };
  assert.ok((await work("read-facts")).includes("EOC reader prompt for the ambulance group, answered by claude-opus-5-5 ↗"));
  assert.ok((await work("check-facts")).some((l) => l.startsWith("Rejected: SB page 6, ambulance $325. Verifier disagreed:")));
  await work("column-rules");
  const table = (name) => fresh.locator(".how-rows", { has: fresh.locator(`.how-rows-head code:text-is("${name}")`) });
  assert.match(await table("rule code").locator("a", { hasText: "present.py lines" }).getAttribute("href"), /present\.py#L\d+-L\d+$/);
  assert.ok((await table("document_facts").locator("tbody tr:not(.hi)").allTextContents()).some((r) => r.includes("SB ranks below EOC")));
});

const openPhone = (hash, colorScheme = "light") => newPage({ ...devices["iPhone 13"], colorScheme }).then(async (p) => {
  await p.goto(`${base}#/2027/${hash}`);
  await p.waitForSelector("table.sheet, .plan-page, .how-lens");
  return p;
});
const scrollsSideways = (p, selector) => p.$eval(selector, (e) => e.scrollWidth > e.clientWidth);

test("phone: only the sheets scroll sideways", async () => {
  const views = ["main", "dvha", "notes", "plan/H1036-153-0", ...["main/H1036-153-0/ambulance", "dvha/H1036-153-0/vision"]
    .flatMap((cell) => STEPS.map((s) => `how/${cell}/${s.id}`))];
  for (const view of views) {
    const p = await openPhone(view, "dark");
    assert.ok(!await scrollsSideways(p, "html"), view);
    if (!/^(main|dvha)$/.test(view)) assert.ok(!await scrollsSideways(p, "#content"), view);
    await p.close();
  }
});

test("phone: the header takes at most a fifth of the screen, upright or sideways", async () => {
  for (const device of ["iPhone SE (3rd gen)", "iPhone 13", "iPhone 13 landscape"]) {
    const p = await newPage(devices[device]);
    await p.goto(`${base}#/2027/main`);
    await p.waitForSelector("table.sheet");
    const header = await p.locator("header").boundingBox();
    assert.ok(header.height <= p.viewportSize().height / 5, `${device}: header is ${header.height}px tall`);
  }
});

test("phone: the plan column leaves most of the sheet's width to the cells", async () => {
  const p = await openPhone("main");
  const plan = await p.locator("tbody th.plan").first().boundingBox();
  assert.ok(plan.width <= p.viewportSize().width * 0.4, `plan column is ${plan.width}px wide`);
});

test("phone: a cell's document opens under the sheet at full width", async () => {
  const p = await openPhone("main");
  await p.locator("td.cited").first().click();
  await p.waitForSelector("#page-area .page canvas");
  const sheet = await p.locator("#content").boundingBox();
  const viewer = await p.locator("#viewer").boundingBox();
  assert.equal(viewer.width, p.viewportSize().width);
  assert.ok(viewer.y >= sheet.y + sheet.height, JSON.stringify({ sheet, viewer }));
  assert.ok(!await scrollsSideways(p, "#page-area"));
});

test("phone: the tapped cell stays in view above the document", async () => {
  const p = await openPhone("main");
  const cell = p.locator("tbody tr:nth-child(6) td.cited").first();
  await cell.tap();
  await p.waitForSelector("#viewer:not([hidden])");
  await p.evaluate(() => new Promise((r) => requestAnimationFrame(r)));
  const sheet = await p.locator("#content").boundingBox(), box = await cell.boundingBox();
  assert.ok(box.y >= sheet.y && box.y + box.height <= sheet.y + sheet.height + 1, JSON.stringify({ sheet, box }));
});

test("phone: the document's pages get a quarter of the screen, even with find open", async () => {
  const p = await openPhone("main");
  await p.locator("td.commented").first().tap();
  await p.waitForSelector("#page-area .page canvas");
  await p.click("#find-open");
  const pages = await p.locator("#page-area").boundingBox();
  assert.ok(pages.height >= p.viewportSize().height / 4, `pages are ${pages.height}px tall`);
});

test("phone: the Notes filter shows one kind", async () => {
  const p = await openPhone("notes");
  await p.selectOption("#kind-filter", "caveat");
  const kinds = await p.locator(".notes tbody tr:visible").evaluateAll((rows) => [...new Set(rows.map((r) => r.dataset.kind))]);
  assert.deepEqual(kinds, ["caveat"]);
});

test("phone: the map scrolls sideways to show the step", async () => {
  for (const s of STEPS) {
    const p = await openPhone(`how/main/H1036-153-0/ambulance/${s.id}`);
    const [rail, pill] = await Promise.all([p.locator(".how-map").boundingBox(), p.locator(".how-pill.on").boundingBox()]);
    assert.ok(pill.x >= rail.x && pill.x + pill.width <= rail.x + rail.width, `${s.id}: ${JSON.stringify([rail, pill])}`);
    await p.close();
  }
});

test("phone: pipeline view boxes fit their text", async () => {
  for (const s of STEPS) {
    const p = await openPhone(`how/main/H1036-153-0/ambulance/${s.id}`);
    const wide = await p.$$eval(".how-rows-head, .how-trace-head, .how-step",
      (els) => els.filter((e) => e.scrollWidth > e.clientWidth).map((e) => e.textContent));
    assert.deepEqual(wide, [], s.id);
    await p.close();
  }
});

test("pipeline view: a short file name stays on one line", async () => {
  const p = await newPage({ viewport: { width: 1000, height: 700 } });
  for (const s of STEPS) {
    await p.goto(`${base}#/2027/how/main/H1036-153-0/ambulance/${s.id}`);
    await p.waitForSelector(".how-lens");
    const broken = await p.$$eval(".how-rows-head code", (codes) => codes.filter((c) => c.textContent.length <= 15 && c.getClientRects().length > 1).map((c) => c.textContent));
    assert.deepEqual(broken, [], s.id);
  }
});

test("landscape phone: a term's pop-over leaves its term uncovered", async () => {
  const p = await newPage({ ...devices["iPhone 13 landscape"] });
  await p.goto(`${base}#/2027/how/main/H1036-153-0/ambulance/check-facts`);
  await p.waitForSelector(".how-lens");
  const term = p.locator(".term", { hasText: "quote check" }).first();
  // Scrolling closes a pop-over, so the scroll that brings the term into view must land before the tap.
  await term.scrollIntoViewIfNeeded();
  await p.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
  await term.tap();
  const pop = await p.locator(".term-pop:visible").boundingBox(), at = await term.boundingBox();
  assert.ok(pop.y >= at.y + at.height || pop.y + pop.height <= at.y, JSON.stringify({ pop, at }));
  assert.ok(pop.y >= 0 && pop.y + pop.height <= p.viewportSize().height, JSON.stringify(pop));
});

// The pdxplans Worker serves tables from D1, so these tests serve two builds' tables instead.
// The deployed build is the one the traces name, so How it's made links to it.
const DEPLOYED = JSON.parse(fs.readFileSync(path.join(SITE, "trace/2027/main/H1036-153-0/AB_ambulance.json"))).build.sha;
const OLDER = "e".repeat(40);
const EOC = Object.values(site.docs).find((d) => d.kind === "EOC" && d.plan_ids.includes("H1036-153-0"));
const factRows = (n) => Array.from({ length: n }, (_, i) => ({
  plan_id: i % 2 ? "H1036-153-0" : "H3805-048-0", benefit: i === 3 ? "ambulance.ground" : `b${i}`, amount: `$${(i * 37) % 1000}`,
  source: "EOC", doc_sha: EOC.sha256, page: String((i * 7) % 200 + 1), quotes: i === 3 ? `["${"a long quote ".repeat(20)}"]` : "[]" }));
const TABLE_DATA = {
  [DEPLOYED]: {
    plans: [{ plan_id: "H1036-153-0", plan_name: "Humana Total Complete (HMO)" }, { plan_id: "H3805-048-0", plan_name: "AARP" }],
    document_facts: factRows(250),
    presented: [{ sheet: "main", plan_id: "H1036-153-0", column: "AB_ambulance", value: "$325" },
                { sheet: "main", plan_id: "H1036-153-0", column: "C_premium", value: "$0" },
                { sheet: "dvha", plan_id: "H1036-153-0", column: "C_premium", value: "$0" }],
    documents: [{ plan_ids: "H1036-153-0;H3805-048-0", kind: "EOC", url: "x" }, { plan_ids: "H3805-048-0", kind: "SB", url: "y" }],
    cms_sources: [{ plan_id: "H1036-153-0", column: "C_premium", field: "Part C Premium" }],
  },
  [OLDER]: { presented: [{ sheet: "main", plan_id: "H1036-153-0", column: "AB_ambulance", value: "$300" }] },
};

async function serveTables(p, { builds = true } = {}) {
  await p.route("**/tables/2027/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/tables/2027/builds.json") {
      return builds ? route.fulfill({ json: { deployed: DEPLOYED, builds: [
        { sha: DEPLOYED, loaded: Date.now() - 3600e3, tables: Object.keys(TABLE_DATA[DEPLOYED]).toSorted() },
        { sha: OLDER, loaded: Date.now() - 86400e3, tables: ["presented"] }] } }) : route.fulfill({ status: 404, body: "Not found" });
    }
    const [, sha, table] = path.match(/^\/tables\/2027\/(\w+)\/(\w+)\.json$/) ?? [];
    const rows = TABLE_DATA[sha]?.[table];
    return rows ? route.fulfill({ json: rows }) : route.fulfill({ status: 404, body: "Not found" });
  });
}

const pageErrors = new WeakMap();
async function openTables(p, path) {
  if (!pageErrors.has(p)) {
    pageErrors.set(p, []);
    p.on("pageerror", (e) => pageErrors.get(p).push(String(e)));
  }
  await serveTables(p);
  await p.goto("about:blank");
  await p.goto(`${base}#/2027/tables${path ? `/${path}` : ""}`);
  await p.waitForSelector(".tables-scroll tbody tr");
}

const bodyColumn = (p, col) => p.locator(`.tables-scroll tbody td[data-col="${col}"]`).allTextContents();

const scope = (p, name, label) => p.locator(".how-rows", { has: p.locator(`.how-rows-head code:text-is("${name}")`) }).getByRole("radio", { name: label });
const framed = (p, name) => p.locator(".how-rows", { has: p.locator(`.how-rows-head code:text-is("${name}")`) });

test("pipeline view: a D1 table shows the cell's rows, or on asking its plan's or every plan's", async () => {
  const fresh = await newPage();
  await serveTables(fresh);
  await openHow(fresh, "main/H1036-153-0/ambulance/column-rules");
  const facts = framed(fresh, "document_facts");
  const where = facts.locator(".how-peek-pager span");
  const cellRows = await facts.locator("tbody tr").count();
  assert.ok(await scope(fresh, "document_facts", "This cell").isChecked());
  assert.equal(await facts.getByRole("group").getAttribute("aria-label"), "document_facts rows");
  await scope(fresh, "document_facts", "This plan").check();
  await where.waitFor();
  assert.equal(await facts.getByRole("status").textContent(), "125 rows");
  assert.equal(await where.textContent(), "Rows 1–100 of 125");
  assert.equal(await facts.locator("tbody tr").count(), 100);
  assert.deepEqual([...new Set(await facts.locator('td[data-col="plan_id"]').allTextContents())], ["H1036-153-0"]);
  assert.equal(await facts.locator('td[data-col="page"] a').first().getAttribute("href"), `#/2027/plan/H1036-153-0/EOC/${TABLE_DATA[DEPLOYED].document_facts[1].page}`);
  await facts.getByRole("button", { name: "Next →" }).click();
  assert.equal(await where.textContent(), "Rows 101–125 of 125");
  assert.equal(await fresh.evaluate(() => document.activeElement.textContent), "← Prev");
  await scope(fresh, "document_facts", "All plans").check();
  await where.filter({ hasText: "of 250" }).waitFor();
  assert.equal(await where.textContent(), "Rows 1–100 of 250");
  assert.equal(await facts.getByRole("link", { name: /Open in Tables/ }).getAttribute("href"), `#/2027/tables/${DEPLOYED}/document_facts`);
  await scope(fresh, "document_facts", "This plan").check();
  assert.equal(await facts.getByRole("link", { name: /Open in Tables/ }).getAttribute("href"), `#/2027/tables/${DEPLOYED}/document_facts/H1036-153-0`);
  await scope(fresh, "document_facts", "This cell").check();
  assert.equal(await facts.locator("tbody tr").count(), cellRows);
  assert.equal(await where.count(), 0);
  assert.equal(await facts.locator("[role=status]").textContent(), "");
  await fresh.close();
});

test("pipeline view: a D1 table with no rows for the plan says so", async () => {
  const fresh = await newPage();
  await serveTables(fresh);
  await fresh.route("**/tables/2027/*/pbp_facts.json", (route) => route.fulfill({ json: [{ plan_id: "H3805-048-0", benefit: "emergency" }] }));
  await openHow(fresh, "main/H1036-153-0/ambulance/column-rules");
  const facts = framed(fresh, "pbp_facts");
  await scope(fresh, "pbp_facts", "This plan").check();
  await facts.getByRole("status").filter({ hasText: "0 rows" }).waitFor();
  assert.equal(await facts.locator(".how-peek-pager button").count(), 0);
  assert.equal(await facts.getByRole("link", { name: /Open in Tables/ }).getAttribute("href"), `#/2027/tables/${DEPLOYED}/pbp_facts/H1036-153-0`);
  await fresh.close();
});

test("pipeline view: a table outside D1 offers no rows to ask for", async () => {
  await openHow(page, "main/H1036-153-0/ambulance/column-rules");
  assert.equal(await framed(page, "rule code").getByRole("radio").count(), 0);
  assert.equal(await framed(page, "presented").getByRole("radio").count(), 3);
});

test("pipeline view: a D1 table's rows that load after the visitor goes back to the cell's rows stay hidden", async () => {
  const fresh = await newPage();
  await serveTables(fresh);
  let release;
  const held = new Promise((r) => { release = r; });
  await fresh.route("**/tables/2027/*/document_facts.json", async (route) => {
    await held;
    await route.fallback();
  });
  await openHow(fresh, "main/H1036-153-0/ambulance/column-rules");
  const facts = framed(fresh, "document_facts");
  const cellRows = await facts.locator("tbody tr").count();
  await scope(fresh, "document_facts", "This plan").check();
  assert.equal(await facts.getByRole("status").textContent(), "Loading the table…");
  assert.equal(await facts.locator("tbody tr").count(), 0);
  await scope(fresh, "document_facts", "This cell").check();
  const loaded = fresh.waitForResponse("**/document_facts.json");
  release();
  await loaded;
  await fresh.evaluate(() => new Promise(requestAnimationFrame));
  assert.equal(await facts.locator("tbody tr").count(), cellRows);
  await fresh.close();
});

test("pipeline view: a D1 table that does not load says so, and a cell with no trace offers no rows to ask for", async () => {
  const fresh = await newPage();
  await serveTables(fresh);
  await openHow(fresh, "main/H1036-153-0/ambulance/column-rules");
  await scope(fresh, "pbp_facts", "All plans").check();
  await framed(fresh, "pbp_facts").getByRole("status").filter({ hasText: "The pbp_facts table did not load." }).waitFor();
  assert.equal(await framed(fresh, "pbp_facts").getByRole("link", { name: /Open in Tables/ }).getAttribute("href"), `#/2027/tables/${DEPLOYED}/pbp_facts`);
  await fresh.route("**/trace/2027/**", (route) => route.fulfill({ status: 404, body: "Not found" }));
  await openHow(fresh, "main/H1036-153-0/ambulance/column-rules");
  assert.equal(await fresh.getByRole("radio").count(), 0);
  await fresh.close();
});

test("tables view: the Tables link opens the deployed build's first table in the pipeline's order", async () => {
  const fresh = await newPage();
  await serveTables(fresh);
  await fresh.goto(base);
  await fresh.click("header nav a[data-view=tables]");
  await fresh.waitForSelector(".tables-scroll tbody tr");
  assert.equal(new URL(fresh.url()).hash, "#/2027/tables/plans");
  assert.deepEqual(await fresh.locator(".tables-list a[aria-current]").allTextContents(), ["plans"]);
  assert.deepEqual(await fresh.locator(".tables-list ul").first().locator("a").allTextContents(), ["plans", "documents", "document_facts", "cms_sources", "presented"]);
  assert.match(await fresh.locator("#tables-build option:checked").textContent(), new RegExp(`^${DEPLOYED.slice(0, 7)} · on the site now · loaded`));
});

test("tables view: a D1 table heading in How it's made opens the table, filtered to the cell", async () => {
  const fresh = await newPage();
  await serveTables(fresh);
  await openHow(fresh, "main/H1036-153-0/ambulance/publish");
  await fresh.locator('.how-source:has(code:text-is("presented"))').click();
  await fresh.waitForSelector(".tables-scroll tbody tr");
  assert.equal(new URL(fresh.url()).hash, `#/2027/tables/${DEPLOYED}/presented/H1036-153-0/main/AB_ambulance`);
  assert.deepEqual(await bodyColumn(fresh, "value"), ["$325"]);
  assert.equal(await fresh.textContent(".tables-count"), "1 of 3 match");
  assert.equal(await fresh.locator("#tables-column option:checked").textContent(), "Main chart · Ambulance Domestic/International");
  assert.equal(await fresh.locator("#tables-plan option:checked").textContent(), "H1036-153-0 · Humana Total Complete (HMO)");
  await fresh.goBack();
  await fresh.waitForSelector(".how-lens");
});

test("tables view: the column filter keeps one sheet's column, and a table without columns has no column filter", async () => {
  await openTables(page, "presented/all/dvha/C_premium");
  assert.deepEqual(await bodyColumn(page, "sheet"), ["dvha"]);
  await page.selectOption("#tables-column", "");
  await page.waitForFunction(() => location.hash === "#/2027/tables/presented");
  assert.equal((await bodyColumn(page, "value")).length, 3);
  await page.selectOption("#tables-column", "main/C_premium");
  await page.waitForFunction(() => location.hash === "#/2027/tables/presented/all/main/C_premium");
  await page.click('.tables-list a:has(code:text-is("document_facts"))');
  await page.waitForFunction(() => document.querySelector(".tables-head code")?.textContent === "document_facts");
  assert.equal(await page.locator("#tables-column").count(), 0);
  assert.equal(new URL(page.url()).hash, "#/2027/tables/document_facts");
  assert.equal(await page.evaluate(() => document.activeElement.getAttribute("aria-current")), "page");
});

test("tables view: a plan filter includes documents that cover several plans, and changes the link", async () => {
  await openTables(page, "documents");
  await page.focus("#tables-plan");
  await page.selectOption("#tables-plan", "H1036-153-0");
  await page.waitForFunction(() => location.hash === "#/2027/tables/documents/H1036-153-0");
  await page.waitForFunction(() => document.querySelectorAll(".tables-scroll tbody tr").length === 1);
  assert.deepEqual(await bodyColumn(page, "kind"), ["EOC"]);
  assert.equal(await page.evaluate(() => document.activeElement.id), "tables-plan");
});

test("tables view: a header sorts its column as numbers, and again in reverse", async () => {
  await openTables(page, "document_facts/H1036-153-0");
  const header = page.locator('.tables-scroll th:has(code:text-is("page"))');
  await header.locator("button").click();
  assert.equal(await header.getAttribute("aria-sort"), "ascending");
  assert.equal(await page.locator(".tables-scroll th[aria-sort]").count(), 1);
  const pages = (await bodyColumn(page, "page")).map(Number);
  assert.deepEqual(pages, pages.toSorted((a, b) => a - b));
  assert.ok(pages.some((n) => n >= 10) && pages.some((n) => n < 10));
  await header.locator("button").click();
  assert.equal(await header.getAttribute("aria-sort"), "descending");
  const reversed = (await bodyColumn(page, "page")).map(Number);
  assert.deepEqual(reversed, reversed.toSorted((a, b) => b - a));
  assert.ok(reversed[0] > pages[0]);
  assert.equal(await page.evaluate(() => document.activeElement.textContent), "page");
});

test("tables view: pages hold 100 rows, and a search goes back to the first page", async () => {
  await openTables(page, "document_facts");
  assert.equal(await page.textContent(".tables-pager span"), "Rows 1–100 of 250");
  await page.click('.tables-pager button:text-is("Next →")');
  await page.click('.tables-pager button:text-is("Next →")');
  assert.equal(await page.textContent(".tables-pager span"), "Rows 201–250 of 250");
  assert.ok(await page.locator('.tables-pager button:text-is("Next →")').isDisabled());
  await page.fill("#tables-search", "AMBULANCE");
  assert.equal(await page.textContent(".tables-pager span"), "Rows 1–1 of 1");
  assert.equal(await page.textContent(".tables-count"), "1 of 250 match");
});

test("tables view: the column menu hides a column", async () => {
  await openTables(page, "document_facts");
  await page.click(".tables-columns summary");
  await page.uncheck('.tables-columns input[value="quotes"]');
  assert.equal(await page.locator('.tables-scroll th:has(code:text-is("quotes"))').count(), 0);
  assert.equal(await page.textContent(".tables-columns summary"), "Columns · 6 of 7");
});

test("tables view: Download CSV saves the shown rows and columns", async () => {
  const fresh = await newPage();
  await openTables(fresh, "documents/H3805-048-0");
  const [download] = await Promise.all([fresh.waitForEvent("download"), fresh.click('button:text-is("Download CSV")')]);
  assert.equal(download.suggestedFilename(), `documents-${DEPLOYED.slice(0, 7)}.csv`);
  const text = fs.readFileSync(await download.path(), "utf8");
  assert.equal(text, "plan_ids,kind,url\r\nH1036-153-0;H3805-048-0,EOC,x\r\nH3805-048-0,SB,y\r\n");
});

test("tables view: the build menu shows an older build's table", async () => {
  const fresh = await newPage();
  await openTables(fresh, "presented");
  const length = await fresh.evaluate(() => history.length);
  await fresh.selectOption("#tables-build", OLDER);
  await fresh.waitForFunction(() => document.querySelector('.tables-scroll td[data-col="value"]')?.textContent === "$300");
  assert.equal(new URL(fresh.url()).hash, `#/2027/tables/${OLDER}/presented`);
  assert.equal(await fresh.evaluate(() => history.length), length);
  assert.deepEqual(await fresh.locator(".tables-list ul").first().locator("a").allTextContents(), ["presented"]);
});

test("tables view: says so when this server has no tables", async () => {
  const fresh = await newPage();
  await serveTables(fresh, { builds: false });
  await fresh.goto(`${base}#/2027/tables/presented`);
  await fresh.waitForSelector(".tables-note.warn");
  assert.equal(await fresh.textContent(".tables-note"), "The list of builds did not load. Try again later.");
});

test("tables view: a table that fails to load says so, and loads on the next visit", async () => {
  const fresh = await newPage();
  let fail = true;
  await serveTables(fresh);
  await fresh.route(`**/tables/2027/${DEPLOYED}/plans.json`, (route) => fail ? route.fulfill({ status: 500, body: "" }) : route.fallback());
  await fresh.goto(`${base}#/2027/tables/plans`);
  await fresh.waitForSelector(".tables-note.warn");
  assert.equal(await fresh.textContent(".tables-note"), "The plans table did not load. Try again later.");
  fail = false;
  await fresh.goto(`${base}#/2027/main`);
  await fresh.goto(`${base}#/2027/tables/plans`);
  await fresh.waitForSelector(".tables-scroll tbody tr");
});

test("tables view: a build may be named by the start of its commit", async () => {
  await openTables(page, `${DEPLOYED.slice(0, 7).toUpperCase()}/documents`);
  assert.equal(new URL(page.url()).hash, `#/2027/tables/${DEPLOYED}/documents`);
  assert.equal(await page.locator(".tables-main > .warn").count(), 0);
});

test("tables view: rendering, filtering and following links raise no page errors", async () => {
  const fresh = await newPage();
  await openTables(fresh, "documents");
  await fresh.click('.tables-list a:has(code:text-is("plans"))');
  await fresh.waitForFunction(() => document.querySelector(".tables-head code")?.textContent === "plans");
  await fresh.selectOption("#tables-plan", "H1036-153-0");
  await fresh.waitForFunction(() => location.hash === "#/2027/tables/plans/H1036-153-0");
  assert.deepEqual(pageErrors.get(fresh), []);
});

test("tables view: an unknown build, table or plan in a link shows what is kept and says so", async () => {
  const fresh = await newPage();
  await serveTables(fresh);
  await fresh.goto(`${base}#/2027/tables/${"f".repeat(40)}/nope/BOGUS`);
  await fresh.waitForSelector(".tables-scroll tbody tr");
  assert.equal(new URL(fresh.url()).hash, "#/2027/tables/plans");
  assert.deepEqual(await fresh.locator(".tables-main > .warn").allTextContents(), [
    `D1 no longer keeps build fffffff, so this shows build ${DEPLOYED.slice(0, 7)}.`,
    `Build ${DEPLOYED.slice(0, 7)} has no nope table.`,
    "The plans table has no rows for BOGUS."]);
  assert.equal(await fresh.locator("#tables-plan option:checked").textContent(), "All plans");
  await fresh.goto(`${base}#/2027/tables/presented/all/main/NOPE`);
  await fresh.waitForFunction(() => location.hash === "#/2027/tables/presented");
  assert.deepEqual(await fresh.locator(".tables-main > .warn").allTextContents(), ["The presented table has no rows for that column."]);
});

test("tables view: a long value shows its start, and the row's one button shows the whole row", async () => {
  await openTables(page, "document_facts/H1036-153-0");
  const row = page.locator(".tables-scroll tbody tr").nth(1);
  const more = row.locator(".tables-more");
  const quote = row.locator('td[data-col="quotes"] > div');
  assert.equal(await more.count(), 1);
  assert.equal(await more.getAttribute("aria-expanded"), "false");
  const shut = (await quote.boundingBox()).height;
  await more.focus();
  await page.keyboard.press("Enter");
  assert.equal(await more.getAttribute("aria-expanded"), "true");
  assert.ok((await quote.boundingBox()).height > shut * 2);
});

test("tables view: a page number opens the plan's document at that page", async () => {
  await openTables(page, "document_facts/H1036-153-0");
  const link = page.locator('.tables-scroll td[data-col="page"] a').first();
  const n = await link.textContent();
  assert.equal(await link.getAttribute("href"), `#/2027/plan/H1036-153-0/EOC/${n}`);
});

test("phone: tables show each row as a card, and the page does not scroll sideways", async () => {
  const phone = await newPage({ ...devices["iPhone 13"] });
  await openTables(phone, "document_facts/H1036-153-0");
  assert.equal(await phone.locator(".tables-scroll thead").isVisible(), false);
  assert.ok(await phone.locator("#tables-sort").isVisible());
  const widths = await phone.evaluate(() => [document.documentElement.scrollWidth, document.querySelector("#content").scrollWidth, innerWidth]);
  assert.ok(widths[0] <= widths[2] && widths[1] <= widths[2], String(widths));
  await phone.selectOption("#tables-sort", "page descending");
  const pages = (await bodyColumn(phone, "page")).map(Number);
  assert.deepEqual(pages, pages.toSorted((a, b) => b - a));
});

test("tables view: another plan starts at the first page, and replaces the history entry", async () => {
  const fresh = await newPage();
  await openTables(fresh, "document_facts");
  await fresh.click('.tables-pager button:text-is("Next →")');
  const length = await fresh.evaluate(() => history.length);
  await fresh.selectOption("#tables-plan", "H1036-153-0");
  await fresh.waitForFunction(() => location.hash === "#/2027/tables/document_facts/H1036-153-0");
  await fresh.waitForFunction(() => document.querySelector(".tables-pager span").textContent === "Rows 1–100 of 125");
  assert.equal(await fresh.evaluate(() => history.length), length);
});

test("tables view: Next on the last page leaves focus on Prev", async () => {
  await openTables(page, "document_facts");
  await page.focus('.tables-pager button:text-is("Next →")');
  await page.keyboard.press("Enter");
  await page.keyboard.press("Enter");
  assert.equal(await page.evaluate(() => document.activeElement.textContent), "← Prev");
});

test("phone: paging to the last page of a table keeps its row count in view", async () => {
  const p = await newPage(devices["iPhone 13"]);
  await openTables(p, "document_facts");
  for (const _ of [1, 2]) await p.click('.tables-pager button:text-is("Next →")');
  assert.ok(await p.locator(".tables-count").evaluate((e) => e.getBoundingClientRect().top >= 0));
  await p.close();
});

test("tables view: hiding the sorted column unsorts, and the last column cannot be hidden", async () => {
  await openTables(page, "plans");
  await page.click('.tables-scroll th button:has(code:text-is("plan_name"))');
  assert.deepEqual(await bodyColumn(page, "plan_id"), ["H3805-048-0", "H1036-153-0"]);
  await page.click(".tables-columns summary");
  await page.uncheck('.tables-columns input[value="plan_name"]');
  assert.deepEqual(await bodyColumn(page, "plan_id"), ["H1036-153-0", "H3805-048-0"]);
  assert.ok(await page.locator('.tables-columns input[value="plan_id"]').isDisabled());
  await page.check('.tables-columns input[value="plan_name"]');
});

test("tables view: a table without a sheet field labels its columns as the main sheet's", async () => {
  await openTables(page, "cms_sources");
  assert.deepEqual(await page.locator("#tables-column option").allTextContents(), ["All columns", "Main chart · Premium"]);
});

test("tables view: the header's Tables link returns to the last table shown", async () => {
  const fresh = await newPage();
  await openTables(fresh, "documents/H1036-153-0");
  await fresh.click("header nav a[data-view=main]");
  await fresh.click("header nav a[data-view=tables]");
  await fresh.waitForSelector(".tables-scroll tbody tr");
  assert.equal(new URL(fresh.url()).hash, "#/2027/tables/documents/H1036-153-0");
});
