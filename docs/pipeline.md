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
    plans[plans.csv]:::state
    checked[documents_checked.csv]:::state
    facts[sb_facts.csv]:::state
    citations[citations.csv]:::state
    sheets[main_chart.csv, dvha.csv,<br>pbp_vs_documents*.csv]:::state
    eoccites[eoc_citations.csv]:::state
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
  review[Read SBs and EOCs;<br>write overrides]:::heavy
  cite[cite.py: find quote pages]:::det
  gen[main_chart.py, dvha.py]:::det

  carriers --> findurls --> documents
  cms --> universe --> plans
  documents & plans --> fetch --> checked
  carriers --> fetch
  checked --> review --> facts
  facts & checked --> cite --> citations
  cms & plans & citations --> gen --> sheets

  extract[Read each EOC and SB blind;<br>quote values]:::cheap
  verify[Verify citations;<br>write comments]:::heavy

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

- Steps in `pipeline/run.py` regenerate every CSV above except `documents.csv`, `sb_facts.csv`, `eoc_citations.csv` and `comments.csv`. Models write those four.
- The Site workflow downloads PDFs from carriers only when no documents release exists.
