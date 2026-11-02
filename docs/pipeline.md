# Data pipeline

[pipeline-slides.md](pipeline-slides.md) walks through the same steps one slide at a time.

```mermaid
flowchart TB
  classDef det fill:#d9f2d9,stroke:#2e7d32,color:#000
  classDef cheap fill:#fff3c4,stroke:#b8860b,color:#000
  classDef heavy fill:#f8d0d0,stroke:#b71c1c,color:#000
  classDef state fill:#fff,stroke:#555,color:#000

  subgraph external [Internet]
    carriers[(Carrier sites:<br>SB and EOC PDFs)]:::state
    cms[(CMS Landscape and<br>PBP Benefits files)]:::state
  end

  subgraph git [Git source: data/year]
    finds[found.csv, links.csv]:::state
    subgraph generated [generated/]
      plans[plans.csv]:::state
      documents[documents.csv]:::state
      checked[documents_checked.csv]:::state
      citations[citations.csv]:::state
      sheets[main_chart.csv, dvha.csv]:::state
    end
    eoccites[machine/*.csv]:::state
    answers[answers/]:::state
    edits[edits.csv]:::state
    comments[comments.csv]:::state
  end

  subgraph r2 [R2 bucket pdxplans]
    blobs[(blobs/sha256:<br>PDFs, their texts, CMS zips)]:::state
  end

  subgraph web [Cloudflare Worker: pdxplans.org]
    site[(index.html, app.js,<br>data.json; PDFs from R2)]:::state
  end

  sheet[(Google Sheet:<br>volunteers comment)]:::state

  findurls[Find document URLs<br>in a browser or the Links sheet]:::heavy
  finddocs[find_docs.py:<br>URL templates]:::det
  universe[universe.py]:::det
  fetch[fetch_docs.py:<br>download, extract text,<br>check covers]:::det
  review[Read SBs and EOCs;<br>write edits]:::heavy
  cite[cite.py: naturopathy]:::det
  gen[main_chart.py, dvha.py]:::det

  carriers --> findurls --> finds
  finds & plans --> finddocs --> documents
  cms --> universe --> plans
  documents & plans --> fetch --> checked
  carriers --> fetch
  checked --> review --> edits
  checked --> cite --> citations
  cms & plans --> gen --> sheets

  extract[blanks.py, filled.py:<br>quote the EOC for each cell]:::cheap
  verify[Verify quotes against decoys;<br>write comments]:::heavy

  checked & sheets --> extract --> verify --> eoccites & answers

  sitewf[Site workflow:<br>tests, build.py site,<br>deploy from main,<br>sheet_sync.py]:::det

  fetch --> blobs
  blobs & git --> sitewf --> site & sheet
```

| Color | Step |
|---|---|
| Green | Deterministic code |
| Yellow | Cheap model (Haiku) |
| Red | Heavier model (Sonnet or Opus), or an agent with a browser |

- `pipeline/find_docs.py` lists plan documents from browser finds (`found.csv`), the volunteers' Links sheet (`links.csv`), and carrier URL templates, in that order of preference.
- `pipeline/run.py` regenerates `generated/`, `machine/blanks.csv` and `machine/filled.csv`. People and earlier Claude sessions wrote the other CSVs.
- The Pipeline workflow runs `run.py <year> <work> api` on main and pushes the result to a new branch. Only people with write access can start it.
- `pipeline/layers.py` applies `generated/citations.csv` and then `edits.csv` to the generated sheets. Rows in `machine/` only cite values.
- `pipeline/blanks.py` and `pipeline/filled.py` write model task files and turn the answers into `machine/` rows. Haiku reads, then Sonnet and Opus verify.
- `pipeline/ask.py` answers task files with the Claude API. It saves each answer in `answers/`, keyed by the model and the task's text, so a rerun calls a model only for new tasks.
- `pipeline/rebuild.py <year> <work> <name>` reruns the model steps with no saved answers or machine rows, on a copy with seeded errors. It saves the answers, rows and scores in `data/<year>/rebuilds/<name>`. The Pipeline workflow's `rebuild` input runs it.
- `pipeline/eval.py <year> [<machine.csv>]` scores machine-written cells against the live data. It also counts the edits that override the machine layer, by column and carrier.
- The Pipeline workflow uploads each fetched PDF, its texts and each CMS zip to R2 as `blobs/<sha256>` before it commits data that names them. `generated/texts.csv` records the texts' hashes. The next run downloads them, so a new pdftotext or pypdfium2 changes no text that models already read.
- The Site build's e2e tests fail if R2 lacks a PDF in `documents_checked.csv`.
- The Site workflow's `reproduce` job reruns `run.py replay` from those blobs and the saved answers, with no web or API access. It fails if any tracked file changes. It keeps the committed `documents.csv` and `documents_checked.csv`, so it does not check the steps that find and fetch documents.
