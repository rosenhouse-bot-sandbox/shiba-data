# Volunteer web UI

A static site for comparing the 2027 Multnomah/Clackamas plans in `repro/data`.
Clicking a cell opens the plan document next to the sheet.
A cell with a citation opens its page and highlights the quote.

The plan PDFs come from the latest GitHub release.
The `Documents` workflow downloads them from the carrier sites, cuts a new release, and redeploys the site.
The `Site` workflow builds the site from that release, runs the tests, and deploys `main` to GitHub Pages.

## Local build

```sh
gh release download --pattern documents.tar && mkdir -p _documents && tar -xf documents.tar -C _documents
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
