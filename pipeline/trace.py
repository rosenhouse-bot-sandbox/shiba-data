"""Builds a year's trace database, and shows how one cell got its value (#178).

Usage:
  python3 -I pipeline/trace.py build <year> <out.sqlite> <commit sha>
  python3 -I pipeline/trace.py cell <db> <sheet> <plan_id> <col>
  python3 -I pipeline/trace.py page <work_dir> <pdf sha256> <page>

`cell` prints JSON. Each record has a status: "traced", "none" when no step touched the cell,
"not_traced_yet" when a later milestone of #181 fills it, or "not_recorded" when nothing kept the record.
`page` prints a page's layout text from a run's <work_dir>/texts, where blobs.py puts it.
"""
import csv, json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import blobs, eoc, fields, layers, present, years

REPO_URL = "https://github.com/rosenhouse-bot-sandbox/shiba-data"
TRACED, NONE, NOT_YET, NOT_RECORDED = "traced", "none", "not_traced_yet", "not_recorded"
MODEL_STEPS = ("blanks", "filled")
DRAFT_CODE = {"main": ("pipeline/main_chart.py", "chart_row"), "dvha": ("pipeline/dvha.py", "dvha_row")}


def read(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def insert(db, table, rows):
    rows = list(rows)
    if rows:
        names = list(rows[0])
        db.executemany(f"INSERT INTO {table} ({', '.join(map(quoted, names))}) VALUES ({', '.join('?' * len(names))})",
                       [[r[n] for n in names] for r in rows])


def quoted(name):
    return f'"{name}"'


def sheet_cells(sheets):
    return [dict(sheet=sheet, plan_id=r["plan_id"], col=col, value=r[col])
            for sheet, sheet_rows in sheets.items() for r in sheet_rows for col in fields.labels(sheet)]


def build(year, out, sha):
    data = years.data_dir(year)
    if os.path.exists(out):
        os.remove(out)
    db = sqlite3.connect(out)
    with open(os.path.join(HERE, "trace.sql")) as f:
        db.executescript(f.read())
    db.execute("INSERT INTO build VALUES (?, ?, ?)", (sha, year, (data / "steps.json").read_text()))
    insert(db, "plan", (dict(p, position=n) for n, p in enumerate(read(data / "generated/plans.csv"))))
    documents = read(data / "generated/documents.csv")
    insert(db, "document", (dict(url=d["url"], position=n, kind=d["kind"], found_via=d["found_via"])
                            for n, d in enumerate(documents)))
    insert(db, "plan_document", (dict(plan_id=p, url=d["url"]) for d in documents for p in d["plan_ids"].split(";")))
    checked = read(data / "generated/documents_checked.csv")
    insert(db, "download", (dict(url=d["url"], sha256=d["sha256"] or None, pages=number(d["pages"]),
                                 cover_problems=d["cover_problems"], baseline=d["baseline"],
                                 baseline_file=d["baseline_file"]) for d in checked))
    insert(db, "text", (dict(pdf=t["pdf"], plain=t["text"], layout=t["layout"], items=t["items"])
                        for t in read(data / "generated" / blobs.TEXTS)))
    insert(db, "draft_cell", sheet_cells(layers.generated(data)))
    insert(db, "cms_source", (renamed(r) for r in read(data / "generated/cms_sources.csv")))
    load_layers(db, data, checked)
    insert(db, "comment", (dict(renamed(c), pdf_page=number(c["pdf_page"])) for c in read(data / "comments.csv")))
    insert(db, "struck_quote", (renamed(s) for s in layers.strikes(data)))
    db.commit()
    db.close()


def number(text):
    return int(text) if text else None


def renamed(row):
    """The row with `column` named `col`."""
    return {("col" if k == "column" else k): v for k, v in row.items()}


def load_layers(db, data, checked):
    insert(db, "layer_row", (dict(
        layer=name, position=r["position"], step=r.get("step"), prompt=r.get("prompt"), sheet=r["sheet"],
        plan_id=r["plan_id"], col=r["column"], line=number(r["line"]), value=r["value"], url=r["url"],
        pdf_page=number(r["pdf_page"]), quote=r["quote"], saw=r.get("saw"), source=r.get("source"),
        author=r.get("author"), note=r.get("note")) for name in layers.LAYERS for r in layers.layer(data, name)))
    for step, name in enumerate(layers.LAYERS):
        insert(db, "layer_value", (dict(c, step=step, layer=name)
                                   for c in sheet_cells(layers.live(data, layers.LAYERS[:step + 1])[0])))
    _, cited = layers.citations(data, {d["url"]: d["kind"] for d in checked})
    insert(db, "live_citation", (dict(layer=c["layer"], position=c["position"], site_order=n, hidden=c["hidden"])
                                 for n, c in enumerate(cited)))


def rows(db, sql, *args):
    cursor = db.execute(sql, args)
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, r)) for r in cursor]


def record(found, **more):
    return dict(status=TRACED if found else NONE, **more)


