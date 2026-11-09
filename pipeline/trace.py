"""Builds a year's trace database, and shows how one cell got its value (#178).

Usage:
  python3 -I pipeline/trace.py build <year> <out.sqlite> <commit sha> [<work_dir>]
  python3 -I pipeline/trace.py cell <db> <sheet> <plan_id> <col>
  python3 -I pipeline/trace.py check <db>
  python3 -I pipeline/trace.py page <work_dir> <pdf sha256> <page>

`cell` prints JSON. Each record has a status: "traced", "none" when no step touched the cell,
"not_traced_yet" when the trace does not cover it yet, as for some DVHA cells, or "not_recorded" when nothing kept
the record. With a work_dir from a run, `build` adds the run's prompts, their saved answers and the checks' outcomes.
`check` fails if a main cell has a record left not traced yet.
`page` prints a page's layout text from a run's <work_dir>/texts, where blobs.py puts it.
"""
import csv, glob, json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ask, blobs, eoc, extract, facts, fields, layers, present, steps, years

REPO_URL = "https://github.com/rosenhouse-bot-sandbox/shiba-data"
PROMPT_URL = "https://pdxplans.org/blobs/{}.txt"
TRUSTED_WITHOUT_REVIEW = "trusted without review (#170)"
TRACED, NONE, NOT_YET, NOT_RECORDED = "traced", "none", "not_traced_yet", "not_recorded"
MODEL_STEPS = ("blanks", "filled")
FACT_FILES = {"document": "machine/document_facts.csv", "pbp": "generated/pbp_facts.csv", "added": present.ADDED}
FACT_COLUMNS = ", ".join(f'f."{c}"' for c in facts.COLUMNS)
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


def build(year, out, sha, work=None):
    data = years.data_dir(year)
    if os.path.exists(out):
        os.remove(out)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    db = sqlite3.connect(out)
    try:
        with open(os.path.join(HERE, "trace.sql")) as f:
            db.executescript(f.read())
        ledger = bool(work) and os.path.exists(os.path.join(work, blobs.LEDGER))
        outcomes = ledger and bool(outcome_files(work))
        db.execute("INSERT INTO build VALUES (?, ?, ?, ?, ?)", (sha, year, (data / "steps.json").read_text(), ledger, outcomes))
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
        insert(db, "cms_read", (dict(renamed(r), position=n) for n, r in enumerate(read(data / "generated/cms_reads.csv"))))
        insert(db, "landscape_read", (dict(r, position=n) for n, r in enumerate(read(data / "generated/landscape_reads.csv"))))
        load_layers(db, data, checked)
        reviewed = {facts.identity(f) for f in read(data / "machine/reviewed_facts.csv")}
        insert(db, "fact", (dict(f, origin=origin, reviewed=int(facts.identity(f) in reviewed))
                            for origin, path in FACT_FILES.items() for f in read(data / path)))
        load_rules(db, data)
        if ledger:
            load_answers(db, data, work)
        if outcomes:
            load_checks(db, work)
        insert(db, "comment", (dict(renamed(c), pdf_page=number(c["pdf_page"])) for c in read(data / "comments.csv")))
        insert(db, "struck_quote", (renamed(s) for s in layers.strikes(data)))
        db.commit()
    finally:
        db.close()


def outcome_files(work):
    return sorted(glob.glob(os.path.join(work, "facts", "**", extract.OUTCOMES), recursive=True))


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


def load_answers(db, data, work):
    """Loads the replay's ledger and the saved answers it names. Fails if a kept prompt does not hash to its answer's key."""
    tasks = list({tuple(t.values()): t for t in read(os.path.join(work, blobs.LEDGER))}.values())
    for t in tasks:
        with open(os.path.join(work, blobs.PROMPTS, t["prompt"]), encoding="utf-8") as f:
            if ask.key(t["model"], f.read(), t["effort"] or None) != t["key"]:
                raise ValueError(f"The prompt {t['prompt']} does not hash to the key of {t['dir']}/{t['task']}")
    insert(db, "task", (dict(prompt_sha=t["prompt"], answer_key=t["key"], dir=t["dir"], task=t["task"]) for t in tasks))
    answers = []
    for key in sorted({t["key"] for t in tasks}):
        with open(data / "answers" / f"{key}.json", encoding="utf-8") as f:
            a = json.load(f)
        answers.append(dict(key=key, model=a["model"], effort=a.get("effort"), batch=int(a.get("batch", False)),
                            reply=a["reply"], usage=json.dumps(a.get("usage", {}))))
    insert(db, "answer", answers)


