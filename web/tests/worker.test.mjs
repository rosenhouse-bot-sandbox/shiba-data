import { test } from "node:test";
import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import worker from "../worker.js";

const SHA = "a".repeat(64);
const PDF = "%PDF-1.4 0123456789";

// Mimics R2's get: options.range and options.onlyIf are request headers, and a whole object still has a range.
async function get(key, { range, onlyIf }) {
  if (key !== `blobs/${SHA}`) return null;
  const meta = { size: PDF.length, httpEtag: '"e"' };
  if (onlyIf.get("If-None-Match") === '"e"') return meta;
  const m = range.get("Range")?.match(/^bytes=(\d+)-(\d+)$/);
  if (!m) return { ...meta, body: PDF, range: { offset: 0, length: PDF.length } };
  const [offset, end] = [Number(m[1]), Number(m[2])];
  return { ...meta, body: PDF.slice(offset, end + 1), range: { offset, length: end - offset + 1 } };
}

const env = { ASSETS: { fetch: async (request) => new Response(`asset ${new URL(request.url).pathname}`) }, BLOBS: { get }, TRACE: d1() };
const fetchPath = (path, init) => worker.fetch(new Request(`https://pdxplans.org${path}`, init), env);
const DOC = `/docs/${SHA}.pdf`;
const TRACE = "/trace/2027/main/H1036-153-0/AB_ambulance";

test("serves a PDF from its blob", async () => {
  const response = await fetchPath(DOC);
  assert.equal(response.status, 200);
  assert.equal(await response.text(), PDF);
  assert.equal(response.headers.get("Content-Type"), "application/pdf");
  assert.equal(response.headers.get("Cache-Control"), "public, max-age=31536000, immutable");
  assert.equal(response.headers.get("ETag"), '"e"');
  assert.equal(response.headers.get("Accept-Ranges"), "bytes");
});

test("serves a byte range", async () => {
  const response = await fetchPath(DOC, { headers: { Range: "bytes=2-5" } });
  assert.equal(response.status, 206);
  assert.equal(response.headers.get("Content-Range"), `bytes 2-5/${PDF.length}`);
  assert.equal(await response.text(), "DF-1");
});

test("answers 304 when the client's copy is current", async () => {
  assert.equal((await fetchPath(DOC, { headers: { "If-None-Match": '"e"' } })).status, 304);
});

test("answers HEAD without a body", async () => {
  const response = await fetchPath(DOC, { method: "HEAD" });
  assert.equal(response.status, 200);
  assert.equal(await response.text(), "");
});

test("answers 404 for a hash with no blob", async () => {
  assert.equal((await fetchPath(`/docs/${"b".repeat(64)}.pdf`)).status, 404);
});

test("serves a prompt blob as UTF-8 text", async () => {
  const response = await fetchPath(`/blobs/${SHA}.txt`);
  assert.equal(response.status, 200);
  assert.equal(await response.text(), PDF);
  assert.equal(response.headers.get("Content-Type"), "text/plain; charset=utf-8");
});

test("serves everything else from the site's assets", async () => {
  for (const path of ["/data.json", `/docs/${SHA.slice(16)}.pdf`, `/x${DOC}`, `${TRACE}.json`, "/trace/2027/main/x",
                      `/blobs/${SHA}.pdf`, `/docs/${SHA}.txt`]) {
    assert.equal(await (await fetchPath(path)).text(), `asset ${path}`);
  }
});

test("answers 405 to a method other than GET or HEAD, except for a load", async () => {
  for (const [method, path] of [["POST", DOC], ["POST", TRACE], ["POST", "/data.json"], ["PUT", `/blobs/${SHA}.txt`],
                                ["DELETE", "/"], ["PUT", `/trace/2027/load/${"1".repeat(40)}`]]) {
    const response = await fetchPath(path, { method });
    assert.equal(response.status, 405, `${method} ${path}`);
    assert.equal(response.headers.get("Allow"), "GET, HEAD");
  }
});

