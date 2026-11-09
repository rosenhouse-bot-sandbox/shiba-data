import { test } from "node:test";
import assert from "node:assert/strict";
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

const env = { ASSETS: { fetch: async (request) => new Response(`asset ${new URL(request.url).pathname}`) }, BLOBS: { get } };
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
