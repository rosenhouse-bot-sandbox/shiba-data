// Drives the built site in Chromium. Usage: SITE=<build dir with --pdfs> node --test web/tests/e2e.test.mjs
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const SITE = process.env.SITE;
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".pdf": "application/pdf" };
let server, browser, page, base;
const site = JSON.parse(fs.readFileSync(path.join(SITE, "data.json")));

before(async () => {
  server = http.createServer((req, res) => {
    const file = path.join(SITE, decodeURIComponent(new URL(req.url, "http://x").pathname).replace(/\/$/, "/index.html"));
    fs.readFile(file, (err, body) => {
      res.writeHead(err ? 404 : 200, { "Content-Type": TYPES[path.extname(file)] || "application/octet-stream" });
      res.end(body);
    });
  });
  await new Promise((r) => server.listen(0, r));
  base = `http://localhost:${server.address().port}/`;
  const proxy = process.env.HTTPS_PROXY ? { server: process.env.HTTPS_PROXY, bypass: "localhost" } : undefined;
  browser = await chromium.launch({ proxy });
  page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
});

after(async () => {
  await browser?.close();
  server?.close();
});

const shown = (doc, n) => page.waitForSelector(`#page-area[data-shown="${doc} ${n}"]`);
const docOf = (planId, kind) => Object.entries(site.docs).find(([, d]) => d.kind === kind && d.plan_ids.includes(planId))[0];
const row = (planId) => page.locator("table.sheet tr", { has: page.locator("small", { hasText: planId }) });
const UNCITED = "td:not(.cited):not(.commented)";

test("clicking a cited cell highlights the quote on its page", async () => {
  await page.goto(`${base}#/main`);
  await row("H2001-045-0").locator("td.cited", { hasText: "$1,980" }).click();
  await shown(docOf("H2001-045-0", "EOC"), 77);
  assert.match((await page.locator(".textLayer mark").allTextContents()).join(" "), /\$1,980 copayment/);
});

test("clicking a DVHA cell with an EOC citation highlights the quote", async () => {
  await page.goto(`${base}#/dvha`);
  await row("H3805-048-0").locator("td.cited", { hasText: "Routine foot care" }).click();
  await shown(docOf("H3805-048-0", "EOC"), 84);
  assert.match((await page.locator(".textLayer mark").allTextContents()).join(" "), /\$45 copayment/);
});