test("serves a cell's trace from its static file", async () => {
  assert.equal(await (await fetchPath(TRACE)).text(), `asset ${TRACE}.json`);
});

test("passes a trace request's method and headers to the assets", async () => {
  const seen = [];
  const assets = { fetch: async (request) => (seen.push(request), new Response("")) };
  await worker.fetch(new Request(`https://pdxplans.org${TRACE}`, { method: "HEAD", headers: { "If-None-Match": '"e"' } }), { ...env, ASSETS: assets });
  assert.equal(seen[0].method, "HEAD");
  assert.equal(seen[0].headers.get("If-None-Match"), '"e"');
});

// The fake D1 database runs on node:sqlite, with the binding's prepare, bind, first, all, run and batch.
// It counts the rows that statements change. It runs afterQuery, if set, after each query's results, and beforeBatch
// before each batch.
function d1() {
  const db = new DatabaseSync(":memory:");
  const fake = { db, batches: 0, written: 0, afterQuery: null, beforeBatch: null };
  const statement = (sql, args = []) => ({
    sql,
    // Like D1, bind throws at once on undefined.
    bind: (...values) => {
      if (values.includes(undefined)) throw new TypeError("D1_TYPE_ERROR: Type 'undefined' not supported");
      return statement(sql, values);
    },
    first: async () => db.prepare(sql).get(...args) ?? null,
    all: async () => {
      const results = db.prepare(sql).all(...args);
      fake.afterQuery?.();
      return { results };
    },
    // SQLite reports the last insert's or delete's count for a CREATE or DROP too.
    run: async () => {
      const { changes } = db.prepare(sql).run(...args);
      if (/^(INSERT|DELETE)/.test(sql)) fake.written += Number(changes);
      return { success: true };
    },
  });
  fake.prepare = (sql) => statement(sql);
  fake.batch = async (statements) => {
    fake.batches++;
    fake.beforeBatch?.(statements);
    db.exec("BEGIN");
    try {
      for (const s of statements) await s.run();
      db.exec("COMMIT");
    } catch (e) {
      db.exec("ROLLBACK");
      throw e;
    }
  };
  return fake;
}

// The fake R2 bucket holds text objects.
function bucket(objects) {
  const object = (key) => ({ text: async () => objects[key], json: async () => JSON.parse(objects[key]) });
  return {
    objects,
    get: async (key) => key in objects ? object(key) : null,
    // Lists two keys a page, so the tests page through the listing.
    list: async ({ prefix, cursor = "" }) => {
      const keys = Object.keys(objects).filter((k) => k.startsWith(prefix) && k > cursor).sort();
      return { objects: keys.slice(0, 2).map((key) => ({ key })), truncated: keys.length > 2, cursor: keys[1] };
    },
    delete: async (keys) => [keys].flat().forEach((k) => delete objects[k]),
  };
}

const OLD = "1".repeat(40), NEW = "2".repeat(40), THIRD = "3".repeat(40), TOKEN = "t".repeat(64);
const PLANS = Array.from({ length: 12 }, (_, n) => `H1036-${String(n).padStart(3, "0")}-0`);
const hash = (n, version) => `${version}${String(n).padStart(2, "0")}`.padEnd(64, "0");
// Every other cell is on the DVHA sheet.
const cellKey = (n) => `${n % 2 ? "dvha" : "main"}/${PLANS[n]}/AB_ambulance`;
// Uploads a build of 12 cells, as CI does. changed lists the cells at version 2, and the rest are at version 1.
function upload(e, sha, changed = []) {
  const cells = Object.fromEntries(PLANS.map((_, n) => [cellKey(n), hash(n, changed.includes(n) ? 2 : 1)]));
  for (const [n, v] of PLANS.map((_, n) => [n, changed.includes(n) ? 2 : 1])) {
    e.BLOBS.objects[`trace/2027/items/${hash(n, v)}.json`] = JSON.stringify({ n, v, code: "blob/${commit}/", sha: "${commit}" });
  }
  e.BLOBS.objects[`trace/2027/${sha}.json`] = JSON.stringify({ sha, year: 2027, items: cells });
}
const traceEnv = (commit) => ({ ...env, BLOBS: bucket({}), TRACE: d1(), COMMIT: commit, LOAD_TOKEN: TOKEN });
const post = (e, sha, token = TOKEN) => worker.fetch(new Request(`https://pdxplans.org/trace/2027/load/${sha}`, {
  method: "POST", headers: { Authorization: `Bearer ${token}` } }), e);
