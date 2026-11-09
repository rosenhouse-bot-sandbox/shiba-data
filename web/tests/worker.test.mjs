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

// The fake D1 database runs on node:sqlite, with the binding's prepare, bind, first, run and batch.
function d1() {
  const db = new DatabaseSync(":memory:");
  const statement = (sql, args = []) => ({
    // Like D1, bind throws at once on undefined.
    bind: (...values) => {
      if (values.includes(undefined)) throw new TypeError("D1_TYPE_ERROR: Type 'undefined' not supported");
      return statement(sql, values);
    },
    first: async () => db.prepare(sql).get(...args) ?? null,
    run: async () => (db.prepare(sql).run(...args), { success: true }),
  });
  const batches = [];
  return {
    batches,
    prepare: (sql) => statement(sql),
    batch: async (statements) => {
      batches.push(statements.length);
      db.exec("BEGIN");
      try {
        for (const s of statements) await s.run();
        db.exec("COMMIT");
      } catch (e) {
        db.exec("ROLLBACK");
        throw e;
      }
    },
  };
}

// The fake R2 bucket holds text objects.
function bucket(objects) {
  return {
    objects,
    get: async (key) => key in objects ? { json: async () => JSON.parse(objects[key]) } : null,
    // Lists two keys a page, so the tests page through the listing.
    list: async ({ prefix, cursor = "" }) => {
      const keys = Object.keys(objects).filter((k) => k.startsWith(prefix) && k > cursor).sort();
      return { objects: keys.slice(0, 2).map((key) => ({ key })), truncated: keys.length > 2, cursor: keys[1] };
    },
    delete: async (keys) => [keys].flat().forEach((k) => delete objects[k]),
  };
}

const OLD = "1".repeat(40), NEW = "2".repeat(40), THIRD = "3".repeat(40), TOKEN = "t".repeat(64);
const parts = (sha, json) => ({
  [`trace/2027/${sha}/manifest.json`]: JSON.stringify({ sha, year: 2027, cells: 3, parts: 2 }),
  [`trace/2027/${sha}/0.json`]: JSON.stringify([["H1036-153-0", "AB_ambulance", json], ["H1036-153-0", "C_premium", "{}"]]),
  [`trace/2027/${sha}/1.json`]: JSON.stringify([["H1036-306-0", "AB_ambulance", "{}"]]),
});
const traceEnv = (commit) => ({ ...env, BLOBS: bucket(parts(OLD, '{"old": 1}')), TRACE: d1(), COMMIT: commit, LOAD_TOKEN: TOKEN });
const upload = (e, sha) => Object.assign(e.BLOBS.objects, parts(sha, `{"${sha}": 1}`));
const post = (e, path, token = TOKEN) => worker.fetch(new Request(`https://pdxplans.org${path}`, {
  method: "POST", headers: { Authorization: `Bearer ${token}` } }), e);
const at = (e, path) => worker.fetch(new Request(`https://pdxplans.org${path}`), e);
const load = async (e, sha, partsToLoad = [0, 1]) => {
  for (const n of partsToLoad) assert.equal((await post(e, `/trace/2027/load/${sha}/${n}`)).status, 200);
  return post(e, `/trace/2027/load/${sha}`);
};
const rows = (e, sha) => e.TRACE.prepare("SELECT count(*) AS n FROM cell_trace WHERE sha = ?").bind(sha).first();

test("serves a cell's trace from D1 once every cell of the deployed commit's build has loaded", async () => {
  const e = traceEnv(OLD);
  assert.equal((await load(e, OLD, [0])).status, 409);
  assert.equal(await (await at(e, TRACE)).text(), `asset ${TRACE}.json`);
  assert.equal((await load(e, OLD, [1])).status, 200);
  const response = await at(e, TRACE);
  assert.equal(await response.text(), '{"old": 1}');
  assert.equal(response.headers.get("Content-Type"), "application/json; charset=utf-8");
});

