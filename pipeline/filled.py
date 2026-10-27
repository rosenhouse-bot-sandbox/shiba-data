"""Cites EOC quotes for filled cells: a dot, or a value whose every amount a quote shows.

Needs what blanks.py needs, including the texts.py <work> directory.

  filled.py bundle  <work> <dir> [every]          one task file per plan, <dir>/<plan>.md, for cells no EOC cites (every: all filled cells)
  filled.py claims  <work> <dir> <claims.json>    answers whose quotes pass the mechanical checks
  filled.py verify  <work> <claims.json> <vdir>   one verifier task file per plan, <vdir>/v-<plan>.md, with decoys
  filled.py accept  <vdir> <accepted.json>        claims the verifier accepted; fails if it accepted a decoy
  filled.py publish <accepted.json> [<out.csv>]   appends the citations to data/<year>/eoc_citations.csv, or writes them to out.csv

Give each task file to a small model (a Haiku subagent): "Read <file> and do exactly the task it describes."
It writes its answer where the file says. The first claims run writes a retry task, <dir>/<plan>.retry.md,
for each plan with failed quotes. Run those, then run claims again.
"""
import collections, csv, glob, io, json, os, pathlib, random, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "web"))
import blanks, build, years
from blanks import fill
from eoc import DATA, Doc, eoc
from fields import FIELDS

DOTS = ("●", "◐")
AMOUNT = re.compile(r"\$(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\d+(?:\.\d+)?%")
COLUMNS = ["sheet", "plan_id", "column", "value", "url", "pdf_page", "quote"]


def money(s):
    """Dollar amounts and percentages, with 0% read as $0."""
    amounts = {re.sub(r"\.0+$", "", a.replace(",", "")) for a in AMOUNT.findall(s)}
    return {"$0" if a == "0%" else a for a in amounts}


def targets(site, every=False):
    """{plan: {key: value}} for checkable cells that no EOC or rider cites, or for all of them."""
    out = collections.defaultdict(dict)
    for sheet in ("main", "dvha"):
        for r in site[sheet]["rows"]:
            for k, c in r["cells"].items():
                key = f"{sheet}.{k}"
                checkable = c["value"].strip() in DOTS or money(c["value"])
                eoc_cited = any(site["docs"][x["doc"]]["kind"] != "SB" for x in c["cites"])
                if key in FIELDS and checkable and (every or not eoc_cited):
                    out[r["plan_id"]][key] = c["value"]
    return dict(out)


def passages(layout, key, value):
    amounts = money(value)
    return blanks.passages(layout, key, lambda s: not amounts or bool(money(s) & amounts))


def names_benefit(key, quote):
    return any(re.search(rx, quote, re.I) for rx in FIELDS[key][1])


def problem(key, value, cites, quote_ok):
    """Why the quotes cannot cite the value, or None."""
    if not cites:
        return "no quotes"
    bad = [c for c in cites if not quote_ok(c["page"], c["quote"])]
    if bad:
        return "not once on its page as running text or down one column: " + "; ".join(f'page {c["page"]} "{c["quote"]}"' for c in bad)
    missing = money(value) - set().union(*(money(c["quote"]) for c in cites))
    if missing:
        return "no quote shows " + ", ".join(sorted(missing))
    if value.strip() in DOTS and not any(names_benefit(key, c["quote"]) for c in cites):
        return "no quote names the benefit"
    return None


def gate(plan, values, answers, quote_ok):
    """Claims from `cite` answers whose quotes pass, and {key: (citations, problem)} for the rest."""
    claims, failed = [], {}
    for r in answers:
        key = r.get("key")
        if r.get("result") != "cite" or key not in values:
            continue
        cites = [{"page": int(c["page"]), "quote": c["quote"]} for c in r.get("citations") or []]
        why = problem(key, values[key], cites, quote_ok)
        if why:
            failed[key] = (cites, why)
        else:
            claims.append({"plan": plan, "key": key, "value": values[key], "citations": cites})
    return claims, failed


def load(path):
    with open(path) as f:
        return json.load(f)