const at = (e, path) => worker.fetch(new Request(`https://pdxplans.org${path}`), e);
const cellAt = (n) => `/trace/2027/${cellKey(n)}`;
// Loads as CI does, until the Worker stops answering 409. Returns the last response and the loads it took.
async function load(e, sha) {
  for (let loads = 1; ; loads++) {
    const response = await post(e, sha);
    if (response.status !== 409) return { response, loads };
  }
}
const served = (n, v, sha) => JSON.stringify({ n, v, code: `blob/${sha}/`, sha });
const stored = (e) => e.TRACE.db.prepare("SELECT count(*) AS n FROM item").get().n;

test("serves a cell's trace from D1, with the deployed commit, once its build has every cell", async () => {
  const e = traceEnv(OLD);
  upload(e, OLD);
  const first = await post(e, OLD);
  assert.equal(first.status, 409);
  assert.equal(await first.text(), "2 items left to load");
  assert.equal(await (await at(e, cellAt(0))).text(), `asset ${cellAt(0)}.json`);
  assert.equal(await (await post(e, OLD)).text(), "Loaded every item");
  const response = await at(e, cellAt(11));
  assert.equal(await response.text(), served(11, 1, OLD));
  assert.equal(await (await at(e, cellAt(10))).text(), served(10, 1, OLD));
  const otherSheet = cellAt(11).replace("dvha", "main");
  assert.equal(await (await at(e, otherSheet)).text(), `asset ${otherSheet}.json`);
  assert.equal(response.headers.get("Content-Type"), "application/json; charset=utf-8");
});

test("serves the static file before a build loads, for a build other than the deployed commit's, and for another year", async () => {
  const e = traceEnv(NEW);
  assert.equal(await (await at(e, cellAt(0))).text(), `asset ${cellAt(0)}.json`);
  upload(e, OLD);
  await load(e, OLD);
  assert.equal(await (await at(e, cellAt(0))).text(), `asset ${cellAt(0)}.json`);
  assert.equal(await (await at({ ...e, COMMIT: OLD }, cellAt(0))).text(), served(0, 1, OLD));
  const other = cellAt(0).replace("2027", "2026");
  assert.equal(await (await at({ ...e, COMMIT: OLD }, other)).text(), `asset ${other}.json`);
  assert.equal(await (await at({ ...e, COMMIT: undefined }, cellAt(0))).text(), `asset ${cellAt(0)}.json`);
});

test("a build writes only the cells that changed", async () => {
  const e = traceEnv(OLD);
  upload(e, OLD);
  await load(e, OLD);
  e.TRACE.written = 0;
  upload(e, NEW, [3]);
  const { response, loads } = await load({ ...e, COMMIT: NEW }, NEW);
  assert.equal(response.status, 200);
  assert.equal(loads, 1);
  assert.equal(e.TRACE.written, 2);
  assert.equal(stored(e), 13);
  assert.equal(await (await at({ ...e, COMMIT: NEW }, cellAt(3))).text(), served(3, 2, NEW));
  e.TRACE.written = 0;
  upload(e, THIRD, [3]);
  assert.equal((await load({ ...e, COMMIT: THIRD }, THIRD)).loads, 1);
  assert.equal(e.TRACE.written, 1);
});

test("a build loaded again with other cells replaces them", async () => {
  const e = traceEnv(OLD);
  upload(e, OLD);
  await load(e, OLD);
  upload(e, OLD, [3]);
  assert.equal((await load(e, OLD)).response.status, 200);
  assert.equal(await (await at(e, cellAt(3))).text(), served(3, 2, OLD));
  assert.ok(`trace/2027/items/${hash(3, 2)}.json` in e.BLOBS.objects);
});

