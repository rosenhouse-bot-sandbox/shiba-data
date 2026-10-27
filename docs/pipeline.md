# Data pipeline

```mermaid
flowchart TB
  classDef det fill:#d9f2d9,stroke:#2e7d32,color:#000
  classDef cheap fill:#fff3c4,stroke:#b8860b,color:#000
  classDef heavy fill:#f8d0d0,stroke:#b71c1c,color:#000
  classDef state fill:#fff,stroke:#555,color:#000

  subgraph external [Internet]
    cms[(CMS Landscape and<br>PBP Benefits files)]:::state
    carriers[(Carrier sites:<br>SB and EOC PDFs)]:::state
  end

  subgraph git [Git source: repro/data]
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

  find[Find document URLs]:::heavy
  universe[universe.py]:::det
  fetch[fetch_docs.py:<br>download, extract text,<br>check covers]:::det
  review[Read SBs and EOCs;<br>write overrides]:::heavy
  cite[cite.py: find quote pages]:::det
  gen[main_chart.py, dvha.py]:::det

  carriers --> find --> documents
  cms --> universe --> plans
  documents & plans --> fetch --> checked
  carriers --> fetch
  checked --> review --> facts
  facts & checked --> cite --> citations
  cms & plans & citations --> gen --> sheets

  subgraph xref [EOC/SB cross-reference, run outside the repo]
    retrieve[Retrieve pages per field]:::det
    extract[Blind extract with quotes]:::cheap
    validate[Quote and amount checks;<br>compare with cell]:::det
    judge[Judge disagreements]:::cheap
    verify[Two verifiers:<br>Sonnet and Opus]:::heavy
    write[Write and recheck comments]:::heavy
  end

  tar & sheets --> retrieve --> extract --> validate
  validate -- agree --> verify --> eoccites
  validate -- disagree --> judge --> write --> comments
  write -- EOC contradicts cell --> facts

  docwf[Documents workflow, manual:<br>build.py documents]:::det
  sitewf[Site workflow, on push to main:<br>tests, build.py site, deploy]:::det

  checked --> docwf
  carriers --> docwf --> tar
  docwf -. triggers .-> sitewf
  tar & git --> sitewf --> site
```

| Color | Step |
|---|---|
| Green | Deterministic code. |
| Yellow | Cheap model (Haiku). |
| Red | Heavier model (Sonnet or Opus), or an agent with a browser. |

- Steps in `repro/run.sh` regenerate every CSV above except `documents.csv`, `sb_facts.csv`, `eoc_citations.csv` and `comments.csv`. Those are written by models and reviewed in pull requests.
- The cross-reference scripts are not in the repo. Issue #8 describes them. The models ran as Claude Code subagents, not through the API.
- The Site workflow never contacts carriers. Only the Documents workflow downloads PDFs.