def answers(answers_dir, plan):
    """The plan's answers, with retry answers in place of first answers."""
    retry_path = f"{answers_dir}/r-{plan}.json"
    retry = {r["key"]: r for r in load(retry_path)} if os.path.exists(retry_path) else {}
    return [retry.get(r.get("key"), r) for r in load(f"{answers_dir}/a-{plan}.json")]


def section(key, value, layout, earlier=None):
    parts = [f"### {key}", f"Meaning: {FIELDS[key][0]}", f"Value: `{value}`"]
    if earlier:
        cites, why = earlier
        parts.append(f"Earlier quotes: {json.dumps(cites, ensure_ascii=False)}. They failed the check: {why}.")
    return "\n\n".join(parts + [passages(layout, key, value)])


def task(plan, cells, layout, answer, failed=None):
    names = {r["plan_id"]: r["plan_name"] for r in csv.DictReader(open(f"{DATA}/main_chart.csv"))}
    head = fill("filled_prompt.md", PLAN_NAME=names[plan], PLAN_ID=plan, YEAR=str(years.config(DATA)["year"]),
                ANSWER=os.path.abspath(answer))
    body = [section(k, v, layout, (failed or {}).get(k)) for k, v in sorted(cells.items())]
    return "\n\n".join([head] + body) + "\n"


def bundle(work, out_dir, every=""):
    os.makedirs(out_dir, exist_ok=True)
    for plan, cells in sorted(targets(build.site_data(DATA), every == "every").items()):
        layout = Doc(work, plan).pages("layout")
        open(f"{out_dir}/{plan}.md", "w").write(task(plan, cells, layout, f"{out_dir}/a-{plan}.json"))


def claims(work, answers_dir, out):
    values = targets(build.site_data(DATA), every=True)
    found, retries = [], 0
    for f in sorted(glob.glob(f"{answers_dir}/a-*.json")):
        plan = os.path.basename(f)[2:-5]
        doc = Doc(work, plan)
        got, failed = gate(plan, values.get(plan, {}), answers(answers_dir, plan), doc.quote_ok)
        found += got
        if failed and not os.path.exists(f"{answers_dir}/r-{plan}.json"):
            cells = {k: values[plan][k] for k in failed}
            open(f"{answers_dir}/{plan}.retry.md", "w").write(
                task(plan, cells, doc.pages("layout"), f"{answers_dir}/r-{plan}.json", failed))
            retries += 1
    json.dump(found, open(out, "w"), indent=1, ensure_ascii=False)
    print(len(found), "claims;", retries, "retry tasks")


def bump(value):
    """The value with its first amount raised by 10."""
    m = re.search(r"\$([\d,]+)|(\d+)%", value)
    if not m:
        return None
    raised = f"${int(m[1].replace(',', '')) + 10:,}" if m[1] else f"{int(m[2]) + 10}%"
    return value[:m.start()] + raised + value[m.end():]


def decoys(claims, rnd):
    """Wrong claims for the verifier: two values with an amount raised, and one cell with another cell's quotes."""
    bumpable = [c for c in claims if bump(c["value"])]
    out = [dict(c, value=bump(c["value"])) for c in rnd.sample(bumpable, min(2, len(bumpable)))]
    amounts = [c for c in claims if c["key"].startswith("main.") and money(c["value"])]
    pairs = [(a, b) for a in amounts for b in amounts
             if a is not b and not {q["quote"] for q in a["citations"]} & {q["quote"] for q in b["citations"]}]
    if pairs:
        a, b = rnd.choice(pairs)
        out.append(dict(a, citations=b["citations"]))
    return out


