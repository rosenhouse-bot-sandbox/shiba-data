# Data pipeline

Each plan year builds through a linear chain of steps. Only steps 1 to 3 read the web. Every later step reads only what an earlier step committed, so a rerun with the same inputs and saved model answers writes the same bytes. Issue #99 has the plan.

| Step | Code | Reads | Writes |
|---|---|---|---|
| 1 Plans | `universe.py` | CMS Landscape file | `generated/plans.csv` |
| 2 Locate documents | `find_docs.py`, with `find_on_carrier_pages.py`, `find_by_plan_page.py` and `find_regence.py` | Carrier sites, URL templates, `found.csv`, `links.csv` | `generated/documents.csv` |
| 3 Snapshot | `fetch_docs.py`, `texts.py` | `documents.csv` | PDFs and texts in R2, `generated/documents_checked.csv`, `generated/texts.csv` |
| 4 Extract facts | `document_facts.py`, `pbp_facts.py` | Texts, CMS PBP zip, saved answers | `machine/document_facts.csv`, `generated/pbp_facts.csv` |
| 5 Present | `present.py` | Facts, column rules in code | `generated/presented.csv` |
| 6 Publish | `web/build.py`, `web/sheet_sync.py` | Committed data, R2 | pdxplans.org and the Google Sheet |

Older steps still fill the columns that step 5 does not present yet: `main_chart.py` and `dvha.py` from CMS data, `blanks.py` and `filled.py` from the EOC, and people's `edits.csv` and `comments.csv`. `pipeline/layers.py` stacks these layers. `presented.csv` wins over the older steps, and `edits.csv` wins over everything.

## Facts

- A fact is one cost or coverage term for one plan, such as "ground ambulance, in network, $250 copay". `pipeline/facts.py` defines its fields and vocabulary.
- An EOC fact beats an SB fact, and an SB fact beats a PBP fact.
- `extract.py` sends a reader model each document's pages about one benefit group. A verifier model then accepts or rejects each fact against decoys that change one field. Every quote must appear exactly once on its page.
- `present.py` holds one rule per column. A cell cites the facts its rule used. `present.HELD` lists cells whose readers missed part of the value, so other layers keep them.

## Model steps

- `ask.py` sends tasks through the Message Batches API at half price. It saves each answer in `answers/`, keyed by the model, effort and task text, so a rerun pays only for new tasks.
- `data/<year>/steps.json` pins a version of each model step. A new version deploys in three steps: merge it unpinned, run it on main with the Pipeline workflow's `candidate` input (such as `document_facts@9`), then pin it in a follow-up PR.
- The Pipeline workflow runs `run.py <year> <work> api` on main and pushes the result to a new branch. Its `rebuild` input also reruns every model step from scratch into `rebuilds/<name>`. A full rebuild cost about $50 in November 2026.
- `evaluate.py`, run by the Evaluate workflow, scores reader and verifier models against an Opus reviewer and the expected cells.

## Checks

- The `reproduce` check replays every step after the snapshot from R2 blobs and saved answers, with no web or API access. It fails if any tracked file changes.
- The `build` check runs the unit tests and the site's browser tests. The browser tests fail if R2 lacks a PDF in `documents_checked.csv`.
