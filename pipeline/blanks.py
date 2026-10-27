"""Cites EOC quotes for blank cells: the plan lacks the benefit, covers only the Medicare part, or sells it as an option.

Needs pypdfium2, poppler's pdftotext and `npm ci` here. First run `texts.py <documents>/pdfs <work>`,
where <documents> comes from `web/build.py documents` or the documents.tar release.

  blanks.py bundle  <work> <dir>                     one task file per plan, <dir>/<plan>.md
  blanks.py claims  <work> <dir> <claims.json>        answers whose quotes pass the mechanical checks
  blanks.py verify  <work> <claims.json> <vdir>       verifier task files <vdir>/v-NN.md, with decoys from cells plans fill
  blanks.py accept  <work> <vdir> <accepted.json>     claims the verifier accepted; fails if it accepted a decoy
  blanks.py publish <accepted.json>                   appends the citations to data/<year>/machine/eoc_citations.csv

Give each task file to a small model (a Haiku subagent): "Read <file> and do exactly the task it describes."
It writes its answer where the file says: <dir>/a-<plan>.json or <vdir>/ans-NN.json.
For a second, independent check, run verify and accept again on accepted.json before publishing.
"""
import collections, csv, glob, hashlib, io, json, os, pathlib, random, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "web"))
import fields, layers, years
from eoc import DATA, Doc, eoc, norm
from fields import FIELDS

LINES_BEFORE_HIT, LINES_AFTER_HIT = 4, 8
CLAIMS = {"excluded", "medicare_only", "optional_only"}
MEDICARE_ONLY_KEYS = {"main.S_acupuncture", "main.T_chiropractic"}
EXCLUSION = re.compile(r"not covered|exclu|does(?: not|n[’']t) (?:cover|offer)|(?:are not|aren[’']t) included", re.I)
CONDITION = re.compile(r"\b(if|when|unless)\b", re.I)
EXCLUSION_ROW_ENDS = (" Not covered under any condition", " Not covered under any condition.")


def cells(data=DATA):
    """{sheet.key: {plan_id: cell}} for the fields an EOC can show."""
    import build
    site = build.site_data(pathlib.Path(data))
    out = collections.defaultdict(dict)
    for sheet in ("main", "dvha"):
        for r in site[sheet]["rows"]:
            for k, c in r["cells"].items():
                if f"{sheet}.{k}" in FIELDS:
                    out[f"{sheet}.{k}"][r["plan_id"]] = c
    return out


def uncited_blanks(all_cells):
    out = collections.defaultdict(list)
    for key, by_plan in all_cells.items():
        for plan, c in by_plan.items():
            if not c["value"].strip() and not c["cites"]:
                out[plan].append(key)
    return out


def snippets(pages, regexes):
    """Line windows around each regex hit, merged per page."""
    out = []
    for p, text in sorted(pages.items()):
        lines = text.split("\n")
        spans = []
        for i, line in enumerate(lines):
            if any(re.search(rx, line, re.I) for rx in regexes):
                a, b = max(0, i - LINES_BEFORE_HIT), min(len(lines), i + LINES_AFTER_HIT + 1)
                if spans and a <= spans[-1][1]:
                    spans[-1][1] = max(spans[-1][1], b)
                else:
                    spans.append([a, b])
        out += [(p, "\n".join(l.rstrip() for l in lines[a:b] if l.strip())) for a, b in spans]
    return out


def passages(layout, key, keep=lambda snippet: True):
    parts, page = [], None
    for p, s in snippets(layout, FIELDS[key][1]):
        if not keep(s):
            continue
        if p != page:
            parts.append(f"=====PAGE {p}=====")
            page = p
        parts.append(s + "\n---")
    return "\n".join(parts) or "(No passage mentions it.)"


def notes(plan_id):
    with open(f"{DATA}/generated/plans.csv") as f:
        org = next((r["organization"] for r in csv.DictReader(f) if r["plan_id"] == plan_id), None)
    return f"\nSeen in {org} EOCs: {fields.CARRIERS[org]}" if org in fields.CARRIERS else ""


def fill(template, **values):
    """The template with each {KEY} replaced. A PLAN_ID also fills {NOTES} with what the plan's carrier tends to do."""
    if "PLAN_ID" in values:
        values = {"NOTES": notes(values["PLAN_ID"]), **values}
    with open(f"{HERE}/{template}") as f:
        text = f.read()
    for k, v in values.items():
        text = text.replace("{" + k + "}", v)
    return text


