"""Cites EOC quotes for filled cells: a dot, or a value whose every amount a quote shows.

Needs what blanks.py needs, including the texts.py <work> directory. `run.py` runs these steps.

  filled.py bundle  <work> <dir> [every]          one task file per plan, <dir>/<plan>.md, for dots and amounts no EOC cites (every: also those an EOC cites)
  filled.py claims  <work> <dir> <claims.json>    answers whose quotes pass the mechanical checks
  filled.py verify  <work> <claims.json> <vdir>   one verifier task file per plan, <vdir>/v-<plan>.md, with decoys
  filled.py accept  <vdir> <accepted.json>        claims the verifier accepted; fails if it accepted a decoy
  filled.py publish <accepted.json> [<out.csv>]   writes the citations to data/<year>/machine/filled.csv, or to out.csv

`ask.py` answers each task file <name>.md in <name>.json.
The first claims run writes a retry task, <dir>/<plan>.retry.md, for each plan with failed quotes.
Answer those, then run claims again.
"""
import collections, csv, glob, json, os, pathlib, random, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "web"))
import blanks, build, layers, years
from blanks import fill
from eoc import DATA, Doc, eoc
from fields import FIELDS

DOTS = ("●", "◐")
NUMBER = re.compile(r"\$?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?")
NOT_ROUTINE = re.compile(blanks.EXCLUSION.pattern + r"|medicare.covered|optional", re.I)
SUPPLEMENTAL = re.compile(r"non.?medicare.covered|not covered by (?:original )?medicare", re.I)


def numbers(s):
    """How often each dollar amount, percentage and other number appears, with 0% read as $0."""
    found = (re.sub(r"\.0+(?=%?$)", "", n.replace(",", "")) for n in NUMBER.findall(s))
    return collections.Counter("$0" if n == "0%" else n for n in found)


def money(s):
    return {n for n in numbers(s) if n.startswith("$") or n.endswith("%")}


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


def site_data(data):
    """The site's data without this step's citations."""
    return build.site_data(data, layers.without(layers.FILLED))


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
        return ("not found exactly once on its page as running text or down one column: "
                + "; ".join(f'page {c["page"]} "{c["quote"]}"' for c in bad))
    wanted = numbers(value)
    missing = wanted - sum((numbers(c["quote"]) for c in cites), collections.Counter())
    if missing:
        return "no quote shows " + ", ".join(f"{n} {wanted[n]} times" if wanted[n] > 1 else n for n in sorted(missing))
    if value.strip() in DOTS and not any(names_benefit(key, c["quote"]) and not NOT_ROUTINE.search(SUPPLEMENTAL.sub("", c["quote"]))
                                         for c in cites):
        return "no quote names the benefit without saying it is excluded, Medicare-covered or optional"
    return None


def citations(answer):
    """The answer's [{page, quote}], or None if one lacks a page number or a quote."""
    try:
        cites = [{"page": int(c["page"]), "quote": c["quote"]} for c in answer.get("citations") or []]
    except (KeyError, TypeError, ValueError):
        return None
    return cites if all(isinstance(c["quote"], str) for c in cites) else None


def gate(plan, values, answers, quote_ok):
    """Claims from `cite` answers whose quotes pass, and {key: (citations, problem)} for the rest. Skips cells answered twice."""
    times = collections.Counter(r.get("key") for r in answers)
    claims, failed = [], {}
    for r in answers:
        key = r.get("key")
        if r.get("result") != "cite" or key not in values or times[key] > 1:
            continue
        cites = citations(r)
        if cites is None:
            failed[key] = (r.get("citations"), "each citation needs one page number and a quote")
            continue
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
    retry_path = f"{answers_dir}/{plan}.retry.json"
    retry = {r["key"]: r for r in load(retry_path)} if os.path.exists(retry_path) else {}
    return [retry.get(r.get("key"), r) for r in load(f"{answers_dir}/{plan}.json")]


def answered(answers_dir):
    """The plans whose first task has an answer."""
    tasks = glob.glob(f"{answers_dir}/*.md")
    return sorted(os.path.basename(t)[:-3] for t in tasks if not t.endswith(".retry.md") and os.path.exists(t[:-3] + ".json"))


def section(key, value, layout, earlier=None):
    parts = [f"### {key}", f"Meaning: {FIELDS[key][0]}", f"Value: `{value}`"]
    if earlier:
        cites, why = earlier
        parts.append(f"Earlier quotes: {json.dumps(cites, ensure_ascii=False)}. They failed the check: {why}.")
    return "\n\n".join(parts + [passages(layout, key, value)])


def task(plan, cells, layout, failed=None):
    names = {r["plan_id"]: r["plan_name"] for r in csv.DictReader(open(f"{DATA}/generated/plans.csv"))}
    head = fill("filled_prompt.md", PLAN_NAME=names[plan], PLAN_ID=plan, YEAR=str(years.config(DATA)["year"]))
    body = [section(k, v, layout, (failed or {}).get(k)) for k, v in sorted(cells.items())]
    return "\n\n".join([head] + body) + "\n"


def bundle(work, out_dir, every=""):
    if every not in ("", "every"):
        raise SystemExit(__doc__)
    os.makedirs(out_dir, exist_ok=True)
    for plan, cells in sorted(targets(site_data(DATA), every == "every").items()):
        layout = Doc.of_plan(work, plan).pages("layout")
        open(f"{out_dir}/{plan}.md", "w").write(task(plan, cells, layout))


