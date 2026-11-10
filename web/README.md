# Volunteer web UI

A static site for comparing the plans in `data/<year>`, where `pipeline/years.py` names the live year.
Clicking a cell opens the plan document next to the sheet.
A cell with a citation opens its page and highlights the quote.
The URL is a permalink to the open cell and page; `static/permalink.js` describes its form.

[`docs/pipeline.md`](../docs/pipeline.md) diagrams how the data is made.

The Pipeline workflow stores each plan PDF in the R2 bucket `pdxplans` as `blobs/<sha256>`.
The `Site` workflow builds the site, runs the tests against those PDFs, and deploys `main` to the `pdxplans` Worker (`wrangler.toml`).
`worker.js` serves each PDF the site links as `docs/<sha256>.pdf`. The e2e tests fail if the bucket lacks one.

After deploying, `sheet_sync.py` updates the Google Sheet named by `sheet_id` in `data/<year>/config.json`.
It matches rows by plan ID and columns by header, so volunteers' comments stay on their cells.
It signs in as the `sheets-sync` service account through Workload Identity Federation.

## Local build

```sh
(cd web && npm ci)
python3 -I web/build.py site _site
npx wrangler dev --remote
```

The site serves pdf.js from `web/node_modules`, so it loads no third-party code.
`static/_headers` sets its content security policy, which the e2e tests apply too.

## Tests

```sh
cd web
python3 -I -m unittest discover -s tests
node --test tests/highlight.test.mjs tests/ago.test.mjs tests/permalink.test.mjs tests/worker.test.mjs tests/pipeline.test.mjs
npm ci && SITE=../_site DOCS=<dir of <sha256>.pdf> node --test tests/e2e.test.mjs
```

## Web platform guidance

Web UI work should follow [Modern Web Guidance](https://github.com/GoogleChrome/modern-web-guidance).
Claude sessions load it from `.claude/skills/modern-web-guidance`, which searches the guides before writing HTML, CSS or client-side JavaScript.
Without the skill, read the guides in that repository.

The site targets Baseline Widely available features.
It may use a newer feature behind feature detection, with a fallback of a few lines.
It should not add polyfills or runtime dependencies.
