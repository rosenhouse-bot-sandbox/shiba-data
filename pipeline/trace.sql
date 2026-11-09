-- A year's trace database (#68). pipeline/trace.py builds it.

CREATE TABLE build (
  sha   TEXT PRIMARY KEY,
  year  INTEGER NOT NULL,
  steps TEXT NOT NULL  -- steps.json
);

CREATE TABLE plan (
  plan_id                        TEXT PRIMARY KEY,
  position                       INTEGER NOT NULL UNIQUE,
  section                        TEXT NOT NULL,
  plan_name                      TEXT NOT NULL,
  plan_type                      TEXT NOT NULL,
  organization                   TEXT NOT NULL,
  premium                        TEXT NOT NULL,
  premium_full_extra_help        TEXT NOT NULL,
  moop_in_network                TEXT NOT NULL,
  part_d_deductible              TEXT NOT NULL,
  tier_without_part_d_deductible TEXT NOT NULL,
  c_snp_conditions               TEXT NOT NULL,
  overall_star_rating            TEXT NOT NULL
);

CREATE TABLE document (
  url       TEXT PRIMARY KEY,
  position  INTEGER NOT NULL UNIQUE,
  kind      TEXT NOT NULL CHECK (kind IN ('SB', 'EOC', 'RIDER')),
  found_via TEXT NOT NULL
);

CREATE TABLE plan_document (
  plan_id TEXT NOT NULL REFERENCES plan,
  url     TEXT NOT NULL REFERENCES document,
  PRIMARY KEY (plan_id, url)
);

-- sha256 and pages are NULL when the download is not a PDF.
CREATE TABLE download (
  url            TEXT PRIMARY KEY REFERENCES document,
  sha256         TEXT,
  pages          INTEGER,
  cover_problems TEXT NOT NULL,
  baseline       TEXT NOT NULL,
  baseline_file  TEXT NOT NULL
);

-- Each text is a blob. trace.py page reads one page of it.
CREATE TABLE text (
  pdf    TEXT PRIMARY KEY,
  plain  TEXT NOT NULL,
  layout TEXT NOT NULL,
  items  TEXT NOT NULL
);

CREATE TABLE cms_file (
  name   TEXT PRIMARY KEY,
  sha256 TEXT NOT NULL
);

-- value keeps a cell's lines, separated by " | ".
CREATE TABLE draft_cell (
  sheet   TEXT NOT NULL CHECK (sheet IN ('main', 'dvha')),
  plan_id TEXT NOT NULL REFERENCES plan,
  col     TEXT NOT NULL,
  value   TEXT NOT NULL,
  PRIMARY KEY (sheet, plan_id, col)
);

-- generated/cms_sources.csv: the CMS fields behind some columns.
CREATE TABLE cms_source (
  plan_id TEXT NOT NULL REFERENCES plan,
  col     TEXT NOT NULL,
  file    TEXT NOT NULL,
  field   TEXT NOT NULL,
  title   TEXT NOT NULL,
  value   TEXT NOT NULL,
  meaning TEXT NOT NULL,
  PRIMARY KEY (plan_id, col, file, field)
);

-- facts.IDENTITY names a fact. fact_id alone repeats across an SB and an EOC.
CREATE TABLE fact (
  fact_id       TEXT NOT NULL,
  source        TEXT NOT NULL,
  doc_sha       TEXT NOT NULL,
  page          TEXT NOT NULL,
  origin        TEXT NOT NULL CHECK (origin IN ('document', 'pbp', 'added')),
  reviewed      INTEGER NOT NULL,
  plan_id       TEXT NOT NULL REFERENCES plan,
  benefit       TEXT NOT NULL,
  setting       TEXT NOT NULL,
  network       TEXT NOT NULL,
  provider_tier TEXT NOT NULL,
  condition     TEXT NOT NULL,
  package       TEXT NOT NULL,
  pool          TEXT NOT NULL,
  covered_by    TEXT NOT NULL,
  cost_kind     TEXT NOT NULL,
  amount        TEXT NOT NULL,
  unit          TEXT NOT NULL,
  "limit"       TEXT NOT NULL,
  quotes        TEXT NOT NULL,
  note          TEXT NOT NULL,
  PRIMARY KEY (fact_id, source, doc_sha, page)
);

-- One row of a layer file. position is the row's place in its file, where a later edit wins.
CREATE TABLE layer_row (
  id       INTEGER PRIMARY KEY,
  layer    TEXT NOT NULL,
  position INTEGER NOT NULL,
  step     TEXT,
  prompt   TEXT,
  sheet    TEXT NOT NULL,
  plan_id  TEXT NOT NULL,
  col      TEXT NOT NULL,
  line     INTEGER NOT NULL,
  value    TEXT NOT NULL,
  url      TEXT NOT NULL,
  pdf_page TEXT NOT NULL,
  quote    TEXT NOT NULL,
  saw      TEXT,
  source   TEXT,
  author   TEXT,
  note     TEXT,
  UNIQUE (layer, position),
  FOREIGN KEY (sheet, plan_id, col) REFERENCES draft_cell
);
CREATE INDEX layer_row_cell ON layer_row (sheet, plan_id, col);

-- A cell's value after each layer, in the order the layers apply.
CREATE TABLE layer_value (
  sheet   TEXT NOT NULL,
  plan_id TEXT NOT NULL,
  col     TEXT NOT NULL,
  step    INTEGER NOT NULL,
  layer   TEXT NOT NULL,
  value   TEXT NOT NULL,
  PRIMARY KEY (sheet, plan_id, col, step),
  FOREIGN KEY (sheet, plan_id, col) REFERENCES draft_cell
);

-- What the site does with each layer row: shows it, or hides it for a reason in layers.py.
-- position orders a cell's rows as the site lists them.
CREATE TABLE live_citation (
  layer_row INTEGER PRIMARY KEY REFERENCES layer_row,
  position  INTEGER NOT NULL,
  hidden    TEXT NOT NULL
);

CREATE TABLE comment (
  sheet    TEXT NOT NULL,
  plan_id  TEXT NOT NULL,
  col      TEXT NOT NULL,
  kind     TEXT NOT NULL,
  comment  TEXT NOT NULL,
  url      TEXT NOT NULL,
  pdf_page TEXT NOT NULL,
  quote    TEXT NOT NULL,
  PRIMARY KEY (sheet, plan_id, col),
  FOREIGN KEY (sheet, plan_id, col) REFERENCES draft_cell
);

CREATE TABLE struck_quote (
  sheet   TEXT NOT NULL,
  plan_id TEXT NOT NULL,
  col     TEXT NOT NULL,
  quote   TEXT NOT NULL,
  note    TEXT NOT NULL,
  PRIMARY KEY (sheet, plan_id, col, quote)
);
