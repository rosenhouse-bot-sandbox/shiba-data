// Serves each plan PDF from the R2 bucket, where the Pipeline workflow stores it as blobs/<sha256>.
// /blobs/<sha256>.txt serves a model prompt, which the Pipeline workflow stores the same way.
// The static site comes from the assets directory.
// CI downloads every blob through this route too, so it needs no R2 credentials.
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    // Until #181 serves traces from D1, web/build.py writes each one as a static file.
    if (/^\/trace\/\d+\/main\/[^/]+\/[^/.]+$/.test(url.pathname)) {
      return env.ASSETS.fetch(new Request(new URL(`${url.pathname}.json`, url), request));
    }
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
