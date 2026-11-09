// Serves each plan PDF from the R2 bucket, where the Pipeline workflow stores it as blobs/<sha256>.
// /blobs/<sha256>.txt serves a model prompt, which the Pipeline workflow stores the same way.
// The static site comes from the assets directory.
// CI downloads every blob through this route too, so it needs no R2 credentials.
// /trace/2027/main/<plan_id>/<col> serves a cell's trace from D1 once every cell of the deployed commit's build has
// loaded. Until then, and for other years, it serves the static file that web/build.py writes.
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const [, year, plan, col] = url.pathname.match(/^\/trace\/(\d+)\/main\/([^/]+)\/([^/.]+)$/) ?? [];
    if (year) {
      const row = year === D1_YEAR && env.COMMIT && await env.TRACE.prepare(
        "SELECT json FROM cell_trace JOIN loaded USING (sha) WHERE sha = ? AND plan_id = ? AND col = ?")
        .bind(env.COMMIT, plan, col).first().catch(() => null);
      if (row) return new Response(row.json, { headers: { "Content-Type": "application/json; charset=utf-8" } });
      return env.ASSETS.fetch(new Request(new URL(`${url.pathname}.json`, url), request));
    }
    const [, build, part] = url.pathname.match(LOAD) ?? [];
    if (build && request.method === "POST") {
      if (!env.LOAD_TOKEN || request.headers.get("Authorization") !== `Bearer ${env.LOAD_TOKEN}`) {
        return new Response("Unauthorized", { status: 401 });
      }
      return part === undefined ? finish(env, build) : loadPart(env, build, part);
    }
    const [, pdf, text] = url.pathname.match(/^\/(?:docs\/([0-9a-f]{64})\.pdf|blobs\/([0-9a-f]{64})\.txt)$/) ?? [];
    const sha = pdf ?? text;
    if (!sha) return env.ASSETS.fetch(request);
    // pdf.js loads large EOCs in ranges.
    const blob = await env.BLOBS.get(`blobs/${sha}`, { range: request.headers, onlyIf: request.headers });
    if (!blob) return missing();
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

// CI loads each main build's cells into D1 from R2's trace/<year>/<sha>/ one part at a time, then finishes the build.
// LOAD_TOKEN is a secret that the deploy job gives the Worker and the trace job derives the same way.
const D1_YEAR = "2027";
const LOAD = new RegExp(`^/trace/${D1_YEAR}/load/([0-9a-f]{40})(?:/(\\d+))?$`);
const SCHEMA = [
  `CREATE TABLE IF NOT EXISTS cell_trace (sha TEXT NOT NULL, plan_id TEXT NOT NULL, col TEXT NOT NULL, json TEXT NOT NULL,
                                          PRIMARY KEY (sha, plan_id, col))`,
  "CREATE TABLE IF NOT EXISTS loaded (sha TEXT PRIMARY KEY)",
];
const missing = () => new Response("Not found", { status: 404 });

async function readJson(env, key) {
  return (await env.BLOBS.get(key))?.json();
}

const schema = (env) => SCHEMA.map((sql) => env.TRACE.prepare(sql));

async function loadPart(env, sha, part) {
  const cells = await readJson(env, `trace/${D1_YEAR}/${sha}/${part}.json`);
  if (!cells) return missing();
  const insert = env.TRACE.prepare("INSERT OR IGNORE INTO cell_trace VALUES (?, ?, ?, ?)");
  await env.TRACE.batch([...schema(env), ...cells.map(([plan, col, json]) => insert.bind(sha, plan, col, json))]);
  return new Response("Loaded");
}

// A build counts as loaded once it has every cell. Then the other builds' rows and parts go, except the deployed one's.
// A batch runs as one transaction, so the count and the deletes see the same rows.
async function finish(env, sha) {
  const manifest = await readJson(env, `trace/${D1_YEAR}/${sha}/manifest.json`);
  if (!manifest) return missing();
  const keep = env.COMMIT ?? sha;
  await env.TRACE.batch([
    ...schema(env),
    env.TRACE.prepare("INSERT OR IGNORE INTO loaded SELECT ?1 WHERE (SELECT count(*) FROM cell_trace WHERE sha = ?1) = ?2")
      .bind(sha, manifest.cells),
    env.TRACE.prepare("DELETE FROM cell_trace WHERE sha NOT IN (?1, ?2) AND ?1 IN (SELECT sha FROM loaded)").bind(sha, keep),
    env.TRACE.prepare("DELETE FROM loaded WHERE sha NOT IN (?1, ?2) AND ?1 IN (SELECT sha FROM loaded)").bind(sha, keep),
  ]);
  if (!await env.TRACE.prepare("SELECT 1 FROM loaded WHERE sha = ?").bind(sha).first()) {
    const { n } = await env.TRACE.prepare("SELECT count(*) AS n FROM cell_trace WHERE sha = ?").bind(sha).first();
    return new Response(`${n} of ${manifest.cells} cells loaded`, { status: 409 });
  }
  const prefix = `trace/${D1_YEAR}/`;
  for (let cursor; ;) {
    const listed = await env.BLOBS.list({ prefix, cursor });
    const old = listed.objects.map((o) => o.key).filter((key) => ![sha, keep].some((s) => key.startsWith(`${prefix}${s}/`)));
    if (old.length) await env.BLOBS.delete(old);
    if (!listed.truncated) break;
    cursor = listed.cursor;
  }
  return new Response("Loaded every cell");
}