test("serves the static file before any build loads, for a build other than the deployed commit's, and for another year", async () => {
  const e = traceEnv(NEW);
  assert.equal(await (await at(e, TRACE)).text(), `asset ${TRACE}.json`);
  await load(e, OLD);
  assert.equal(await (await at(e, TRACE)).text(), `asset ${TRACE}.json`);
  upload(e, NEW);
  await load(e, NEW);
  const other = "/trace/2026/main/H1036-153-0/AB_ambulance";
  assert.equal(await (await at(e, other)).text(), `asset ${other}.json`);
  assert.equal(await (await at({ ...e, COMMIT: undefined }, TRACE)).text(), `asset ${TRACE}.json`);
});

test("a loaded build drops other builds' rows and parts, but keeps the deployed commit's", async () => {
  const e = traceEnv(OLD);
  await load(e, OLD);
  upload(e, NEW);
  await load(e, NEW);
  assert.deepEqual([(await rows(e, OLD)).n, (await rows(e, NEW)).n], [3, 3]);
  assert.equal(Object.keys(e.BLOBS.objects).filter((k) => k.includes(OLD)).length, 3);
  assert.equal(await (await at(e, TRACE)).text(), '{"old": 1}');
  const e2 = { ...e, COMMIT: NEW };
  await load(e2, NEW, []);
  assert.deepEqual([(await rows(e2, OLD)).n, (await rows(e2, NEW)).n], [0, 3]);
  assert.equal((await e2.TRACE.prepare("SELECT group_concat(sha) AS shas FROM loaded").first()).shas, NEW);
  assert.deepEqual(Object.keys(e.BLOBS.objects).filter((k) => k.includes(OLD)), []);
  assert.equal(Object.keys(e.BLOBS.objects).filter((k) => k.includes(NEW)).length, 3);
});

test("an unfinished build drops nothing", async () => {
  const e = traceEnv(NEW);
  await load(e, OLD);
  upload(e, THIRD);
  assert.equal((await load(e, THIRD, [1])).status, 409);
  assert.equal(await (await at({ ...e, COMMIT: OLD }, TRACE)).text(), '{"old": 1}');
});

test("finishing a build before any of its parts reports that none loaded", async () => {
  const response = await post(traceEnv(OLD), `/trace/2027/load/${OLD}`);
  assert.equal(response.status, 409);
  assert.equal(await response.text(), "0 of 3 cells loaded");
});

test("a build loaded while no commit is deployed drops the other builds", async () => {
  const e = traceEnv(undefined);
  await load(e, OLD);
  upload(e, NEW);
  assert.equal((await load(e, NEW)).status, 200);
  assert.deepEqual([(await rows(e, OLD)).n, (await rows(e, NEW)).n], [0, 3]);
});

test("a part loaded twice counts its cells once", async () => {
  const e = traceEnv(OLD);
  await post(e, `/trace/2027/load/${OLD}/1`);
  assert.equal((await load(e, OLD, [1])).status, 409);
  assert.equal((await load(e, OLD, [0])).status, 200);
});

test("loads only for a POST with the load token", async () => {
  const e = traceEnv(OLD);
  assert.equal((await post(e, `/trace/2027/load/${OLD}/0`, "wrong")).status, 401);
  assert.equal((await post({ ...e, LOAD_TOKEN: undefined }, `/trace/2027/load/${OLD}/0`, "undefined")).status, 401);
  assert.equal(await (await at(e, `/trace/2027/load/${OLD}/0`)).text(), `asset /trace/2027/load/${OLD}/0`);
  assert.deepEqual(e.TRACE.batches, []);
});

test("answers 404 to a load of a part or build that R2 lacks", async () => {
  const e = traceEnv(OLD);
  assert.equal((await post(e, `/trace/2027/load/${OLD}/2`)).status, 404);
  assert.equal((await post(e, `/trace/2027/load/${THIRD}`)).status, 404);
});
