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
// Uploads a build of 12 cells, as CI does. changed lists the cells at version 2, and the rest are at version 1.
function upload(e, sha, changed = []) {
  const cells = Object.fromEntries(PLANS.map((plan, n) => [`${plan}/AB_ambulance`, hash(n, changed.includes(n) ? 2 : 1)]));
  for (const [n, v] of PLANS.map((_, n) => [n, changed.includes(n) ? 2 : 1])) {
    e.BLOBS.objects[`trace/2027/cells/${hash(n, v)}.json`] = JSON.stringify({ n, v, code: "blob/${commit}/", sha: "${commit}" });
  }
  e.BLOBS.objects[`trace/2027/${sha}.json`] = JSON.stringify({ sha, year: 2027, cells });
}
const traceEnv = (commit) => ({ ...env, BLOBS: bucket({}), TRACE: d1(), COMMIT: commit, LOAD_TOKEN: TOKEN });
const post = (e, sha, token = TOKEN) => worker.fetch(new Request(`https://pdxplans.org/trace/2027/load/${sha}`, {
  method: "POST", headers: { Authorization: `Bearer ${token}` } }), e);
const at = (e, path) => worker.fetch(new Request(`https://pdxplans.org${path}`), e);
const cellAt = (n) => `/trace/2027/main/${PLANS[n]}/AB_ambulance`;
// Loads as CI does, until the Worker stops answering 409. Returns the last response and the loads it took.
async function load(e, sha) {
  for (let loads = 1; ; loads++) {
    const response = await post(e, sha);
    if (response.status !== 409) return { response, loads };
  }
}
const served = (n, v, sha) => JSON.stringify({ n, v, code: `blob/${sha}/`, sha });
const stored = (e) => e.TRACE.db.prepare("SELECT count(*) AS n FROM cell_json").get().n;

test("serves a cell's trace from D1, with the deployed commit, once its build has every cell", async () => {
  const e = traceEnv(OLD);
  upload(e, OLD);
  const first = await post(e, OLD);
  assert.equal(first.status, 409);
  assert.equal(await first.text(), "2 cells left to load");
  assert.equal(await (await at(e, cellAt(0))).text(), `asset ${cellAt(0)}.json`);
  assert.equal(await (await post(e, OLD)).text(), "Loaded every cell");
  const response = await at(e, cellAt(11));
  assert.equal(await response.text(), served(11, 1, OLD));
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
  assert.equal(e.TRACE.written, 4);
  assert.equal(stored(e), 12);
  assert.equal(await (await at({ ...e, COMMIT: NEW }, cellAt(3))).text(), served(3, 2, NEW));
  e.TRACE.written = 0;
  upload(e, THIRD, [3]);
  assert.equal((await load({ ...e, COMMIT: THIRD }, THIRD)).loads, 1);
  assert.equal(e.TRACE.written, 2);
});

test("a build loaded again with other cells replaces them", async () => {
  const e = traceEnv(OLD);
  upload(e, OLD);
  await load(e, OLD);
  upload(e, OLD, [3]);
  assert.equal((await load(e, OLD)).response.status, 200);
  assert.equal(await (await at(e, cellAt(3))).text(), served(3, 2, OLD));
  assert.ok(`trace/2027/cells/${hash(3, 2)}.json` in e.BLOBS.objects);
});

test("a build loaded again whose new cell went missing keeps its earlier cells", async () => {
  const e = traceEnv(OLD);
  upload(e, OLD);
  await load(e, OLD);
  upload(e, OLD, [3]);
  e.TRACE.beforeBatch = (statements) => {
    if (statements[0].sql.startsWith("INSERT INTO build")) e.TRACE.db.exec(`DELETE FROM cell_json WHERE hash = '${hash(3, 2)}'`);
  };
  assert.equal((await post(e, OLD)).status, 409);
  assert.equal(await (await at(e, cellAt(3))).text(), served(3, 1, OLD));
});

test("a build drops other builds and the cells only they used, but keeps the deployed commit's", async () => {
  const e = traceEnv(OLD);
  upload(e, OLD);
  await load(e, OLD);
  e.BLOBS.objects[`trace/2027/${THIRD}/0.json`] = "[]";
  upload(e, NEW, [3]);
  await load(e, NEW);
  assert.equal(stored(e), 13);
  assert.ok(`trace/2027/${OLD}.json` in e.BLOBS.objects);
  assert.ok(`trace/2027/cells/${hash(3, 1)}.json` in e.BLOBS.objects);
  assert.ok(!(`trace/2027/${THIRD}/0.json` in e.BLOBS.objects));
  const e2 = { ...e, COMMIT: NEW };
  assert.equal((await load(e2, NEW)).response.status, 200);
  assert.equal(stored(e2), 12);
  assert.deepEqual(e2.TRACE.db.prepare("SELECT sha FROM build").all().map((b) => b.sha), [NEW]);
  assert.deepEqual(Object.keys(e.BLOBS.objects).filter((k) => k.includes(OLD) || k.includes(hash(3, 1))), []);
  assert.equal(Object.keys(e.BLOBS.objects).length, 13);
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
    if (statements[0].sql.startsWith("INSERT INTO build")) e.TRACE.db.exec(`DELETE FROM cell_json WHERE hash = '${hash(0, 2)}'`);
  };
  const response = await post(e, THIRD);
  e.TRACE.beforeBatch = null;
  assert.equal(response.status, 409);
  assert.equal(await response.text(), "A cell went missing, so load again");
  assert.equal(await (await at({ ...e, COMMIT: OLD }, cellAt(1))).text(), served(1, 1, OLD));
  assert.equal(await (await at({ ...e, COMMIT: THIRD }, cellAt(1))).text(), `asset ${cellAt(1)}.json`);
  assert.equal(await (await load(e, THIRD)).response.text(), "Loaded every cell");
});

test("a cell that another load stored first loads without error", async () => {
  const e = traceEnv(OLD);
  upload(e, OLD);
  e.TRACE.afterQuery = () => (e.TRACE.db.exec(`INSERT INTO cell_json VALUES ('${hash(0, 1)}', '{}')`), e.TRACE.afterQuery = null);
  assert.equal((await post(e, OLD)).status, 409);
});

test("a build loaded while no commit is deployed drops the other builds", async () => {
  const e = traceEnv(undefined);
  upload(e, OLD);
  await load(e, OLD);
  upload(e, NEW, [3]);
  assert.equal((await load(e, NEW)).response.status, 200);
  assert.deepEqual(e.TRACE.db.prepare("SELECT sha FROM build").all().map((b) => b.sha), [NEW]);
});

test("a load drops the tables that held whole builds", async () => {
  const e = traceEnv(OLD);
  e.TRACE.db.exec("CREATE TABLE cell_trace (sha); CREATE TABLE loaded (sha)");
  upload(e, OLD);
  await post(e, OLD);
  assert.deepEqual(e.TRACE.db.prepare("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").all().map((t) => t.name),
                   ["build", "cell_json"]);
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
  delete e.BLOBS.objects[`trace/2027/cells/${hash(4, 1)}.json`];
  assert.equal((await post(e, OLD)).status, 404);
});
