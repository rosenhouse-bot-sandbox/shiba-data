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
import collections, csv, json, os, random, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import blanks, facts, years
from eoc import DATA, Doc
from fields import CARRIERS
from filled import accepted, numbers

ANSWER_FIELDS = set(facts.KEY) | {"amount", "unit", "limit", "page", "quotes", "note"}
OPTIONAL = {"provider_tier", "condition", "package", "pool", "amount", "unit", "limit", "note"}
DECOY_FIELDS = ("plan_id", "network", "setting")
TREES = ("benefit", "setting", "network")


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


def fill(template, doc, plan_rows, data, **values):
    names = "\n".join(f"- {p}: {plan_rows.get(p, {}).get('plan_name', '')}" for p in doc["plan_ids"])
    orgs = sorted({plan_rows[p]["organization"] for p in doc["plan_ids"] if p in plan_rows} & set(CARRIERS))
    notes = "".join(f"\nSeen in {o} documents: {CARRIERS[o]}" for o in orgs)
    return blanks.fill(template, KIND=doc["kind"], PLANS=names, NOTES=notes,
                       YEAR=str(years.config(data)["year"]), **values)


def printable(answer):
    return json.dumps(answer, ensure_ascii=False).encode("utf-8", "backslashreplace").decode()


def task(doc, plan_rows, pages, group, data, failed=()):
    parts = [fill("fact_prompt.md", doc, plan_rows, data, VOCABULARY=facts.describe(group))]
    if failed:
        parts.append("## Earlier answers that failed a check\n\n"
                     "Code keeps the facts that passed. Reply with fixed versions of only these answers, "
                     "and leave out any you cannot fix.\n\n"
                     + "\n".join(f"- {printable(a)}: {why}" for a, why in failed))
    parts.append("## Pages\n\n" + page_text(relevant(pages, group)))
    return "\n\n".join(parts) + "\n"


# These groups' documents state some $0 amounts in words.
ZERO_GROUPS = ("part_b_drugs", "medical_deductible")
NO_COST = re.compile(r"\bno (?:coinsurance|copay|deductible)|does not have a (?:medical )?deductible|no deductible for medical", re.I)


def problem(doc, group, a, pages, quote_ok):
    """Why the answer cannot be a fact, or None, and the fact."""
    if not isinstance(a, dict):
        return "not an object", None
    unknown, missing = set(a) - ANSWER_FIELDS, ANSWER_FIELDS - OPTIONAL - set(a)
    if unknown or missing:
        return "; ".join(f"{what} fields: {', '.join(sorted(f))}" for what, f in
                         [("unknown", unknown), ("missing", missing)] if f), None
    texts = [k for k in a if k not in ("page", "quotes") and not isinstance(a[k], str)]
    if texts:
        return f"give {', '.join(sorted(texts))} as text", None
    if type(a["page"]) is not int:
        return "page: give the PDF page as a whole number", None
    if a["page"] not in pages:
        return f"page: the document has no page {a['page']}", None
    try:
        json.dumps(a, ensure_ascii=False).encode()
    except UnicodeEncodeError:
        return "text: not valid Unicode", None
    row = {c: a.get(c, "") for c in facts.COLUMNS if c not in ("quotes", "fact_id")}
    row.update(page=str(a["page"]), source=doc["kind"], doc_sha=doc["sha256"],
               quotes=json.dumps(a["quotes"], ensure_ascii=False))
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
    if group in ZERO_GROUPS and missing == collections.Counter({"$0": 1}) and any(NO_COST.search(q) for q in a["quotes"]):
        missing = None
    if missing:
        return "no quote shows " + ", ".join(sorted(missing)), None
    return None, row


def gate(doc, group, answers, pages, quote_ok):
    """The facts whose answers pass the code checks, and [(answer, why)] for the rest."""
    passed, failed = [], []
    for a in answers:
        why, row = problem(doc, group, a, pages, quote_ok)
        if why:
            failed.append((a, why))
        else:
            passed.append((a, row))
    clash = set(facts.conflicts([r for _, r in passed]))
    failed += [(a, "two answers for one fact on one page") for a, r in passed
               if tuple(r[c] for c in facts.IDENTITY) in clash]
    unique = {tuple(r[c] for c in facts.COLUMNS): r for _, r in passed if tuple(r[c] for c in facts.IDENTITY) not in clash}
    return list(unique.values()), failed


def overlaps(f, g):
    """Whether the two facts could be about the same thing: their keys match, or one's words cover the other's."""
    return all(f[k] == g[k] or k in TREES and (facts.covers(f[k], g[k]) or facts.covers(g[k], f[k])) for k in facts.KEY)