def claims(work, answers_dir, out):
    values = targets(site_data(DATA), every=True)
    found, retries = [], 0
    for plan in answered(answers_dir):
        doc = Doc.of_plan(work, plan)
        got, failed = gate(plan, values.get(plan, {}), answers(answers_dir, plan), doc.quote_ok)
        found += got
        if failed and not os.path.exists(f"{answers_dir}/{plan}.retry.json"):
            cells = {k: values[plan][k] for k in failed}
            open(f"{answers_dir}/{plan}.retry.md", "w").write(task(plan, cells, doc.pages("layout"), failed))
            retries += 1
    json.dump(found, open(out, "w"), indent=1, ensure_ascii=False)
    print(len(found), "claims;", retries, "retry tasks")


def decoys(claims, rnd, n=3):
    """Wrong claims that pass the mechanical checks: a cell's value and quotes, which name its benefit,
    moved to another field of its sheet that the quotes do not name."""
    amounts = [c for c in claims if c["value"].strip() not in DOTS]
    moves = [(a["key"], b) for a in amounts for b in amounts
             if a["key"].split(".")[0] == b["key"].split(".")[0]
             and any(names_benefit(b["key"], q["quote"]) for q in b["citations"])
             and not any(names_benefit(a["key"], q["quote"]) for q in b["citations"])]
    return [dict(b, key=key) for key, b in rnd.sample(moves, min(n, len(moves)))]


def verify(work, claims_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    by_plan = collections.defaultdict(list)
    for c in json.load(open(claims_path)):
        by_plan[c["plan"]].append(c)
    names = {r["plan_id"]: r["plan_name"] for r in csv.DictReader(open(f"{DATA}/generated/plans.csv"))}
    items = []
    for plan, found in sorted(by_plan.items()):
        rnd = random.Random(plan)
        mine = [dict(c, decoy=False) for c in found] + [dict(c, decoy=True) for c in decoys(found, rnd)]
        rnd.shuffle(mine)
        layout = Doc.of_plan(work, plan).pages("layout")
        parts = [fill("vfilled_prompt.md", PLAN_NAME=names[plan], PLAN_ID=plan, YEAR=str(years.config(DATA)["year"]))]
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
    """Claims every verdict accepted. An item without a verdict is rejected."""
    ok = {v["id"] for v in verdicts} - {v["id"] for v in verdicts if v["ok"] is not True}
    decoys_ok = sorted(i for i in ok if items[i]["decoy"])
    if decoys_ok:
        raise SystemExit(f"The verifier accepted decoys {decoys_ok}. Use a stronger verifier.")
    return [{k: v for k, v in items[i].items() if k != "decoy"} for i in sorted(ok)]


def accept(verify_dir, out):
    items = json.load(open(f"{verify_dir}/items.json"))
    verdicts = [v for f in sorted(glob.glob(f"{verify_dir}/v-*.json")) for v in json.load(open(f))]
    acc = accepted(items, verdicts)
    json.dump(acc, open(out, "w"), indent=1, ensure_ascii=False)
    print(len(acc), "of", sum(not c["decoy"] for c in items), "claims accepted;", sum(c["decoy"] for c in items), "decoys rejected;",
          len(blanks.missing_verdicts(items, verdicts)), "items without a verdict")


def lead(key, value, cites):
    """The quotes, best first: for a dot, those that name the benefit; else those that show more of the value's amounts."""
    if value.strip() in DOTS:
        return sorted(cites, key=lambda c: not names_benefit(key, c["quote"]))

    def shown(c):
        both = money(c["quote"]) & money(value)
        return len(both - {"$0"}), len(both)  # $0 is on most pages, so other amounts show the cell better

    return sorted(cites, key=shown, reverse=True)


def citation_rows(acc, url_of):
    prompt = blanks.prompt_version("filled_prompt.md", "vfilled_prompt.md")
    rows = []
    for c in sorted(acc, key=lambda c: (c["key"], c["plan"])):
        sheet, column = c["key"].split(".")
        rows += [dict(step="filled", prompt=prompt, sheet=sheet, plan_id=c["plan"], column=column, line="", value=c["value"],
                      url=url_of(c["plan"]), pdf_page=q["page"], quote=q["quote"])
                 for q in lead(c["key"], c["value"], c["citations"])]
    return rows


def publish(accepted_path, out=None, data=DATA):
    with open(accepted_path) as f:
        acc = json.load(f)
    current = targets(site_data(pathlib.Path(data)), every=out is not None)
    stale = [(c["plan"], c["key"]) for c in acc if current.get(c["plan"], {}).get(c["key"]) != c["value"]]
    if stale:
        raise SystemExit(f"Changed, or already cited by an EOC: {stale}")
    with open(out or f"{data}/{layers.FILLED}", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=layers.MACHINE_COLUMNS, lineterminator="\r\n")
        w.writeheader()
        w.writerows(citation_rows(acc, lambda plan: eoc(plan, data)[1]))


COMMANDS = {"bundle": bundle, "claims": claims, "verify": verify, "accept": accept, "publish": publish}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        raise SystemExit(__doc__)
    COMMANDS[sys.argv[1]](*sys.argv[2:])
