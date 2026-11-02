"""Extracts benefit facts from plan documents: readers state facts, code checks them, verifiers judge them among decoys.

Needs the texts.py <work> directory. One reader task covers one document and one benefit group.

  extract.py read   <work> <dir> <group>             reader task files <dir>/<doc>.md
  extract.py facts  <work> <dir> <group> <out.json>  facts from answers that pass the code checks
  extract.py verify <work> <facts.json> <vdir>       verifier task files <vdir>/v-<doc>.md, with decoys
  extract.py accept <vdir> <facts.csv>               the facts every verdict accepted; fails if one accepted a decoy

`ask.py` answers each task file <name>.md in <name>.json.
The first facts run writes a retry task, <dir>/<doc>.retry.md, for each document with failed answers.
Answer those, then run facts again.
"""
import collections, csv, glob, json, os, random, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import blanks, facts, years
from eoc import DATA, Doc
from fields import CARRIERS
from filled import numbers

ANSWER_FIELDS = set(facts.KEY) | {"amount", "unit", "limit", "page", "quotes", "note"}
FREE_TEXT = ("provider_tier", "condition", "package", "pool", "unit", "limit", "note")
DECOY_FIELDS = ("plan_id", "network", "setting")


def documents(data=DATA):
    """Each checked document once: {id, sha256, kind, plan_ids}."""
    with open(f"{data}/generated/documents_checked.csv") as f:
        rows = [r for r in csv.DictReader(f) if r["sha256"] and r["kind"] in facts.DOCUMENTS]
    by_sha = {}
    for r in rows:
        d = by_sha.setdefault(r["sha256"], {"id": r["sha256"][:16], "sha256": r["sha256"], "kind": r["kind"], "plan_ids": []})
        d["plan_ids"] += [p for p in r["plan_ids"].split(";") if p not in d["plan_ids"]]
    return sorted(by_sha.values(), key=lambda d: d["id"])


def plans(data=DATA):
    with open(f"{data}/generated/plans.csv") as f:
        return {r["plan_id"]: r for r in csv.DictReader(f)}


def relevant(pages, group):
    return {p: t for p, t in pages.items() if any(re.search(rx, t, re.I) for rx in facts.FIND[group])}


def page_text(pages):
    return "\n\n".join(f"=====PAGE {p}=====\n{pages[p].rstrip()}" for p in sorted(pages))


def fill(template, doc, plan_rows, **values):
    names = "\n".join(f"- {p}: {plan_rows.get(p, {}).get('plan_name', '')}" for p in doc["plan_ids"])
    orgs = sorted({plan_rows[p]["organization"] for p in doc["plan_ids"] if p in plan_rows} & set(CARRIERS))
    notes = "".join(f"\nSeen in {o} documents: {CARRIERS[o]}" for o in orgs)
    return blanks.fill(template, KIND=doc["kind"], PLANS=names, NOTES=notes,
                       YEAR=str(years.config(DATA)["year"]), **values)


def task(doc, plan_rows, pages, group, failed=()):
    parts = [fill("fact_prompt.md", doc, plan_rows, VOCABULARY=facts.describe(group))]
    if failed:
        parts.append("## Earlier answers that failed a check\n\nFix each or leave it out.\n\n"
                     + "\n".join(f"- {json.dumps(a, ensure_ascii=False)}: {why}" for a, why in failed))
    parts.append("## Pages\n\n" + page_text(relevant(pages, group)))
    return "\n\n".join(parts) + "\n"


def problem(doc, group, a, quote_ok):
    """Why the answer cannot be a fact, or None, and the fact."""
    if not isinstance(a, dict):
        return "not an object", None
    if set(a) - ANSWER_FIELDS or not ANSWER_FIELDS - set(FREE_TEXT) <= set(a):
        return f"fields: {sorted(set(a) ^ ANSWER_FIELDS)}", None
    if type(a["page"]) is not int:
        return "page: give the PDF page number as a number", None
    if not isinstance(a["quotes"], list):
        return "quotes: give a list of quotes", None
    row = {c: str(a.get(c, "")) for c in facts.COLUMNS if c not in ("quotes", "fact_id")}
    row.update(source=doc["kind"], doc_sha=doc["sha256"], quotes=json.dumps(a["quotes"], ensure_ascii=False))
    row["fact_id"] = facts.fact_id(row)
    bad = facts.check(row)
    if bad:
        return "; ".join(bad), None
    if row["plan_id"] not in doc["plan_ids"]:
        return f"plan_id: this document covers {', '.join(doc['plan_ids'])}", None
    if not facts.covers(group, row["benefit"]):
        return f"benefit: {row['benefit']} is not in {group}", None
    failing = [q for q in a["quotes"] if not quote_ok(a["page"], q)]
    if failing:
        return "quote not found exactly once on its page: " + "; ".join(json.dumps(q) for q in failing), None
    missing = numbers(row["amount"]) - sum((numbers(q) for q in a["quotes"]), collections.Counter())
    if missing:
        return "no quote shows " + ", ".join(sorted(missing)), None
    return None, row