def decoys(found, rnd, n=3):
    """Wrong facts that pass the code checks: a fact's amount and quotes under the key of another fact,
    which differs only in plan, network or setting and has another amount. No fact that overlaps it has that amount."""
    def rest(f, field):
        return tuple(f[k] for k in facts.KEY if k != field)

    moves = {}
    for a in found:
        for b in found:
            for field in DECOY_FIELDS:
                if rest(a, field) == rest(b, field) and a[field] != b[field]:
                    d = dict(a, **{field: b[field]}, fact_id=b["fact_id"])
                    if not any(overlaps(d, f) and f["amount"] == d["amount"] for f in found):
                        moves[tuple(d[c] for c in facts.COLUMNS)] = d
    return rnd.sample(sorted(moves.values(), key=lambda d: tuple(d[c] for c in facts.COLUMNS)), min(n, len(moves)))


def shown(fact):
    return ({k: v for k, v in fact.items() if k in ANSWER_FIELDS - {"quotes", "note"} and v}
            | {"quotes": json.loads(fact["quotes"])})


def verifier_task(doc, plan_rows, pages, items, data):
    groups = sorted({c["benefit"].split(".")[0] for c in items})
    parts = [fill("vfact_prompt.md", doc, plan_rows, data, VOCABULARY="\n\n".join(facts.describe(g) for g in groups))]
    parts += [json.dumps({"id": n, **shown(c)}, ensure_ascii=False) for n, c in enumerate(items)]
    parts.append("## Pages\n\n" + page_text({p: pages[p] for p in {int(c["page"]) for c in items}}))
    return "\n\n".join(parts) + "\n"


def answers(path):
    """A task's answers. A reply that is not a JSON array is one bad answer."""
    try:
        with open(path) as f:
            found = json.load(f)
    except json.JSONDecodeError:
        return ["(not JSON)"]
    return found if isinstance(found, list) else [found]


def doc_facts(doc, group, first, retry, pages, quote_ok):
    """The document's facts from its first answers and any retry answers, and the failures to retry, if it needs a retry."""
    found, failed = gate(doc, group, first + (retry or []), pages, quote_ok)
    return found, (failed if retry is None else [])


def read(work, out_dir, group, data=DATA, ids=None):
    """Writes a task for each document that mentions the group, or for those of them named in ids."""
    os.makedirs(out_dir, exist_ok=True)
    plan_rows = plans(data)
    for doc in documents(data):
        if ids is not None and doc["id"] not in ids:
            continue
        pages = Doc(work, doc["id"]).pages("layout")
        if relevant(pages, group):
            with open(f"{out_dir}/{doc['id']}.md", "w") as f:
                f.write(task(doc, plan_rows, pages, group, data))


def extract_facts(work, answers_dir, group, out, data=DATA):
    plan_rows, found, retries = plans(data), [], 0
    for doc in documents(data):
        first = f"{answers_dir}/{doc['id']}.json"
        if not os.path.exists(first):
            continue
        d, retry = Doc(work, doc["id"]), f"{answers_dir}/{doc['id']}.retry.json"
        pages = d.pages("layout")
        got, failed = doc_facts(doc, group, answers(first), answers(retry) if os.path.exists(retry) else None,
                                pages, d.quote_ok)
        if failed:
            with open(f"{answers_dir}/{doc['id']}.retry.md", "w") as f:
                f.write(task(doc, plan_rows, pages, group, data, failed))
            retries += 1
        found += got
    with open(out, "w") as f:
        json.dump(found, f, indent=1)
    print(len(found), "facts;", retries, "retry tasks")


def verify(work, facts_path, out_dir, data=DATA):
    os.makedirs(out_dir, exist_ok=True)
    with open(facts_path) as f:
        found = json.load(f)
    plan_rows, items = plans(data), []
    for doc in documents(data):
        mine = [f for f in found if f["doc_sha"] == doc["sha256"]]
        if not mine:
            continue
        rnd = random.Random(doc["sha256"])
        mixed = [dict(f, decoy=False) for f in mine] + [dict(f, decoy=True) for f in decoys(mine, rnd)]
        rnd.shuffle(mixed)
        with open(f"{out_dir}/v-{doc['id']}.md", "w") as f:
            f.write(verifier_task(doc, plan_rows, Doc(work, doc["id"]).pages("layout"), mixed, data))
        items += [dict(c, task=doc["id"]) for c in mixed]
    with open(f"{out_dir}/items.json", "w") as f:
        json.dump(items, f, indent=1)
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