def prompt_version(*templates):
    """Hashes the templates and fields.py, whose meanings and carrier notes the prompts show."""
    h = hashlib.sha256()
    for name in (*templates, "fields.py"):
        with open(f"{HERE}/{name}", "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:12]


def bundle(work, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    names = {r["plan_id"]: r["plan_name"] for r in csv.DictReader(open(f"{DATA}/generated/plans.csv"))}
    for plan, keys in sorted(uncited_blanks(cells()).items()):
        layout = Doc(work, plan).pages("layout")
        head = fill("blank_prompt.md", PLAN_NAME=names[plan], PLAN_ID=plan, YEAR=str(years.config(DATA)["year"]),
                    ANSWER=os.path.abspath(f"{out_dir}/a-{plan}.json"),
                    CHECK=f"python3 -I {HERE}/quote_check.py {os.path.abspath(work)} {plan}")
        body = [f"### {k}\n\n{FIELDS[k][0]}\n\n{passages(layout, k)}" for k in sorted(keys)]
        open(f"{out_dir}/{plan}.md", "w").write("\n\n".join([head] + body) + "\n")


def gate_claims(plan, answers, quote_ok):
    """Claims whose every quote passes quote_ok(page, quote)."""
    out = []
    for r in answers:
        if r.get("result") not in CLAIMS or not r.get("citations"):
            continue
        if r["result"] == "medicare_only" and r["key"] not in MEDICARE_ONLY_KEYS:
            continue
        if all(quote_ok(int(c["page"]), c["quote"]) for c in r["citations"]):
            out.append({"plan": plan, "key": r["key"], "claim": r["result"],
                        "citations": [{"page": int(c["page"]), "quote": c["quote"]} for c in r["citations"]]})
    return out


def claims(work, answers_dir, out):
    found = []
    for f in sorted(glob.glob(f"{answers_dir}/a-*.json")):
        plan = os.path.basename(f)[2:-5]
        found += gate_claims(plan, json.load(open(f)), Doc(work, plan).quote_ok)
    json.dump(found, open(out, "w"), indent=1, ensure_ascii=False)
    print(len(found), "claims")


def decoys(found, filled, doc_of, max_per_key=3, seed=8):
    """Real claims moved onto plans that fill the same cell, in other documents that hold each quote once."""
    out, seen, per_key = [], set(), collections.Counter()
    for c in random.Random(seed).sample(found, len(found)):
        if per_key[c["key"]] >= max_per_key:
            continue
        for plan in filled.get(c["key"], []):
            doc = doc_of(plan)
            if (doc.id, c["key"]) in seen or doc.id == doc_of(c["plan"]).id:
                continue
            moved = []
            for q in c["citations"]:
                hits = [p for p, t in doc.flow.items() if t.count(norm(q["quote"])) == 1]
                if len(hits) == 1 and doc.quote_ok(hits[0], q["quote"]):
                    moved.append({"page": hits[0], "quote": q["quote"]})
            if moved:
                out.append(dict(c, plan=plan, citations=moved, decoy=True))
                seen.add((doc.id, c["key"]))
                per_key[c["key"]] += 1
                break
    return out


def verifier_items(found, planted, seed=3):
    items = found + planted
    random.Random(seed).shuffle(items)
    return items


def verify(work, claims_path, out_dir, items_per_task=6):
    os.makedirs(out_dir, exist_ok=True)
    found = json.load(open(claims_path))
    filled = {k: [p for p, c in by_plan.items() if c["value"].strip()] for k, by_plan in cells().items()}
    docs = {}
    doc_of = lambda plan: docs.setdefault(plan, Doc(work, plan))
    items = verifier_items(found, decoys(found, filled, doc_of))
    json.dump(items, open(f"{out_dir}/items.json", "w"), indent=1, ensure_ascii=False)
    for b in range(0, len(items), items_per_task):
        n = b // items_per_task
        parts = [fill("vblank_prompt.md", ANSWER=os.path.abspath(f"{out_dir}/ans-{n:02d}.json"))]
        for i in range(b, min(b + items_per_task, len(items))):
            c = items[i]
            shown = {"id": i, "plan": c["plan"], "field": c["key"], "meaning": FIELDS[c["key"]][0],
                     "claim": c["claim"], "citations": c["citations"]}
            parts.append(f"### Item {i}\n\n{json.dumps(shown, ensure_ascii=False)}\n\nPassages:\n\n"
                         f"{passages(doc_of(c['plan']).pages('layout'), c['key'])}")
        open(f"{out_dir}/v-{n:02d}.md", "w").write("\n\n".join(parts) + "\n")
    print(len(found), "claims", len(items) - len(found), "decoys")


def states_exclusion(key, quote):
    names = any(re.search(rx, quote, re.I) for rx in FIELDS[key][1])
    return bool(names and EXCLUSION.search(quote) and not CONDITION.search(quote))


def exclusion_cites(key, cites, quote_ok):
    """The quotes that name the benefit and say it is not covered, completing bare exclusion-table rows."""
    out = []
    for c in cites:
        for q in [c["quote"]] + [c["quote"] + end for end in EXCLUSION_ROW_ENDS]:
            if states_exclusion(key, q) and (q == c["quote"] or quote_ok(c["page"], q)):
                out.append(dict(c, quote=q))
                break
    return out


def missing_verdicts(items, verdicts):
    return sorted(set(range(len(items))) - {v["id"] for v in verdicts})


def accepted(items, verdicts, quote_ok_for):
    """Claims every verdict accepted, with the exclusion stated for `excluded` claims."""
    if missing_verdicts(items, verdicts):
        raise SystemExit(f"No verdict for items {missing_verdicts(items, verdicts)}")
    ok = {v["id"] for v in verdicts} - {v["id"] for v in verdicts if v["ok"] is not True}
    decoys_ok = [i for i in ok if items[i].get("decoy")]
    if decoys_ok:
        raise SystemExit(f"The verifier accepted decoys {decoys_ok}. Use a stronger verifier.")
    out = []
    for i in sorted(ok):
        c = items[i]
        cites = c["citations"]
        if c["claim"] == "excluded":
            cites = exclusion_cites(c["key"], cites, quote_ok_for(c["plan"]))
        if cites:
            out.append(dict(c, citations=cites))
    return out


def accept(work, verify_dir, out):
    items = json.load(open(f"{verify_dir}/items.json"))
    verdicts = [v for f in sorted(glob.glob(f"{verify_dir}/ans-*.json")) for v in json.load(open(f))]
    acc = accepted(items, verdicts, lambda plan: Doc(work, plan).quote_ok)
    json.dump([{k: v for k, v in c.items() if k != "decoy"} for c in acc], open(out, "w"), indent=1, ensure_ascii=False)
    print(len(acc), "of", sum(1 for c in items if not c.get("decoy")), "claims accepted;",
          sum(1 for c in items if c.get("decoy")), "decoys rejected")


def citation_rows(acc, url_of):
    prompt = prompt_version("blank_prompt.md", "vblank_prompt.md")
    return [dict(step="blanks", prompt=prompt, sheet=c["key"].split(".")[0], plan_id=c["plan"], column=c["key"].split(".")[1],
                 line="", value="", url=url_of(c["plan"]), pdf_page=q["page"], quote=q["quote"])
            for c in sorted(acc, key=lambda c: (c["key"], c["plan"])) for q in c["citations"]]


def publish(accepted_path, data=DATA):
    with open(accepted_path) as f:
        acc = json.load(f)
    all_cells = cells(data)
    stale = [(c["plan"], c["key"]) for c in acc if all_cells[c["key"]][c["plan"]]["value"].strip() or all_cells[c["key"]][c["plan"]]["cites"]]
    if stale:
        raise SystemExit(f"No longer uncited blanks: {stale}")
    buf = io.StringIO()
    csv.DictWriter(buf, fieldnames=layers.MACHINE_COLUMNS, lineterminator="\r\n").writerows(
        citation_rows(acc, lambda plan: eoc(plan, data)[1]))
    with open(f"{data}/machine/eoc_citations.csv", "a", newline="") as f:
        f.write(buf.getvalue())


COMMANDS = {"bundle": bundle, "claims": claims, "verify": verify, "accept": accept, "publish": publish}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        raise SystemExit(__doc__)
    COMMANDS[sys.argv[1]](*sys.argv[2:])