def gate(doc, group, answers, quote_ok):
    """The facts whose answers pass the code checks, and [(answer, why)] for the rest."""
    passed, failed = [], []
    for a in answers:
        why, row = problem(doc, group, a, quote_ok)
        if why:
            failed.append((a, why))
        else:
            passed.append((a, row))
    clash = set(facts.conflicts([r for _, r in passed]))
    failed += [(a, "two answers for one fact on one page") for a, r in passed
               if tuple(r[c] for c in facts.IDENTITY) in clash]
    unique = {tuple(r[c] for c in facts.COLUMNS): r for _, r in passed if tuple(r[c] for c in facts.IDENTITY) not in clash}
    return list(unique.values()), failed


def decoys(found, rnd, n=3):
    """Wrong facts that pass the code checks: a fact's amount and quotes under the key of another fact,
    which differs only in plan, network or setting and has another amount."""
    def rest(f, field):
        return tuple(f[k] for k in facts.KEY if k != field)

    moves = [dict(a, **{field: b[field]}, fact_id=b["fact_id"]) for a in found for b in found for field in DECOY_FIELDS
             if a[field] != b[field] and rest(a, field) == rest(b, field) and a["amount"] != b["amount"]]
    return rnd.sample(moves, min(n, len(moves)))


def shown(fact):
    return {k: v for k, v in fact.items() if k in ANSWER_FIELDS and k != "quotes" and v} | {"quotes": json.loads(fact["quotes"])}


def verifier_task(doc, plan_rows, pages, items):
    groups = sorted({c["benefit"].split(".")[0] for c in items})
    parts = [fill("vfact_prompt.md", doc, plan_rows, VOCABULARY="\n\n".join(facts.describe(g) for g in groups))]
    parts += [json.dumps({"id": n, **shown(c)}, ensure_ascii=False) for n, c in enumerate(items)]
    parts.append("## Pages\n\n" + page_text({p: pages[p] for p in {int(c["page"]) for c in items}}))
    return "\n\n".join(parts) + "\n"


def accepted(items, verdicts):
    """Facts every verdict accepted. An item without a verdict is rejected."""
    ok = {v["id"] for v in verdicts} - {v["id"] for v in verdicts if v.get("ok") is not True}
    decoys_ok = sorted(i for i in ok if items[i]["decoy"])
    if decoys_ok:
        raise SystemExit(f"The verifier accepted decoys {decoys_ok}. Use a stronger verifier.")
    return [{k: v for k, v in items[i].items() if k not in ("decoy", "task")} for i in sorted(ok)]


def answers(path):
    """A task's answers, or [] when the model answered with something other than a list."""
    with open(path) as f:
        found = json.load(f)
    return found if isinstance(found, list) else []


def read(work, out_dir, group):
    os.makedirs(out_dir, exist_ok=True)
    plan_rows = plans()
    for doc in documents():
        pages = Doc(work, doc["id"]).pages("layout")
        if relevant(pages, group):
            with open(f"{out_dir}/{doc['id']}.md", "w") as f:
                f.write(task(doc, plan_rows, pages, group))


def extract_facts(work, answers_dir, group, out):
    plan_rows, found, retries = plans(), [], 0
    for doc in documents():
        first = f"{answers_dir}/{doc['id']}.json"
        if not os.path.exists(first):
            continue
        d = Doc(work, doc["id"])
        got, failed = gate(doc, group, answers(first), d.quote_ok)
        retry = f"{answers_dir}/{doc['id']}.retry.json"
        if os.path.exists(retry):
            again, failed = gate(doc, group, answers(retry), d.quote_ok)
            got += again
        elif failed:
            with open(f"{answers_dir}/{doc['id']}.retry.md", "w") as f:
                f.write(task(doc, plan_rows, d.pages("layout"), group, failed))
            retries += 1
        found += got
    with open(out, "w") as f:
        json.dump(found, f, indent=1, ensure_ascii=False)
    print(len(found), "facts;", retries, "retry tasks")


def verify(work, facts_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    with open(facts_path) as f:
        found = json.load(f)
    plan_rows, items = plans(), []
    for doc in documents():
        mine = [f for f in found if f["doc_sha"] == doc["sha256"]]
        if not mine:
            continue
        rnd = random.Random(doc["sha256"])
        mixed = [dict(f, decoy=False) for f in mine] + [dict(f, decoy=True) for f in decoys(mine, rnd)]
        rnd.shuffle(mixed)
        with open(f"{out_dir}/v-{doc['id']}.md", "w") as f:
            f.write(verifier_task(doc, plan_rows, Doc(work, doc["id"]).pages("layout"), mixed))
        items += [dict(c, task=doc["id"]) for c in mixed]
    with open(f"{out_dir}/items.json", "w") as f:
        json.dump(items, f, indent=1, ensure_ascii=False)
    print(sum(not c["decoy"] for c in items), "facts", sum(c["decoy"] for c in items), "decoys")


def accept(verify_dir, out):
    with open(f"{verify_dir}/items.json") as f:
        items = json.load(f)
    verdicts = blanks.verdicts(items, verify_dir)
    acc = accepted(items, verdicts)
    facts.write(out, acc)
    print(len(acc), "of", sum(not c["decoy"] for c in items), "facts accepted;",
          len(blanks.missing_verdicts(items, verdicts)), "items without a verdict")


COMMANDS = {"read": read, "facts": extract_facts, "verify": verify, "accept": accept}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        raise SystemExit(__doc__)
    COMMANDS[sys.argv[1]](*sys.argv[2:])