def load_checks(db, work):
    """Loads the outcomes that extract.py and review.py wrote in the run's facts folders."""
    stated, verdicts = {}, {}
    for path in outcome_files(work):
        with open(path, encoding="utf-8") as f:
            for o in json.load(f):
                fact = o["fact"] or dict.fromkeys(facts.IDENTITY)
                if "stated" in o:
                    a = o["stated"]
                    stated[o["prompt"], o["item"]] = dict(
                        prompt_sha=o["prompt"], item=o["item"], doc_sha=o["doc_sha"], plan_id=text(a, "plan_id"),
                        benefit=text(a, "benefit"), answer=json.dumps(a, ensure_ascii=False), problem=o["problem"],
                        fact_id=fact["fact_id"], source=fact["source"], page=fact["page"], skipped=o.get("skipped"))
                else:
                    verdicts[o["prompt"], o["item"]] = dict(
                        step="reviewer" if "earlier" in o else "verifier", prompt_sha=o["prompt"], item=o["item"],
                        decoy=int(o.get("decoy", False)), shown=json.dumps(o["shown"], ensure_ascii=False) if "shown" in o else None,
                        **fact, ok=None if o["ok"] is None else int(o["ok"] is True), reason=str(o["reason"]),
                        earlier=int(o.get("earlier", False)))
    insert(db, "stated", stated.values())
    insert(db, "verdict", verdicts.values())


def text(answer, field):
    value = answer.get(field) if isinstance(answer, dict) else None
    return value if isinstance(value, str) else None


def load_rules(db, data):
    organization = {p["plan_id"]: p["organization"] for p in read(data / "generated/plans.csv")}
    found = present.plan_facts(data)
    held = present.held(data, steps.versions(data, {"present": present.VERSIONS})["present"])
    for r in layers.generated(data)["main"]:
        plan_id = r["plan_id"]
        for col in present.COLUMNS:
            got, aside = present.explain(organization[plan_id], found[plan_id], col)
            insert(db, "rule_line", (dict(plan_id=plan_id, col=col, line=n, value=value, presented=int(present.presents(cited)),
                                          held=held.get((col, plan_id))) for n, (value, cited) in enumerate(got, 1)))
            used = {(n, facts.identity(f)) for n, (_, cited) in enumerate(got, 1) for f in cited}
            insert(db, "rule_fact", [dict(plan_id=plan_id, col=col, line=n, **dict(zip(facts.IDENTITY, identity)), reasons=None)
                                     for n, identity in sorted(used)]
                   + [dict(plan_id=plan_id, col=col, line=None, **dict(zip(facts.IDENTITY, identity)),
                           reasons=json.dumps(reasons)) for identity, reasons in sorted(aside.items())])


def rule(db, plan_id, col, code):
    """Record 6: the rule's lines and the facts it used and set aside."""
    lines = rows(db, "SELECT line, value, presented, held FROM rule_line WHERE plan_id = ? AND col = ? ORDER BY line",
                 plan_id, col)
    considered = rows(db, f"""SELECT r.line, r.reasons, {FACT_COLUMNS}, f.origin, f.reviewed
                              FROM rule_fact r JOIN fact f USING (fact_id, source, doc_sha, page)
                              WHERE r.plan_id = ? AND r.col = ? ORDER BY r.line, f.fact_id""", plan_id, col)
    function = present.COLUMNS[col].__qualname__.split(".")[0]
    return considered, record(True, code=dict(file="pipeline/present.py", function=function, url=code + "pipeline/present.py"),
                              held=lines[0]["held"], lines=[dict(
                                  line=n["line"], value=n["value"], presented=bool(n["presented"]),
                                  facts=[fact_of(f) for f in considered if f["line"] == n["line"]]) for n in lines],
                              set_aside=[dict(fact_of(f), reasons=json.loads(f["reasons"])) for f in considered
                                         if f["line"] is None])