def verify(work, claims_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    by_plan = collections.defaultdict(list)
    for c in json.load(open(claims_path)):
        by_plan[c["plan"]].append(c)
    names = {r["plan_id"]: r["plan_name"] for r in csv.DictReader(open(f"{DATA}/main_chart.csv"))}
    items = []
    for plan, found in sorted(by_plan.items()):
        rnd = random.Random(plan)
        mine = [dict(c, decoy=False) for c in found] + [dict(c, decoy=True) for c in decoys(found, rnd)]
        rnd.shuffle(mine)
        layout = Doc(work, plan).pages("layout")
        parts = [fill("vfilled_prompt.md", PLAN_NAME=names[plan], PLAN_ID=plan, YEAR=str(years.config(DATA)["year"]),
                      ANSWER=os.path.abspath(f"{out_dir}/ans-{plan}.json"))]
        for c in mine:
            shown = {"id": len(items), "field": c["key"], "meaning": FIELDS[c["key"]][0], "value": c["value"],
                     "citations": c["citations"]}
            parts.append(json.dumps(shown, ensure_ascii=False))
            items.append(c)
        parts.append("## EOC pages")
        parts += [f"=====PAGE {p}=====\n{layout[p].rstrip()}" for p in sorted({q["page"] for c in mine for q in c["citations"]})]
        open(f"{out_dir}/v-{plan}.md", "w").write("\n\n".join(parts) + "\n")
    json.dump(items, open(f"{out_dir}/items.json", "w"), indent=1, ensure_ascii=False)
    print(sum(not c["decoy"] for c in items), "claims", sum(c["decoy"] for c in items), "decoys")


def accepted(items, verdicts):
    """Claims every verdict accepted."""
    missing = blanks.missing_verdicts(items, verdicts)
    if missing:
        raise SystemExit(f"No verdict for items {missing}")
    ok = {v["id"] for v in verdicts} - {v["id"] for v in verdicts if v["ok"] is not True}
    decoys_ok = sorted(i for i in ok if items[i]["decoy"])
    if decoys_ok:
        raise SystemExit(f"The verifier accepted decoys {decoys_ok}. Use a stronger verifier.")
    return [{k: v for k, v in items[i].items() if k != "decoy"} for i in sorted(ok)]


def accept(verify_dir, out):
    items = json.load(open(f"{verify_dir}/items.json"))
    verdicts = [v for f in sorted(glob.glob(f"{verify_dir}/ans-*.json")) for v in json.load(open(f))]
    acc = accepted(items, verdicts)
    json.dump(acc, open(out, "w"), indent=1, ensure_ascii=False)
    print(len(acc), "of", sum(not c["decoy"] for c in items), "claims accepted;", sum(c["decoy"] for c in items), "decoys rejected")


def lead(key, value, cites):
    """The quotes that show the value, best first: for a dot, those that name the benefit; else those with more amounts."""
    if value.strip() in DOTS:
        return sorted(cites, key=lambda c: not names_benefit(key, c["quote"]))

    def shown(c):
        both = money(c["quote"]) & money(value)
        return len(both - {"$0"}), len(both)  # $0 is on most pages, so other amounts show the cell better

    return [c for c in sorted(cites, key=shown, reverse=True) if any(shown(c))]


def citation_rows(acc, url_of):
    rows = []
    for c in sorted(acc, key=lambda c: (c["key"], c["plan"])):
        sheet, column = c["key"].split(".")
        rows += [[sheet, c["plan"], column, c["value"], url_of(c["plan"]), q["page"], q["quote"]]
                 for q in lead(c["key"], c["value"], c["citations"])]
    return rows


def publish(accepted_path, out=None, data=DATA):
    with open(accepted_path) as f:
        acc = json.load(f)
    current = targets(build.site_data(pathlib.Path(data)), every=out is not None)
    stale = [(c["plan"], c["key"]) for c in acc if current.get(c["plan"], {}).get(c["key"]) != c["value"]]
    if stale:
        raise SystemExit(f"Changed, or already cited by an EOC: {stale}")
    rows = citation_rows(acc, lambda plan: eoc(plan, data)[1])
    with open(out or f"{data}/eoc_citations.csv", "w" if out else "a", newline="") as f:
        csv.writer(f, lineterminator="\r\n").writerows(([COLUMNS] if out else []) + rows)


COMMANDS = {"bundle": bundle, "claims": claims, "verify": verify, "accept": accept, "publish": publish}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        raise SystemExit(__doc__)
    COMMANDS[sys.argv[1]](*sys.argv[2:])
