# Volunteer web UI

A static site for comparing the plans in `data/<year>`, where `pipeline/years.py` names the live year.
Clicking a cell opens the plan document next to the sheet.
A cell with a citation opens its page and highlights the quote.

[`docs/pipeline.md`](../docs/pipeline.md) diagrams how the data is made.

The plan PDFs come from the GitHub release that `documents_release` in `data/<year>/config.json` names.
The `Site` workflow builds the site from that release, runs the tests, and deploys `main` to a Cloudflare Worker (`wrangler.toml`).
The build fails if the release lacks a document in `documents_checked.csv`.

When a carrier re-issues a PDF:
1. Run the `Documents` workflow on `main`. It cuts a release of the PDFs the carriers serve now, each named by its own hash, and lists the re-issued ones.
2. In one PR, update `documents_checked.csv` and the citations to the re-issued PDFs, and point `documents_release` at the new release.
Then `sheet_sync.py` updates the Google Sheet named by `sheet_id` in `data/<year>/config.json`.
It matches rows by plan ID and columns by header, so volunteers' comments stay on their cells.
It signs in as the `sheets-sync` service account through Workload Identity Federation.

## Local build

```sh
gh release download "$(jq -r .documents_release data/2027/config.json)" --pattern documents.tar && mkdir -p _documents && tar -xf documents.tar -C _documents
python3 -I web/build.py site _site _documents
python3 -m http.server -d _site
```

## Tests

```sh
cd web
python3 -I -m unittest discover -s tests
node --test tests/highlight.test.mjs
npm ci && SITE=../_site node --test tests/e2e.test.mjs
```
