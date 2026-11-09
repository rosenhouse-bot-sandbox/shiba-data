// Serves each plan PDF from the R2 bucket, where the Pipeline workflow stores it as blobs/<sha256>.
// /blobs/<sha256>.txt serves a model prompt, which the Pipeline workflow stores the same way.
// The static site comes from the assets directory.
// CI downloads every blob through this route too, so it needs no R2 credentials.
// /trace/<year>/main/<plan_id>/<col> serves a cell's trace from D1 once a build is live, and from the static file
// that web/build.py writes otherwise.
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const [, year, plan, col] = url.pathname.match(/^\/trace\/(\d+)\/main\/([^/]+)\/([^/.]+)$/) ?? [];
    if (year) {
      const live = year === D1_YEAR && await env.TRACE.prepare(
        "SELECT json FROM cell_trace JOIN live USING (sha) WHERE plan_id = ? AND col = ?").bind(plan, col).first().catch(() => null);
      if (live) return new Response(live.json, { headers: { "Content-Type": "application/json; charset=utf-8" } });
      return env.ASSETS.fetch(new Request(new URL(`${url.pathname}.json`, url), request));
    }
    if (url.pathname === `/trace/${D1_YEAR}/live`) {
      const live = await env.TRACE.prepare("SELECT sha, hash FROM live").first().catch(() => null);
      return live ? Response.json(live) : new Response("Not found", { status: 404 });
    }
    const [, build, part] = url.pathname.match(/^\/trace\/2027\/load\/([0-9a-f]{40})(?:\/(\d+))?$/) ?? [];
    if (build && request.method === "POST") return part === undefined ? goLive(env, build) : loadPart(env, build, Number(part));
    const [, pdf, text] = url.pathname.match(/^\/(?:docs\/([0-9a-f]{64})\.pdf|blobs\/([0-9a-f]{64})\.txt)$/) ?? [];
    const sha = pdf ?? text;
    if (!sha) return env.ASSETS.fetch(request);
    // pdf.js loads large EOCs in ranges.
    const blob = await env.BLOBS.get(`blobs/${sha}`, { range: request.headers, onlyIf: request.headers });
    if (!blob) return new Response("Not found", { status: 404 });
    const headers = new Headers({
      "Content-Type": pdf ? "application/pdf" : "text/plain; charset=utf-8",
      "Cache-Control": "public, max-age=31536000, immutable",
      "Accept-Ranges": "bytes",
      ETag: blob.httpEtag,
    });
    if (!("body" in blob)) return new Response(null, { status: 304, headers });
    let status = 200;
    if (blob.range && request.headers.has("Range")) {
      const offset = blob.range.offset ?? blob.size - blob.range.suffix;
      const length = blob.range.length ?? blob.size - offset;
      headers.set("Content-Range", `bytes ${offset}-${offset + length - 1}/${blob.size}`);
      status = 206;
    }
    return new Response(request.method === "HEAD" ? null : blob.body, { status, headers });
  },
};

// Each main build loads its cells' traces into D1 one part at a time, then goes live, so a cut-off load leaves the
// previous build live. CI uploads the parts to R2 as trace/<year>/<sha>/<n>.json beside a manifest.json.
const D1_YEAR = "2027";
const SCHEMA = [
  `CREATE TABLE IF NOT EXISTS cell_trace (sha TEXT NOT NULL, part INTEGER NOT NULL, plan_id TEXT NOT NULL, col TEXT NOT NULL,
                                          json TEXT NOT NULL, PRIMARY KEY (sha, plan_id, col))`,
  "CREATE TABLE IF NOT EXISTS live (one INTEGER PRIMARY KEY CHECK (one = 1), sha TEXT NOT NULL, hash TEXT NOT NULL)",
];
const missing = () => new Response("Not found", { status: 404 });

async function object(env, key) {
  return (await env.BLOBS.get(key))?.json();
}

async function loadPart(env, sha, part) {
  await env.TRACE.batch(SCHEMA.map((sql) => env.TRACE.prepare(sql)));
  if (await env.TRACE.prepare("SELECT 1 FROM cell_trace WHERE sha = ? AND part = ?").bind(sha, part).first()) {
    return new Response("Loaded before");
  }
  const cells = await object(env, `trace/${D1_YEAR}/${sha}/${part}.json`);
  if (!cells) return missing();
  const insert = env.TRACE.prepare("INSERT INTO cell_trace VALUES (?, ?, ?, ?, ?)");
  await env.TRACE.batch(cells.map(([plan, col, json]) => insert.bind(sha, part, plan, col, json)));
  return new Response("Loaded");
}

async function goLive(env, sha) {
  const manifest = await object(env, `trace/${D1_YEAR}/${sha}/manifest.json`);
  if (!manifest) return missing();
  await env.TRACE.batch(SCHEMA.map((sql) => env.TRACE.prepare(sql)));
  const { n } = await env.TRACE.prepare("SELECT count(*) AS n FROM cell_trace WHERE sha = ?").bind(sha).first();
  if (n !== manifest.cells) return new Response(`${n} of ${manifest.cells} cells loaded`, { status: 409 });
  const before = await env.TRACE.prepare("SELECT sha FROM live").first();
  await env.TRACE.batch([
    env.TRACE.prepare("INSERT OR REPLACE INTO live VALUES (1, ?, ?)").bind(sha, manifest.hash),
    env.TRACE.prepare("DELETE FROM cell_trace WHERE sha != ?").bind(sha),
  ]);
  // Without its parts, the build that was live cannot go live again.
  if (before && before.sha !== sha) {
    const prefix = `trace/${D1_YEAR}/${before.sha}/`;
    for (let cursor; ;) {
      const listed = await env.BLOBS.list({ prefix, cursor });
      if (listed.objects.length) await env.BLOBS.delete(listed.objects.map((o) => o.key));
      if (!listed.truncated) break;
      cursor = listed.cursor;
    }
  }
  return new Response("Live");
}
