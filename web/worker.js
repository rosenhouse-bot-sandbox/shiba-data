// Serves each plan PDF from the R2 bucket, where the Pipeline workflow stores it as blobs/<sha256>.
// /blobs/<sha256>.txt serves a model prompt, which the Pipeline workflow stores the same way.
// The static site comes from the assets directory.
// CI downloads every blob through this route too, so it needs no R2 credentials.
// /trace/2027/<sheet>/<plan_id>/<col> serves a cell's trace from D1 once every cell of the deployed commit's build has
// loaded. Until then, and for other years, it serves the static file that web/build.py writes.
// Only a trace load may change anything, so every other request must be a GET or HEAD.
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const [, build] = url.pathname.match(LOAD) ?? [];
    if (build && request.method === "POST") {
      if (!env.LOAD_TOKEN || request.headers.get("Authorization") !== `Bearer ${env.LOAD_TOKEN}`) {
        return new Response("Unauthorized", { status: 401 });
      }
      return load(env, build);
    }
    if (!["GET", "HEAD"].includes(request.method)) {
      return new Response("Method not allowed", { status: 405, headers: { Allow: "GET, HEAD" } });
    }
    const [, year, cell] = url.pathname.match(/^\/trace\/(\d+)\/((?:main|dvha)\/[^/]+\/[^/.]+)$/) ?? [];
    if (year) {
      const row = year === D1_YEAR && env.COMMIT && await env.TRACE.prepare(
        "SELECT json FROM cell_json WHERE hash = (SELECT cells ->> ? FROM build WHERE sha = ?)")
        .bind(`$."${cell}"`, env.COMMIT).first().catch(() => null);
      if (row) {
        return new Response(row.json.replaceAll(COMMIT, env.COMMIT), { headers: { "Content-Type": "application/json; charset=utf-8" } });
      }
      return env.ASSETS.fetch(new Request(new URL(`${url.pathname}.json`, url), request));
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

// CI loads each main build into D1 from R2: trace/<year>/<sha>.json names the file in trace/<year>/cells/ that holds
// each cell's trace, by <sheet>/<plan_id>/<col>. CI repeats the load while it answers 409. Each load adds a few cells
// that D1 lacks, so a cell that did not change since an earlier build costs no writes. Once D1 has every cell, the load adds the build.
// LOAD_TOKEN is a secret that the deploy job gives the Worker and the trace job derives the same way.
const D1_YEAR = "2027";
const COMMIT = "${commit}";
const PER_LOAD = 10;
const LOAD = new RegExp(`^/trace/${D1_YEAR}/load/([0-9a-f]{40})$`);
const PREFIX = `trace/${D1_YEAR}/`;
const SCHEMA = [
  "CREATE TABLE IF NOT EXISTS cell_json (hash TEXT PRIMARY KEY, json TEXT NOT NULL)",
  "CREATE TABLE IF NOT EXISTS build (sha TEXT PRIMARY KEY, cells TEXT NOT NULL)",
  "DROP TABLE IF EXISTS cell_trace",
  "DROP TABLE IF EXISTS loaded",
];
const missing = () => new Response("Not found", { status: 404 });
const LACKING = "SELECT value AS hash FROM json_each(?1) WHERE value NOT IN (SELECT hash FROM cell_json)";

async function load(env, sha) {
  const manifest = await (await env.BLOBS.get(`${PREFIX}${sha}.json`))?.json();
  if (!manifest) return missing();
  const cells = JSON.stringify(manifest.cells);
  await env.TRACE.batch(SCHEMA.map((sql) => env.TRACE.prepare(sql)));
  const { results: lacking } = await env.TRACE.prepare(LACKING).bind(cells).all();
  if (lacking.length) {
    const some = lacking.slice(0, PER_LOAD);
    const texts = await Promise.all(some.map(async ({ hash }) => (await env.BLOBS.get(`${PREFIX}cells/${hash}.json`))?.text()));
    if (texts.includes(undefined)) return missing();
    const insert = env.TRACE.prepare("INSERT OR IGNORE INTO cell_json VALUES (?, ?)");
    await env.TRACE.batch(some.map(({ hash }, i) => insert.bind(hash, texts[i])));
    if (lacking.length > some.length) return new Response(`${lacking.length - some.length} cells left to load`, { status: 409 });
  }
  return finish(env, sha, cells);
}

// Adding a build drops every other build, except the deployed one, and the cells that only they used.
// A batch runs as one transaction, so a cell that another build's load just dropped stops the build from being added.
async function finish(env, sha, cells) {
  const keep = env.COMMIT ?? sha;
  await env.TRACE.batch([
    env.TRACE.prepare(`INSERT INTO build SELECT ?2, ?1 WHERE NOT EXISTS (${LACKING}) ON CONFLICT (sha) DO UPDATE SET cells = ?1`)
      .bind(cells, sha),
    env.TRACE.prepare("DELETE FROM build WHERE sha NOT IN (?1, ?2) AND ?1 IN (SELECT sha FROM build)").bind(sha, keep),
    env.TRACE.prepare("DELETE FROM cell_json WHERE hash NOT IN (SELECT value FROM build, json_each(build.cells))"),
  ]);
  const { results: kept } = await env.TRACE.prepare("SELECT sha, cells FROM build").all();
  if (!kept.some((b) => b.sha === sha && b.cells === cells)) return new Response("A cell went missing, so load again", { status: 409 });
  const keys = new Set(kept.flatMap((b) => [`${PREFIX}${b.sha}.json`, ...Object.values(JSON.parse(b.cells)).map((h) => `${PREFIX}cells/${h}.json`)]));
  for (let cursor; ;) {
    const listed = await env.BLOBS.list({ prefix: PREFIX, cursor });
    const old = listed.objects.map((o) => o.key).filter((key) => !keys.has(key));
    if (old.length) await env.BLOBS.delete(old);
    if (!listed.truncated) break;
    cursor = listed.cursor;
  }
  return new Response("Loaded every cell");
}