test("a build loaded again whose new cell went missing keeps its earlier cells", async () => {
  const e = traceEnv(OLD);
  upload(e, OLD);
  await load(e, OLD);
  upload(e, OLD, [3]);
  e.TRACE.beforeBatch = (statements) => {
    if (statements[0].sql.startsWith("INSERT INTO data_build")) e.TRACE.db.exec(`DELETE FROM item WHERE hash = '${hash(3, 2)}'`);
  };
  assert.equal((await post(e, OLD)).status, 409);
  assert.equal(await (await at(e, cellAt(3))).text(), served(3, 1, OLD));
});

const DAY = 24 * 60 * 60 * 1000;
const sha = (n) => n.toString(16).padStart(40, "0");
const builds = (e) => e.TRACE.db.prepare("SELECT sha FROM data_build ORDER BY loaded").all().map((b) => b.sha);
const own = (n) => String(n).padStart(64, "e");
// Loads builds 1, 2 and so on, each on the day given, and each with its own item for cell 0.
async function loadEach(t, e, days, first = 1) {
  for (const [j, day] of days.entries()) {
    const i = j + first - 1;
    upload(e, sha(i + 1));
    const manifest = JSON.parse(e.BLOBS.objects[`trace/2027/${sha(i + 1)}.json`]);
    manifest.items[cellKey(0)] = own(i + 1);
    e.BLOBS.objects[`trace/2027/${sha(i + 1)}.json`] = JSON.stringify(manifest);
    e.BLOBS.objects[`trace/2027/items/${own(i + 1)}.json`] = "{}";
    t.mock.method(Date, "now", () => day * DAY);
    assert.equal((await load(e, sha(i + 1))).response.status, 200);
  }
}

test("a load keeps the last 10 builds, however old", async (t) => {
  const e = traceEnv(undefined);
  await loadEach(t, e, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20]);
  assert.deepEqual(builds(e), [3, 4, 5, 6, 7, 8, 9, 10, 11, 12].map(sha));
});

test("a load keeps every build of the last 5 days, however many", async (t) => {
  const e = traceEnv(undefined);
  await loadEach(t, e, [0, ...Array(11).fill(10), 15]);
  assert.deepEqual(builds(e), [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13].map(sha));
});

test("a load keeps a build until it is 5 days old", async (t) => {
  const e = traceEnv(undefined);
  await loadEach(t, e, [4.5, ...Array(10).fill(9)]);
  assert.equal(builds(e).length, 11);
  await loadEach(t, e, [9.6], 12);
  assert.deepEqual(builds(e), [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12].map(sha));
});

test("a build loaded again counts as loaded then", async (t) => {
  const e = traceEnv(undefined);
  await loadEach(t, e, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
  await loadEach(t, e, [19], 1);
  await loadEach(t, e, [20], 11);
  assert.deepEqual(builds(e), [3, 4, 5, 6, 7, 8, 9, 10, 1, 11].map(sha));
});

test("a build that could not be added drops no other build", async (t) => {
  const e = traceEnv(undefined);
  await loadEach(t, e, Array(11).fill(0));
  upload(e, THIRD, [0]);
  e.TRACE.beforeBatch = (statements) => {
    if (statements[0].sql.startsWith("INSERT INTO data_build")) e.TRACE.db.exec(`DELETE FROM item WHERE hash = '${hash(0, 2)}'`);
  };
  t.mock.method(Date, "now", () => 10 * DAY);
  assert.equal((await post(e, THIRD)).status, 409);
  assert.equal(builds(e).length, 11);
});

test("a load keeps the deployed commit's build, however old", async (t) => {
  const e = traceEnv(sha(1));
  await loadEach(t, e, [0, ...Array(10).fill(10)]);
  assert.deepEqual(builds(e), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11].map(sha));
});

