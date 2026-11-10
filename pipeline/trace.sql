-- A year's trace database (#178). pipeline/trace.py builds it.

-- replayed is 1 when the build read a run's ledger of prompts, and checked when it read the run's check outcomes.
CREATE TABLE build (
  sha      TEXT PRIMARY KEY,
  year     INTEGER NOT NULL,
  steps    TEXT NOT NULL,  -- steps.json
  replayed INTEGER NOT NULL,
  checked  INTEGER NOT NULL
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

-- value keeps a cell's lines, separated by " | ".
CREATE TABLE draft_cell (
  sheet   TEXT NOT NULL CHECK (sheet IN ('main', 'dvha')),
  plan_id TEXT NOT NULL REFERENCES plan,
  col     TEXT NOT NULL,
  value   TEXT NOT NULL,
  PRIMARY KEY (sheet, plan_id, col)
);

-- One row of a layer file. position is the row's place in its file, where a later edit wins.
-- line is NULL for a whole cell.
CREATE TABLE layer_row (
  layer    TEXT NOT NULL,
  position INTEGER NOT NULL,
  sheet    TEXT NOT NULL,
  plan_id  TEXT NOT NULL,
  col      TEXT NOT NULL,
  line     INTEGER,
  value    TEXT NOT NULL,
  url      TEXT NOT NULL,
  pdf_page INTEGER,
  quote    TEXT NOT NULL,
  saw      TEXT,
  source   TEXT,
  author   TEXT,
  note     TEXT,
  PRIMARY KEY (layer, position),
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
-- site_order orders a cell's rows as the site lists them.
CREATE TABLE live_citation (
  layer      TEXT NOT NULL,
  position   INTEGER NOT NULL,
  site_order INTEGER NOT NULL,
  hidden     TEXT NOT NULL,
  PRIMARY KEY (layer, position),
  FOREIGN KEY (layer, position) REFERENCES layer_row
);

CREATE TABLE comment (
  sheet    TEXT NOT NULL,
  plan_id  TEXT NOT NULL,
  col      TEXT NOT NULL,
  kind     TEXT NOT NULL,
  comment  TEXT NOT NULL,
  url      TEXT NOT NULL,
  pdf_page INTEGER,
  quote    TEXT NOT NULL,
  PRIMARY KEY (sheet, plan_id, col),
  FOREIGN KEY (sheet, plan_id, col) REFERENCES draft_cell
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

-- Each line a present.py rule returned for a cell. presented is 0 when no document fact backs the line, so
-- the line keeps its other layers' value. held is the pinned version's reason for leaving the whole cell alone.
CREATE TABLE rule_line (
  sheet     TEXT NOT NULL,
  plan_id   TEXT NOT NULL REFERENCES plan,
  col       TEXT NOT NULL,
  line      INTEGER NOT NULL,
  value     TEXT NOT NULL,
  presented INTEGER NOT NULL,
  held      TEXT,
  PRIMARY KEY (sheet, plan_id, col, line)
);

-- Each fact a rule considered. A used fact names its line. A set-aside fact has no line, and reasons is a JSON array.
CREATE TABLE rule_fact (
  sheet   TEXT NOT NULL,
  plan_id TEXT NOT NULL,
  col     TEXT NOT NULL,
  line    INTEGER,
  fact_id TEXT NOT NULL,
  source  TEXT NOT NULL,
  doc_sha TEXT NOT NULL,
  page    TEXT NOT NULL,
  reasons TEXT,
  FOREIGN KEY (fact_id, source, doc_sha, page) REFERENCES fact
);
CREATE INDEX rule_fact_cell ON rule_fact (sheet, plan_id, col);

-- Each Landscape field a plans.csv column read (universe.py).
CREATE TABLE landscape_read (
  plan_id    TEXT NOT NULL REFERENCES plan,
  plan_field TEXT NOT NULL,
  position   INTEGER NOT NULL,
  field      TEXT NOT NULL,
  value      TEXT NOT NULL,
  PRIMARY KEY (plan_id, plan_field, position)
);

-- Each prompt a run sent, by the sha256 of its text, which R2 keeps as blobs/<prompt_sha>.
-- dir is the task's folder under the run's work dir, such as facts/ambulance/read.
CREATE TABLE task (
  prompt_sha TEXT NOT NULL,
  answer_key TEXT NOT NULL REFERENCES answer,
  dir        TEXT NOT NULL,
  task       TEXT NOT NULL,
  PRIMARY KEY (prompt_sha, answer_key, dir, task)
);
CREATE INDEX task_answer ON task (answer_key);

-- A saved answer in data/<year>/answers/<key>.json.
CREATE TABLE answer (
  key    TEXT PRIMARY KEY,
  model  TEXT NOT NULL,
  effort TEXT,
  batch  INTEGER NOT NULL,
  reply  TEXT NOT NULL,
  usage  TEXT NOT NULL
);

-- Each item of a reader's answer, and why the code checks rejected it (extract.py). problem is NULL when the item
-- passed, and the fact columns then name its fact. plan_id and benefit are as stated, or NULL if not text.
-- skipped says why the verifier did not check a fact that passed (document_facts.py).
CREATE TABLE stated (
  prompt_sha TEXT NOT NULL,
  item       INTEGER NOT NULL,
  doc_sha    TEXT NOT NULL,
  plan_id    TEXT,
  benefit    TEXT,
  answer     TEXT NOT NULL,
  problem    TEXT,
  fact_id    TEXT,
  source     TEXT,
  page       TEXT,
  skipped    TEXT,
  PRIMARY KEY (prompt_sha, item)
);
CREATE INDEX stated_plan ON stated (plan_id);
CREATE INDEX stated_doc ON stated (doc_sha);
CREATE INDEX stated_fact ON stated (fact_id, source, doc_sha, page);

-- Each verdict on an item of a verifier or reviewer task (extract.py, review.py). A decoy names no fact.
-- ok is NULL when the answer gave no verdict. earlier is 1 for a trusted fact's saved verdict from an earlier run.
CREATE TABLE verdict (
  step       TEXT NOT NULL CHECK (step IN ('verifier', 'reviewer')),
  prompt_sha TEXT NOT NULL,
  item       INTEGER NOT NULL,
  decoy      INTEGER NOT NULL,
  shown      TEXT,
  fact_id    TEXT,
  source     TEXT,
  doc_sha    TEXT,
  page       TEXT,
  ok         INTEGER,
  reason     TEXT NOT NULL,
  earlier    INTEGER NOT NULL,
  PRIMARY KEY (step, prompt_sha, item)
);
CREATE INDEX verdict_fact ON verdict (fact_id, source, doc_sha, page);