def checks(db, plan_id, col, considered):
    """The prompts behind record 5, and record 5: each check of the document facts the rule considered, and of the
    answers that state a fact for the plan and the column's benefits."""
    identities = [facts.identity(f) for f in considered if f["origin"] == "document"]
    found = [s for s in rows(db, "SELECT * FROM stated WHERE plan_id = ? ORDER BY rowid", plan_id)
             if linked(db, s) and present.related(s, present.LEAVES[col])]
    for identity in identities:
        found += rows(db, "SELECT * FROM stated WHERE fact_id = ? AND source = ? AND doc_sha = ? AND page = ? ORDER BY rowid",
                      *identity)
    out, by_fact, prompts = [], {}, []
    for s in {(s["prompt_sha"], s["item"]): s for s in found}.values():
        ref = dict(prompt=s["prompt_sha"], item=s["item"], answer_key=answer_key(db, s["prompt_sha"]), stated=json.loads(s["answer"]))
        prompts.append(s["prompt_sha"])
        if s["problem"] is None:
            identity = tuple(s[c] for c in facts.IDENTITY)
            if identity not in by_fact:
                by_fact[identity] = fact_check(db, identity, prompts)
                out.append(by_fact[identity])
            by_fact[identity]["stated_by"].append(ref)
            by_fact[identity]["skipped"] = by_fact[identity]["skipped"] or s["skipped"]
        else:
            out.append(dict(fact=None, code_check=s["problem"], stated_by=[ref], verifier=[], reviewer={"status": NONE},
                            kept=False, skipped=None))
    out += [dict(fact_check(db, identity, prompts), code_check=NOT_RECORDED) for identity in identities if identity not in by_fact]
    return prompts, record(out, rows=out)


def answers_of(db, prompts):
    """Record 4: the saved answers to the prompts, each with the tasks that sent them."""
    keys = {}
    for prompt in prompts:
        for t in rows(db, "SELECT * FROM task t JOIN answer a ON a.key = t.answer_key WHERE t.prompt_sha = ?", prompt):
            a = keys.setdefault(t["key"], dict(key=t["key"], model=t["model"], effort=t["effort"], batch=bool(t["batch"]),
                                               usage=json.loads(t["usage"]), reply=t["reply"], prompts=[]))
            ref = dict(prompt=prompt, dir=t["dir"], task=t["task"], url=PROMPT_URL.format(prompt))
            if ref not in a["prompts"]:
                a["prompts"].append(ref)
    return record(keys, rows=list(keys.values()))


def model_tasks(db, step, plan_id):
    """Record 8: the step's tasks for the plan, which have one reader task and one task per verifier."""
    found = rows(db, "SELECT dir, task, prompt_sha AS prompt, answer_key FROM task WHERE dir LIKE ? AND task IN (?, ?, ?) "
                     "ORDER BY rowid", f"{step}/%", f"{plan_id}.md", f"{plan_id}.retry.md", f"v-{plan_id}.md")
    for t in found:
        t["url"] = PROMPT_URL.format(t["prompt"])
    return dict(status=TRACED, rows=found) if found else {"status": NOT_RECORDED}


def linked(db, s):
    """Whether the stated item names a plan its document covers and a known benefit."""
    return s["benefit"] in facts.BENEFITS and bool(db.execute(
        "SELECT 1 FROM plan_document p JOIN download d USING (url) WHERE d.sha256 = ? AND p.plan_id = ?",
        (s["doc_sha"], s["plan_id"])).fetchone())


def answer_key(db, prompt):
    found = db.execute("SELECT answer_key FROM task WHERE prompt_sha = ?", (prompt,)).fetchone()
    return found and found[0]