test("a load drops the items only dropped builds used, from D1 and R2", async (t) => {
  const e = traceEnv(undefined);
  e.BLOBS.objects[`trace/2027/cells/${hash(0, 1)}.json`] = "{}";
  await loadEach(t, e, [0, ...Array(10).fill(10)]);
  assert.equal(stored(e), 11 + 10);
  const kept = Object.keys(e.BLOBS.objects);
  assert.deepEqual(kept.filter((k) => k.includes(sha(1)) || k.includes(own(1)) || k.includes("/cells/")), []);
  const manifests = 10, sharedCells = 11, ownCells = 10;
  assert.equal(kept.length, manifests + sharedCells + ownCells);
});

test("serves a loaded build's table, its rows in the build's order", async () => {
  const e = traceEnv(undefined);
  assert.equal((await at(e, `/tables/2027/${OLD}/presented.json`)).status, 404);
  upload(e, OLD);
  const manifest = JSON.parse(e.BLOBS.objects[`trace/2027/${OLD}.json`]);
  const tables = { "tables/presented/0/P2": [{ n: "1" }, { n: "2" }], "tables/presented/1/P1": [{ n: "3" }],
                   "tables/main/0/P1": [{ n: "4" }], "tables/main_chart/0/P1": [{ n: "5" }] };
  for (const [i, [key, rows]] of Object.entries(tables).entries()) {
    manifest.items[key] = own(i);
    e.BLOBS.objects[`trace/2027/items/${own(i)}.json`] = JSON.stringify(rows);
  }
  e.BLOBS.objects[`trace/2027/${OLD}.json`] = JSON.stringify(manifest);
  await load(e, OLD);
  const response = await at(e, `/tables/2027/${OLD}/presented.json`);
  assert.equal(response.headers.get("Content-Type"), "application/json; charset=utf-8");
  assert.equal(response.headers.get("Cache-Control"), "no-cache");
  const etag = response.headers.get("ETag");
  assert.match(etag, /^"[0-9a-f]{64}"$/);
  const again = await worker.fetch(new Request(`https://pdxplans.org/tables/2027/${OLD}/presented.json`, { headers: { "If-None-Match": etag } }), e);
  assert.equal(again.status, 304);
  assert.equal(again.headers.get("ETag"), etag);
  for (const header of [`W/${etag}`, `"x", ${etag}`, "*"]) {
    const response = await worker.fetch(new Request(`https://pdxplans.org/tables/2027/${OLD}/presented.json`, { headers: { "If-None-Match": header } }), e);
    assert.equal(response.status, 304, header);
  }
  assert.equal((await worker.fetch(new Request(`https://pdxplans.org/tables/2027/${OLD}/presented.json`, { headers: { "If-None-Match": '"x"' } }), e)).status, 200);
  assert.notEqual((await at(e, `/tables/2027/${OLD}/main.json`)).headers.get("ETag"), etag);
  assert.deepEqual(await response.json(), [{ n: "1" }, { n: "2" }, { n: "3" }]);
  assert.deepEqual(await (await at(e, `/tables/2027/${OLD}/main.json`)).json(), [{ n: "4" }]);
  for (const path of [`/tables/2027/${OLD}/dvha.json`, `/tables/2027/${NEW}/presented.json`, `/tables/2026/${OLD}/presented.json`]) {
    assert.equal((await at(e, path)).status, 404, path);
  }
});

