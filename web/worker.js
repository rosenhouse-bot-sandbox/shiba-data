// Serves each plan PDF from the R2 bucket, where the Pipeline workflow stores it as blobs/<sha256>.
// /blobs/<sha256>.txt serves a model prompt, which the Pipeline workflow stores the same way.
// The static site comes from the assets directory.
// CI downloads every blob through this route too, so it needs no R2 credentials.
// /trace/2027/<sheet>/<plan_id>/<col> serves a cell's trace from D1 once every cell of the deployed commit's build has
// loaded. Until then, and for other years, it serves the static file that web/build.py writes.
// /tables/2027/<sha>/<table>.json serves main_chart, dvha or presented of any build that D1 keeps.
// Only a build load may change anything, so every other request must be a GET or HEAD.
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
        "SELECT json FROM item WHERE hash = (SELECT items ->> ? FROM data_build WHERE sha = ?)")
        .bind(`$."${cell}"`, env.COMMIT).first().catch(() => null);
      if (row) {
        return new Response(row.json.replaceAll(COMMIT, env.COMMIT), { headers: { "Content-Type": "application/json; charset=utf-8" } });
      }
      return env.ASSETS.fetch(new Request(new URL(`${url.pathname}.json`, url), request));
    }
    const [, tableYear, tableBuild, table] = url.pathname.match(/^\/tables\/(\d+)\/([0-9a-f]{40})\/(\w+)\.json$/) ?? [];
    if (tableYear) return tableYear === D1_YEAR ? tableRows(env, tableBuild, table) : missing();
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

// CI loads each main build into D1 from R2: trace/<year>/<sha>.json names the file in trace/<year>/items/ that holds
// each item: a cell's trace, by <sheet>/<plan_id>/<col>, or the nth run of one plan's rows in a table, by tables/<table>/<n>/<plan_id>.
// CI repeats the load while it answers 409. Each load adds a few items that D1 lacks, so an item that did not change
// since an earlier build costs no writes. Once D1 has every item, the load adds the build.
// LOAD_TOKEN is a secret that the deploy job gives the Worker and the trace job derives the same way.
const D1_YEAR = "2027";
const COMMIT = "${commit}";
const PER_LOAD = 10;
const KEEP_BUILDS = 10;
const KEEP_MS = 5 * 24 * 60 * 60 * 1000;
const LOAD = new RegExp(`^/trace/${D1_YEAR}/load/([0-9a-f]{40})$`);
const PREFIX = `trace/${D1_YEAR}/`;
const SCHEMA = [
  "CREATE TABLE IF NOT EXISTS item (hash TEXT PRIMARY KEY, json TEXT NOT NULL)",
  "CREATE TABLE IF NOT EXISTS data_build (sha TEXT PRIMARY KEY, items TEXT NOT NULL, loaded INTEGER NOT NULL)",
  ...["cell_json", "build", "cell_trace", "loaded"].map((t) => `DROP TABLE IF EXISTS ${t}`),
];
const missing = () => new Response("Not found", { status: 404 });
const LACKING = "SELECT value AS hash FROM json_each(?1) WHERE value NOT IN (SELECT hash FROM item)";

async function tableRows(env, sha, table) {
  const { results } = await env.TRACE.prepare(
    "SELECT item.json FROM data_build, json_each(data_build.items) AS j JOIN item ON item.hash = j.value " +
    "WHERE data_build.sha = ? AND j.key GLOB ? ORDER BY j.id").bind(sha, `tables/${table}/*`).all().catch(() => ({ results: [] }));
  if (!results.length) return missing();
  const rows = results.map((r) => r.json.slice(1, -1));
  return new Response(`[${rows.join(",")}]`, { headers: { "Content-Type": "application/json; charset=utf-8" } });
}

async function load(env, sha) {
  const manifest = await (await env.BLOBS.get(`${PREFIX}${sha}.json`))?.json();
  if (!manifest) return missing();
  const items = JSON.stringify(manifest.items);
  await env.TRACE.batch(SCHEMA.map((sql) => env.TRACE.prepare(sql)));
  const { results: lacking } = await env.TRACE.prepare(LACKING).bind(items).all();
  if (lacking.length) {
    const some = lacking.slice(0, PER_LOAD);
    const texts = await Promise.all(some.map(async ({ hash }) => (await env.BLOBS.get(`${PREFIX}items/${hash}.json`))?.text()));
    if (texts.includes(undefined)) return missing();
    const insert = env.TRACE.prepare("INSERT OR IGNORE INTO item VALUES (?, ?)");
    await env.TRACE.batch(some.map(({ hash }, i) => insert.bind(hash, texts[i])));
    if (lacking.length > some.length) return new Response(`${lacking.length - some.length} items left to load`, { status: 409 });
  }
  return finish(env, sha, items);
}

// Adding a build drops each build that is older than KEEP_MS and not among the last KEEP_BUILDS, except the deployed
// one, and the items that only dropped builds used.
// A batch runs as one transaction, so an item that another build's load just dropped stops the build from being added.
async function finish(env, sha, items) {
  const now = Date.now();
  await env.TRACE.batch([
    env.TRACE.prepare(`INSERT INTO data_build SELECT ?2, ?1, ?3 WHERE NOT EXISTS (${LACKING}) ` +
      "ON CONFLICT (sha) DO UPDATE SET items = ?1, loaded = ?3").bind(items, sha, now),
    env.TRACE.prepare("DELETE FROM data_build WHERE sha != ?2 AND ?1 IN (SELECT sha FROM data_build) AND loaded < ?3 " +
      `AND sha NOT IN (SELECT sha FROM data_build ORDER BY loaded DESC LIMIT ${KEEP_BUILDS})`).bind(sha, env.COMMIT ?? sha, now - KEEP_MS),
    env.TRACE.prepare("DELETE FROM item WHERE hash NOT IN (SELECT value FROM data_build, json_each(data_build.items))"),
  ]);
  const { results: kept } = await env.TRACE.prepare("SELECT sha, items FROM data_build").all();
  if (!kept.some((b) => b.sha === sha && b.items === items)) return new Response("An item went missing, so load again", { status: 409 });
  const keys = new Set(kept.flatMap((b) => [`${PREFIX}${b.sha}.json`, ...Object.values(JSON.parse(b.items)).map((h) => `${PREFIX}items/${h}.json`)]));
  for (let cursor; ;) {
    const listed = await env.BLOBS.list({ prefix: PREFIX, cursor });
    const old = listed.objects.map((o) => o.key).filter((key) => !keys.has(key));
    if (old.length) await env.BLOBS.delete(old);
    if (!listed.truncated) break;
    cursor = listed.cursor;
  }
  return new Response("Loaded every item");
}
