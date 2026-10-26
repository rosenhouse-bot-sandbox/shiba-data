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

test("clicking a cited cell highlights the quote on its page", async () => {
  await page.goto(`${base}#/main`);
  await row("H2001-045-0").locator("td.cited").first().click();
  await shown(docOf("H2001-045-0", "SB"), 6);
  assert.match((await page.locator(".textLayer mark").allTextContents()).join(" "), /\$1,980 copay per stay/);
});

test("clicking an uncited cell opens the summary of benefits with a note", async () => {
  await page.goto(`${base}#/main`);
  await row("H3805-048-0").locator("td").first().click();
  await shown(docOf("H3805-048-0", "SB"), 1);
  assert.match(await page.textContent("#source-note"), /CMS 2027 Plan Benefit Package/);
  assert.match(await page.textContent("#doc-title"), /^Summary of Benefits/);
});

test("plan page lists the plan's documents", async () => {
  await page.goto(`${base}#/plan/H2001-045-0`);
  const docs = await page.locator("table.docs").textContent();
  assert.match(docs, /Summary of Benefits/);
  assert.match(docs, /Evidence of Coverage/);
});

test("every citation's quote is found on its page", { timeout: 600_000 }, async () => {
  const missing = [];
  await page.goto(`${base}#/main`);
  for (const r of site.main.rows) {
    for (const [col, cell] of Object.entries(r.cells)) {
      cell.cites.forEach((c) => (c.key = `${r.plan_id} ${col} ${c.doc} p${c.page}`));
      if (!cell.cites.length) continue;
      const index = site.main.columns.findIndex((c) => c.key === col);
      await row(r.plan_id).locator("td").nth(index).click();
      for (let i = 0; i < cell.cites.length; i++) {
        if (i) await page.locator("#source-note a").nth(i).click();
        await shown(cell.cites[i].doc, cell.cites[i].page);
        if (!(await page.locator(".textLayer mark").count())) missing.push(cell.cites[i].key);
      }
    }
  }
  assert.deepEqual(missing, []);
});