test("clicking an uncited cell opens the summary of benefits with a note", async () => {
  await page.goto(`${base}#/main`);
  await row("H3805-048-0").locator(UNCITED).first().click();
  await shown(docOf("H3805-048-0", "SB"), 1);
  assert.match(await page.textContent("#source-note"), /CMS 2027 Plan Benefit Package/);
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
  await page.locator("#source-note p.cite a", { hasText: "EOC" }).click();
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

test("yellow marks a comment, shown on hover and in the note", async () => {
  await page.goto(`${base}#/main`);
  const index = site.main.columns.findIndex((c) => c.key === "K_tests_labs");
  const cell = row("H6815-038-0").locator("td").nth(index);
  assert.match(await cell.getAttribute("class"), /commented/);
  assert.match(await cell.getAttribute("title"), /EKG/);
  assert.equal(await page.locator("td.commented").count(), site.main.rows.flatMap((r) => Object.values(r.cells)).filter((c) => c.comment).length);
  const background = (td) => td.evaluate((e) => getComputedStyle(e).backgroundColor);
  assert.notEqual(await background(row("H2001-045-0").locator("td.cited").first()), await background(cell));
  await cell.click();
  assert.match(await page.textContent("#source-note .comment"), /EKG/);
  const { doc, page: n, quote } = site.main.rows.find((r) => r.plan_id === "H6815-038-0").cells.K_tests_labs.comment;
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
const cellTd = (planId, col) => page.locator(`table.sheet td[data-plan="${planId}"][data-col="${col}"]`);

test("Ambiguities lists every comment with links to its document page and cell", async () => {
  const comments = ["main", "dvha"].flatMap(allCells).filter(({ cell }) => cell.comment);
  await page.goto(`${base}#/main`);
  await page.click("nav a[data-view=ambiguities]");
  const rows = page.locator("table.ambiguities tbody tr");
  await rows.first().waitFor();
  assert.equal(await rows.count(), comments.length);
  const wellcare = rows.filter({ has: page.locator('td[data-plan="H6815-038-0"][data-col="K_tests_labs"]') });
  assert.match(await wellcare.textContent(), /EKGs/);
  await wellcare.locator("td.links a", { hasText: "EOC page 83" }).click();
  await shown(docOf("H6815-038-0", "EOC"), 83);
  await wellcare.locator("td.links a", { hasText: "Show in Main chart" }).click();
  await page.waitForSelector("table.sheet td.selected");
  assert.match(await cellTd("H6815-038-0", "K_tests_labs").getAttribute("class"), /selected/);
});

test("going back to Ambiguities keeps the scroll position", async () => {
  await page.goto(`${base}#/ambiguities`);
  const target = page.locator("table.ambiguities tbody tr").nth(60);
  await target.scrollIntoViewIfNeeded();
  const before = await page.$eval("#content", (c) => c.scrollTop);
  assert.ok(before > 0);
  await target.locator("td.links a", { hasText: "Show in" }).click();
  await page.waitForSelector("table.sheet td.selected");
  await page.goBack();
  await page.waitForSelector("table.ambiguities");
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
  const fresh = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  await fresh.route("**/data.json", (route) => {
    const edited = structuredClone(site);
    edited.main.rows.find((r) => r.plan_id === "H6815-038-0").cells.K_tests_labs.comment.text = "See EOC page 82 for EKGs.";
    route.fulfill({ json: edited });
  });
  await fresh.goto(`${base}#/main`);
  await fresh.locator('table.sheet td[data-plan="H6815-038-0"][data-col="K_tests_labs"]').click();
  await fresh.waitForSelector(`#page-area[data-shown="${docOf("H6815-038-0", "EOC")} 83"]`);
  await fresh.locator("#source-note .comment a", { hasText: "EOC page 82" }).click();
  await fresh.waitForSelector(`#page-area[data-shown="${docOf("H6815-038-0", "EOC")} 82"]`);
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
  const fresh = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
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

test("browser zoom enlarges the document pages", async () => {
  const pageWidthRatio = async (zoom) => {
    const fresh = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
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
  const fresh = await browser.newPage({ timezoneId: "America/Los_Angeles" });
  await fresh.route("**/data.json", (route) =>
    route.fulfill({ json: { ...site, built: new Date(Date.now() - 3 * 3600000).toISOString() } }));
  await fresh.clock.install();
  await fresh.goto(`${base}#/main`);
  const label = fresh.locator("header #updated");
  assert.equal(await label.textContent(), "Last updated 3 hours ago");
  assert.match(await label.getAttribute("title"), /\b(PDT|PST)\b/);
  await fresh.clock.runFor(60 * 60000);
  assert.equal(await label.textContent(), "Last updated 4 hours ago");
  await fresh.close();
});

test("orange marks a comment that contradicts the cell", async () => {
  const fresh = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  const edited = structuredClone(site);
  edited.main.rows.find((r) => r.plan_id === "H6815-038-0").cells.K_tests_labs.comment.kind = "contradicts";
  await fresh.route("**/data.json", (route) => route.fulfill({ json: edited }));
  await fresh.goto(`${base}#/main`);
  const background = (locator) => locator.evaluate((e) => getComputedStyle(e).backgroundColor);
  const contradicts = fresh.locator('table.sheet td[data-plan="H6815-038-0"][data-col="K_tests_labs"]');
  const note = fresh.locator("table.sheet td.commented:not(.contradicts)").first();
  const orange = await background(contradicts);
  assert.notEqual(orange, await background(note));
  await note.click();
  assert.equal(await background(fresh.locator("#source-note .comment")), await background(note));
  await contradicts.click();
  assert.equal(await background(fresh.locator("#source-note .comment")), orange);
  assert.equal(await background(contradicts), orange, "stays orange in the open plan's row");
  await fresh.click("nav a[data-view=ambiguities]");
  const rows = fresh.locator("table.ambiguities tbody tr");
  await fresh.selectOption("#kind-filter", "contradicts");
  const contradictions = ["main", "dvha"].flatMap((sheet) => edited[sheet].rows.flatMap((r) => Object.values(r.cells)))
    .filter((c) => c.comment?.kind === "contradicts");
  const shown = await rows.filter({ visible: true }).allTextContents();
  assert.equal(shown.length, contradictions.length);
  assert.ok(shown.every((t) => t.includes("Contradicts the EOC")));
  await rows.filter({ visible: true }).first().locator("a", { hasText: "Show in" }).click();
  await fresh.goBack();
  assert.equal(await fresh.locator("#kind-filter").inputValue(), "contradicts");
  assert.equal(await rows.filter({ visible: true }).count(), contradictions.length);
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
          // A re-issued PDF may have moved the quote; the viewer warns about it instead.
          if (site.docs[c.doc].changed) continue;
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
  const fresh = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  const slow = docOf("H7006-018-0", "SB");
  await fresh.route(`**/pdfs/${slow}.pdf`, async (route) => {
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

test("the viewer warns about changed and missing copies", async () => {
  const fresh = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  const [changed, missing] = site.plans.find((p) => p.plan_id === "H2001-045-0").docs;
  await fresh.route("**/data.json", (route) => {
    const edited = structuredClone(site);
    edited.docs[changed].changed = true;
    edited.docs[missing].file = null;
    route.fulfill({ json: edited });
  });
  await fresh.goto(`${base}#/plan/H2001-045-0`);
  await fresh.locator("table.docs a", { hasText: kindName(site.docs[changed].kind) }).click();
  await fresh.waitForSelector(`#page-area[data-shown="${changed} 1"]`);
  assert.match(await fresh.textContent("#source-note"), /carrier has changed this file/);
  await fresh.locator("table.docs a", { hasText: kindName(site.docs[missing].kind) }).click();
  assert.match(await fresh.textContent("#page-area"), /No copy of this document is hosted here/);
  assert.equal(await fresh.getAttribute("#viewer a#doc-source", "href"), site.docs[missing].url);
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

test("a blank uncited cell says CMS data has no entry", async () => {
  await page.goto(`${base}#/dvha`);
  const index = site.dvha.columns.findIndex((c) => c.key === "F_dental");
  await row("H3805-048-0").locator("td").nth(index).click();
  assert.match(await page.textContent("#source-note"), /has no entry for this benefit/);
});

test("a cited blank cell says the document shows why", async () => {
  await page.goto(`${base}#/main`);
  const index = site.main.columns.findIndex((c) => c.key === "U_naturopath");
  await row("H2056-003-0").locator("td").nth(index).click();
  assert.match(await page.textContent("#source-note"), /shows why this is blank/);
});

test("a cell's note restates the CMS plan data without our symbols", async () => {
  const withPbp = (match) => ["main", "dvha"].flatMap((sheet) => site[sheet].rows.flatMap((r) =>
    Object.entries(r.cells).filter(([, c]) => c.cites.length && match(c.pbp ?? null)).map(([col]) => `#/${sheet}/${r.plan_id}/${col}`)))[0];
  for (const [hash, expected] of [
    [withPbp((p) => p === "●"), /CMS plan data shows this benefit is covered\./],
    [withPbp((p) => p === "20%"), /CMS plan data shows 20%\./],
    [withPbp((p) => p === ""), /CMS plan data leaves this blank/],
  ]) {
    await page.goto(`${base}${hash}`);
    const pbp = await page.locator("#source-note p.pbp").textContent();
    assert.match(pbp, expected);
    assert.doesNotMatch(pbp, /[●◐“]/);
  }
});

test("closing the viewer hides it", async () => {
  await page.click("#close");
  assert.equal(await page.isHidden("#viewer"), true);
});

const kindName = (k) => ({ SB: "Summary of Benefits", EOC: "Evidence of Coverage" })[k];