test("lists the kept builds, newest first, with their tables and the deployed commit", async (t) => {
  const e = traceEnv(NEW);
  assert.deepEqual(await (await at(e, "/tables/2027/builds.json")).json(), { deployed: NEW, builds: [] });
  t.mock.method(Date, "now", () => 1000);
  upload(e, OLD);
  const manifest = JSON.parse(e.BLOBS.objects[`trace/2027/${OLD}.json`]);
  for (const [i, key] of ["tables/presented/0/P1", "tables/plans/0/P1", "tables/presented/1/P2"].entries()) {
    manifest.items[key] = own(i);
    e.BLOBS.objects[`trace/2027/items/${own(i)}.json`] = "[]";
  }
  e.BLOBS.objects[`trace/2027/${OLD}.json`] = JSON.stringify(manifest);
  await load(e, OLD);
  t.mock.method(Date, "now", () => 2000);
  upload(e, NEW);
  await load(e, NEW);
  const response = await at(e, "/tables/2027/builds.json");
  assert.equal(response.headers.get("Content-Type"), "application/json; charset=utf-8");
  assert.equal(response.headers.get("Cache-Control"), "no-cache");
  const { deployed, builds } = await response.json();
  assert.equal(deployed, NEW);
  assert.deepEqual(builds.map((b) => ({ ...b, tables: b.tables.toSorted() })), [
    { sha: NEW, loaded: 2000, tables: [] },
    { sha: OLD, loaded: 1000, tables: ["plans", "presented"] },
  ]);
  assert.equal((await at(e, "/tables/2026/builds.json")).status, 404);
});

test("an unfinished build drops nothing", async () => {
  const e = traceEnv(NEW);
  upload(e, OLD);
  await load(e, OLD);
  upload(e, THIRD, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]);
  assert.equal((await post(e, THIRD)).status, 409);
  assert.equal(await (await at({ ...e, COMMIT: OLD }, cellAt(11))).text(), served(11, 1, OLD));
});

test("a build whose cell went missing while it loaded is neither added nor drops other builds", async () => {
  const e = traceEnv(NEW);
  upload(e, OLD);
  await load(e, OLD);
  upload(e, THIRD, [0]);
  e.TRACE.beforeBatch = (statements) => {
    if (statements[0].sql.startsWith("INSERT INTO data_build")) e.TRACE.db.exec(`DELETE FROM item WHERE hash = '${hash(0, 2)}'`);
  };
  const response = await post(e, THIRD);
  e.TRACE.beforeBatch = null;
  assert.equal(response.status, 409);
  assert.equal(await response.text(), "An item went missing, so load again");
  assert.equal(await (await at({ ...e, COMMIT: OLD }, cellAt(1))).text(), served(1, 1, OLD));
  assert.equal(await (await at({ ...e, COMMIT: THIRD }, cellAt(1))).text(), `asset ${cellAt(1)}.json`);
  assert.equal(await (await load(e, THIRD)).response.text(), "Loaded every item");
});

test("a cell that another load stored first loads without error", async () => {
  const e = traceEnv(OLD);
  upload(e, OLD);
  e.TRACE.afterQuery = () => (e.TRACE.db.exec(`INSERT INTO item VALUES ('${hash(0, 1)}', '{}')`), e.TRACE.afterQuery = null);
  assert.equal((await post(e, OLD)).status, 409);
});

test("a load drops the tables that earlier versions used", async () => {
  const e = traceEnv(OLD);
  e.TRACE.db.exec("CREATE TABLE cell_trace (sha); CREATE TABLE loaded (sha); CREATE TABLE cell_json (hash); CREATE TABLE build (sha)");
  upload(e, OLD);
  await post(e, OLD);
  assert.deepEqual(e.TRACE.db.prepare("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").all().map((t) => t.name),
                   ["data_build", "item"]);
});

test("loads only for a POST with the load token", async () => {
  const e = traceEnv(OLD);
  upload(e, OLD);
  assert.equal((await post(e, OLD, "wrong")).status, 401);
  assert.equal((await post({ ...e, LOAD_TOKEN: undefined }, OLD, "undefined")).status, 401);
  assert.equal(await (await at(e, `/trace/2027/load/${OLD}`)).text(), `asset /trace/2027/load/${OLD}`);
  assert.equal(e.TRACE.batches, 0);
});

test("answers 404 to a load of a build or cell that R2 lacks", async () => {
  const e = traceEnv(OLD);
  assert.equal((await post(e, OLD)).status, 404);
  upload(e, OLD);
  delete e.BLOBS.objects[`trace/2027/items/${hash(4, 1)}.json`];
  assert.equal((await post(e, OLD)).status, 404);
});
