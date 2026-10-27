# Data pipeline

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
    documents[documents.csv]:::state
    subgraph generated [generated/]
      plans[plans.csv]:::state
      checked[documents_checked.csv]:::state
      citations[citations.csv]:::state
      sheets[main_chart.csv, dvha.csv]:::state
    end
    eoccites[machine/eoc_citations.csv]:::state
    edits[edits.csv]:::state
    comments[comments.csv]:::state
  end

  subgraph release [GitHub release]
    tar[(documents.tar:<br>PDFs, documents.json)]:::state
  end

  subgraph web [GitHub Pages]
    site[(index.html, app.js,<br>data.json, PDFs)]:::state
  end

  findurls[Find document URLs]:::heavy
  universe[universe.py]:::det
  fetch[fetch_docs.py:<br>download, extract text,<br>check covers]:::det
  review[Read SBs and EOCs;<br>write edits]:::heavy
  cite[cite.py: naturopathy]:::det
  gen[main_chart.py, dvha.py]:::det

  carriers --> findurls --> documents
  cms --> universe --> plans
  documents & plans --> fetch --> checked
  carriers --> fetch
  checked --> review --> edits
  checked --> cite --> citations
  cms & plans --> gen --> sheets

  extract[blanks.py, filled.py:<br>quote the EOC for each cell]:::cheap
  verify[Verify quotes against decoys;<br>write comments]:::heavy

  tar & sheets --> extract --> verify --> eoccites & comments

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

- `pipeline/run.py` regenerates `generated/`. People and models write the other CSVs.
- `pipeline/layers.py` applies `generated/citations.csv` and then `edits.csv` to the generated sheets. Rows in `machine/eoc_citations.csv` only cite values.
- `pipeline/blanks.py` and `pipeline/filled.py` turn small-model answers into `machine/eoc_citations.csv` rows. Their docstrings list the steps.
- `pipeline/eval.py <year> [<machine.csv>]` scores machine-written cells against the live data.
- The Site workflow downloads PDFs from carriers only when no documents release exists.
