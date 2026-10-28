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

  subgraph release [GitHub release]
    tar[(documents.tar:<br>PDFs, documents.json)]:::state
  end

  subgraph web [GitHub Pages]
    site[(index.html, app.js,<br>data.json, PDFs)]:::state
  end

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

  docwf[Documents workflow, manual:<br>build.py documents]:::det
  sitewf[Site workflow:<br>tests, build.py site,<br>deploy from main]:::det

  checked --> docwf
  carriers --> docwf --> tar
  docwf -. triggers .-> sitewf
  tar & git --> sitewf --> site
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
- The Site workflow downloads PDFs from carriers only when no documents release exists.