def fact_check(db, identity, prompts):
    """A stated fact's checks after the code checks passed it. Adds the prompts of its verdicts to prompts."""
    named = dict(zip(facts.IDENTITY, identity))
    verdicts = rows(db, """SELECT step, prompt_sha, item, ok, reason, earlier FROM verdict
                           WHERE fact_id = ? AND source = ? AND doc_sha = ? AND page = ? ORDER BY step, prompt_sha, item""",
                    *identity)
    prompts += [v["prompt_sha"] for v in verdicts]
    verifier = [dict(prompt=v["prompt_sha"], item=v["item"], answer_key=answer_key(db, v["prompt_sha"]), ok=verdict_ok(v),
                     reason=v["reason"], decoys=[dict(item=d["item"], shown=json.loads(d["shown"]), ok=verdict_ok(d),
                                                      reason=d["reason"]) for d in rows(
                         db, "SELECT item, shown, ok, reason FROM verdict WHERE prompt_sha = ? AND decoy = 1 ORDER BY item",
                         v["prompt_sha"])]) for v in verdicts if v["step"] == "verifier"]
    reviews = [v for v in verdicts if v["step"] == "reviewer"]
    if reviews:
        v = reviews[0]
        reviewer = dict(status=TRACED, prompt=v["prompt_sha"], answer_key=answer_key(db, v["prompt_sha"]), ok=verdict_ok(v),
                        reason=v["reason"], earlier=bool(v["earlier"]))
    elif db.execute("SELECT 1 FROM fact WHERE fact_id = ? AND source = ? AND doc_sha = ? AND page = ? AND reviewed = 1",
                    identity).fetchone():
        reviewer = {"status": NOT_RECORDED, "note": TRUSTED_WITHOUT_REVIEW}
    else:
        reviewer = {"status": NONE}
    kept = db.execute("SELECT 1 FROM fact WHERE fact_id = ? AND source = ? AND doc_sha = ? AND page = ? AND origin = 'document'",
                      identity).fetchone()
    return dict(fact=named, code_check="passed", stated_by=[], verifier=verifier, reviewer=reviewer, kept=bool(kept), skipped=None)


def verdict_ok(v):
    return None if v["ok"] is None else bool(v["ok"])


def unlinked(db, sha256):
    """The stated items in the document's tasks that name no plan it covers, or no known benefit."""
    found = [s for s in rows(db, "SELECT prompt_sha, item, answer, problem, plan_id, benefit, doc_sha FROM stated "
                                 "WHERE doc_sha = ? ORDER BY rowid", sha256) if not linked(db, s)]
    return record(found, rows=[dict(prompt=s["prompt_sha"], item=s["item"], answer_key=answer_key(db, s["prompt_sha"]),
                                    stated=json.loads(s["answer"]), problem=s["problem"]) for s in found])