def layer_rows(db, sheet, plan_id, col):
    """The cell's layer rows in the site's order, without the columns their layer lacks."""
    found = rows(db, """SELECT r.layer, r.step, r.prompt, r.line, r.value, r.url, r.pdf_page, r.quote,
                               r.saw, r.source, r.author, r.note, c.hidden
                        FROM layer_row r JOIN live_citation c USING (layer, position)
                        WHERE r.sheet = ? AND r.plan_id = ? AND r.col = ? ORDER BY c.site_order""", sheet, plan_id, col)
    return [{k: v for k, v in r.items() if v is not None} for r in found]


def cell(db, sheet, plan_id, col):
    """The records of #178 for one cell, read from that cell's rows only."""
    found = rows(db, "SELECT value FROM draft_cell WHERE sheet = ? AND plan_id = ? AND col = ?", sheet, plan_id, col)
    if not found:
        raise LookupError(f"No cell {sheet} {plan_id} {col}")
    build_row = rows(db, "SELECT sha, year, steps FROM build")[0]
    code = f"{REPO_URL}/blob/{build_row['sha']}/"
    values = rows(db, "SELECT layer, value FROM layer_value WHERE sheet = ? AND plan_id = ? AND col = ? ORDER BY step",
                  sheet, plan_id, col)
    cited = layer_rows(db, sheet, plan_id, col)
    setters = [r["layer"] for r in cited if r["layer"] not in layers.CITE_ONLY]
    documents = rows(db, """SELECT d.kind, d.url, d.found_via, w.sha256, w.pages, w.cover_problems, w.baseline,
                                   t.plain, t.layout, t.items
                            FROM plan_document p JOIN document d USING (url) JOIN download w USING (url)
                            LEFT JOIN text t ON t.pdf = w.sha256 WHERE p.plan_id = ? ORDER BY d.position""", plan_id)
    for d in documents:
        d["text"] = {k: d.pop(k) for k in ("plain", "layout", "items")}
    cms = rows(db, "SELECT file, field, title, value, meaning FROM cms_source WHERE plan_id = ? AND col = ?", plan_id, col)
    file, function = DRAFT_CODE[sheet]
    has_rule = sheet == "main" and col in present.COLUMNS
    model = [dict(r, answers={"status": NOT_RECORDED if r["step"] == "xref" else NOT_YET})
             for r in cited if r.get("step") in MODEL_STEPS + ("xref",)]
    return {
        "cell": dict(year=build_row["year"], sheet=sheet, plan_id=plan_id, col=col, label=fields.labels(sheet)[col],
                     value=values[-1]["value"]),
        "plan": record(True, row=rows(db, "SELECT * FROM plan WHERE plan_id = ?", plan_id)[0],
                       landscape_row={"status": NOT_YET}),
        "documents": record(documents, documents=documents),
        "draft": record(True, value=found[0]["value"], code=dict(file=file, function=function, url=code + file),
                        # cms_sources.csv covers some columns. Milestone 3 covers the rest.
                        cms_fields=record(cms, rows=cms) if cms else {"status": NOT_YET}),
        "answers": {"status": NOT_YET if has_rule else NONE},
        "fact_checks": {"status": NOT_YET if has_rule else NONE},
        "rule": {"status": NOT_YET} if has_rule else {"status": NONE},
        "added_facts": {"status": NOT_YET if has_rule else NONE},
        "notes": record(n := rows(db, "SELECT kind, comment, url, pdf_page, quote FROM comment WHERE sheet = ? AND plan_id = ? "
                                      "AND col = ?", sheet, plan_id, col), rows=n),
        "struck_quotes": record(s := rows(db, "SELECT quote, note FROM struck_quote WHERE sheet = ? AND plan_id = ? AND col = ?",
                                          sheet, plan_id, col), rows=s),
        # Without rows, milestone 6 tells a cell the model steps asked about from one they left alone.
        "model_citations": record(model, rows=model) if model else {"status": NOT_YET},
        "layers": record(True, draft=found[0]["value"], applied=[
            dict(layer=v["layer"], value=v["value"], rows=[r for r in cited if r["layer"] == v["layer"]]) for v in values],
            live=dict(value=values[-1]["value"], set_by=setters[0] if setters else None,
                      citations=[r for r in cited if not r["hidden"]]),
            hidden=[r for r in cited if r["hidden"]]),
        "build": record(True, sha=build_row["sha"], steps=json.loads(build_row["steps"]), code=code),
    }


def page(work, sha256, n):
    return eoc.load_pages(blobs.text_path(work, "layout", sha256))[int(n)]


def main(command=None, *args):
    if command == "build" and len(args) == 3:
        build(int(args[0]), args[1], args[2])
    elif command == "cell" and len(args) == 4:
        db = sqlite3.connect(f"file:{args[0]}?mode=ro", uri=True)
        print(json.dumps(cell(db, *args[1:]), indent=1, ensure_ascii=False))
    elif command == "page" and len(args) == 3:
        print(page(*args))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(*sys.argv[1:])
