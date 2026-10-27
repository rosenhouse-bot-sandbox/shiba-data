# Volunteer web UI

A static site for comparing the 2027 Multnomah/Clackamas plans in `repro/data`.
Clicking a cell opens the plan document next to the sheet.
A cell with a citation opens its page and highlights the quote.

The `Site` workflow builds the site, downloads the plan PDFs, runs the tests, and deploys `main` to GitHub Pages.

## Local build

```sh
python3 -I web/build.py _site --pdfs
python3 -m http.server -d _site
```

## Tests

```sh
cd web
python3 -I -m unittest discover -s tests
node --test tests/highlight.test.mjs
npm ci && SITE=../_site node --test tests/e2e.test.mjs
```