def fact_of(row):
    return {k: v for k, v in row.items() if k not in ("line", "reasons")} | {"reviewed": bool(row["reviewed"])}


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
    build_row = rows(db, "SELECT sha, year, steps, replayed, checked FROM build")[0]
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
        d["unlinked_answers"] = unlinked(db, d["sha256"]) if build_row["checked"] else {"status": NOT_RECORDED}
    landscape = rows(db, "SELECT plan_field, field, value FROM landscape_read WHERE plan_id = ? ORDER BY position", plan_id)
    if sheet == "main":
        cms = rows(db, "SELECT file, field, value, title, meaning FROM cms_read WHERE plan_id = ? AND col = ? ORDER BY position",
                   plan_id, col)
        for r in cms:
            if r["file"] == "plans.csv":
                r["landscape"] = [dict(field=n["field"], value=n["value"]) for n in landscape if n["plan_field"] == r["field"]]
        cms_fields = record(cms, rows=cms)
    else:
        # cms_sources.csv covers some DVHA columns.
        cms = rows(db, "SELECT file, field, title, value, meaning FROM cms_source WHERE plan_id = ? AND col = ?", plan_id, col)
        cms_fields = record(cms, rows=cms) if cms else {"status": NOT_YET}
    landscape_row = list({(n["field"], n["value"]): dict(field=n["field"], value=n["value"]) for n in landscape}.values())
    file, function = DRAFT_CODE[sheet]
    has_rule = sheet == "main" and col in present.COLUMNS
    considered, rule_record = rule(db, plan_id, col, code) if has_rule else ([], {"status": NONE})
    added = list({json.dumps(f): f for f in map(fact_of, considered) if f["origin"] == "added"}.values())
    model = [dict(r, answers=model_tasks(db, r["step"], plan_id) if r["step"] in MODEL_STEPS and build_row["replayed"]
                  else {"status": NOT_RECORDED}) for r in cited if r.get("step") in MODEL_STEPS + ("xref",)]
    if not has_rule:
        prompts, fact_checks = [], {"status": NONE}
    elif build_row["checked"]:
        prompts, fact_checks = checks(db, plan_id, col, considered)
    else:
        prompts, fact_checks = [], {"status": NOT_RECORDED}
    prompts += [t["prompt"] for r in model for t in r["answers"].get("rows", [])]
    if not build_row["replayed"]:
        answers = {"status": NOT_RECORDED if has_rule or any(r["step"] in MODEL_STEPS for r in model) else NONE}
    else:
        answers = answers_of(db, prompts)
        if answers["status"] == NONE and fact_checks["status"] == NOT_RECORDED:
            answers = {"status": NOT_RECORDED}
    return {
        "cell": dict(year=build_row["year"], sheet=sheet, plan_id=plan_id, col=col, label=fields.labels(sheet)[col],
                     value=values[-1]["value"]),
        "plan": record(True, row=rows(db, "SELECT * FROM plan WHERE plan_id = ?", plan_id)[0],
                       landscape_row=record(landscape_row, fields=landscape_row)),
        "documents": record(documents, documents=documents),
        "draft": record(True, value=found[0]["value"], code=dict(file=file, function=function, url=code + file),
                        cms_fields=cms_fields),
        "answers": answers,
        "fact_checks": fact_checks,
        "rule": rule_record,
        "added_facts": record(added, rows=added),
        "notes": record(n := rows(db, "SELECT kind, comment, url, pdf_page, quote FROM comment WHERE sheet = ? AND plan_id = ? "
                                      "AND col = ?", sheet, plan_id, col), rows=n),
        "struck_quotes": record(s := rows(db, "SELECT quote, note FROM struck_quote WHERE sheet = ? AND plan_id = ? AND col = ?",
                                          sheet, plan_id, col), rows=s),
        "model_citations": record(model, rows=model),
        "layers": record(True, draft=found[0]["value"], applied=[
            dict(layer=v["layer"], value=v["value"], rows=[r for r in cited if r["layer"] == v["layer"]]) for v in values],
            live=dict(value=values[-1]["value"], set_by=setters[0] if setters else None,
                      citations=[r for r in cited if not r["hidden"]]),
            hidden=[r for r in cited if r["hidden"]]),
        "build": record(True, sha=build_row["sha"], steps=json.loads(build_row["steps"]), code=code),
    }


def check(db):
    """Fails if any main cell has a record left not traced yet."""
    left = [f"{plan_id} {col}: {path}" for plan_id, col in db.execute(
        "SELECT plan_id, col FROM draft_cell WHERE sheet = 'main' ORDER BY plan_id, col")
            for path in not_yet(cell(db, "main", plan_id, col))]
    if left:
        raise SystemExit("These records are not traced yet:\n" + "\n".join(left))


def not_yet(records, path=""):
    """The paths of the records whose status is not traced yet."""
    if isinstance(records, list):
        return [p for r in records for p in not_yet(r, path)]
    if not isinstance(records, dict):
        return []
    here = [path.strip("/")] if records.get("status") == NOT_YET else []
    return here + [p for k, v in records.items() for p in not_yet(v, f"{path}/{k}")]


def page(work, sha256, n):
    return eoc.load_pages(blobs.text_path(work, "layout", sha256))[int(n)]


def main(command=None, *args):
    if command == "build" and len(args) in (3, 4):
        build(int(args[0]), *args[1:])
    elif command == "cell" and len(args) == 4:
        db = sqlite3.connect(f"file:{args[0]}?mode=ro", uri=True)
        print(json.dumps(cell(db, *args[1:]), indent=1, ensure_ascii=False))
    elif command == "check" and len(args) == 1:
        check(sqlite3.connect(f"file:{args[0]}?mode=ro", uri=True))
    elif command == "page" and len(args) == 3:
        print(page(*args))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(*sys.argv[1:])
