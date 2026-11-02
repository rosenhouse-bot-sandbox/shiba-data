"""Measures fact readers and verifiers at each model and effort on one benefit group.

Usage: python3 -I pipeline/evaluate.py <year> <work> <dir> <group> <all|sample> [api]

<dir> holds the task files. data/<year>/evaluations/<group> holds the saved answers and the report.

Every reader extracts facts from the same documents: all of them, or one per carrier and kind.
The reviewer judges every reader's facts, mixed with decoys, and each verifier judges the same items.
A rerun asks only new tasks. Without `api`, the run stops at the first step with unanswered tasks.
"""
import collections, csv, glob, json, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ask, blanks, expected, extract, facts, years
from eoc import Doc
from filled import numbers

MODELS = ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5")
EFFORTS = ("low", "medium", "high")
GRID = [(m, e) for m in MODELS for e in EFFORTS]
REVIEWER = ("claude-opus-5-5", "high")
# Dollars per million input and output tokens. Cache tokens are priced as input.
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00), "claude-opus-5-5": (4.00, 20.00)}
COLUMN = {"imaging": ("main", "L_xray_imaging")}
AGREE, DISAGREE = "accepts the reviewer's accepts", "accepts the reviewer's rejects"


def name(role):
    return "-".join(role)


def sample(docs, plan_rows):
    """The first document of each carrier and kind."""
    first = {}
    for d in docs:
        org = plan_rows.get(d["plan_ids"][0], {}).get("organization", "")
        first.setdefault((org, d["kind"]), d)
    return sorted(first.values(), key=lambda d: d["id"])


def cost(model, usage):
    price_in, price_out = PRICES[model]
    tokens_in = sum(usage.get(k, 0) for k in ask.USAGE_FIELDS if k != "output_tokens")
    return (tokens_in * price_in + usage.get("output_tokens", 0) * price_out) / 1e6


def spent(tasks, role, saved):
    """Dollars the saved answers to these tasks cost."""
    total = 0.0
    for t in tasks:
        with open(t) as f:
            path = os.path.join(saved, ask.key(role[0], f.read(), role[1]) + ".json")
        with open(path) as f:
            total += cost(role[0], json.load(f).get("usage", {}))
    return total


class Unanswered(Exception):
    pass


def answer(tasks, role, saved, asker):
    left = ask.answer(tasks, role[0], saved, asker, role[1])
    if left:
        raise Unanswered(f"{len(left)} tasks for {name(role)} have no answer, such as {left[0]}")


def read(work, data, root, group, role, docs, saved, asker):
    """The reader's facts and the dollars its answers cost."""
    d = f"{root}/read/{name(role)}"
    extract.read(work, d, group, data)
    keep = {f"{doc['id']}.md" for doc in docs}
    for t in glob.glob(f"{d}/*.md"):
        if os.path.basename(t) not in keep:
            os.remove(t)
    answer(sorted(glob.glob(f"{d}/*.md")), role, saved, asker)
    quiet(extract.extract_facts, work, d, group, f"{d}/facts.json", data)
    answer(sorted(glob.glob(f"{d}/*.retry.md")), role, saved, asker)
    quiet(extract.extract_facts, work, d, group, f"{d}/facts.json", data)
    with open(f"{d}/facts.json") as f:
        return json.load(f), spent(sorted(glob.glob(f"{d}/*.md")), role, saved)


def quiet(f, *args):
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        f(*args)


def row(fact):
    return tuple(fact[c] for c in facts.COLUMNS)


def claim(fact):
    return fact["doc_sha"], fact["fact_id"], fact["amount"]


def pool(by_reader):
    """Every reader's facts once each."""
    return sorted({row(f): f for found in by_reader.values() for f in found}.values(), key=row)


def judged(items, verdicts):
    """{item index: accepted}. An item without a verdict is rejected."""
    ok = collections.defaultdict(lambda: True)
    for v in verdicts:
        ok[v["id"]] &= v.get("ok") is True
    return {i: i in ok and ok[i] for i in range(len(items))}


def accepted_claims(items, verdict):
    return {claim(items[i]) for i, ok in verdict.items() if ok and not items[i]["decoy"]}


def score_reader(found, truth):
    claims = {claim(f) for f in found}
    good = claims & truth
    return {"facts": len(claims), "accepted": len(good), "precision": ratio(len(good), len(claims)),
            "recall": ratio(len(good), len(truth))}


def score_verifier(items, verdict, reviewer):
    real = [i for i, c in enumerate(items) if not c["decoy"]]
    decoys = [i for i, c in enumerate(items) if c["decoy"]]
    good = [i for i in real if reviewer[i]]
    bad = [i for i in real if not reviewer[i]]
    return {"decoys accepted": sum(verdict[i] for i in decoys), "decoys": len(decoys),
            AGREE: ratio(sum(verdict[i] for i in good), len(good)), DISAGREE: ratio(sum(verdict[i] for i in bad), len(bad))}


def score_expected(found, truth, wanted, docs, plan_rows):
    """The share of expected cell lines whose numbers all appear in the plan's accepted facts,
    and the share of expected EOC pages with an accepted fact."""
    good = [f for f in found if claim(f) in truth]
    amounts = collections.defaultdict(collections.Counter)
    pages = {(f["plan_id"], f["source"], int(f["page"])) for f in good}
    for f in good:
        amounts[f["plan_id"]] |= numbers(f["amount"])
    covered = {p for d in docs for p in d["plan_ids"]}
    lines = [w for w in wanted if w["plan_id"] in covered]
    shown = sum(not numbers(w["value"]) - amounts[w["plan_id"]] for w in lines)
    eoc = [(w["plan_id"], p) for w in lines for p in w["eoc_pages"]
           if any(d["kind"] == "EOC" and w["plan_id"] in d["plan_ids"] for d in docs)]
    return {"expected lines shown": ratio(shown, len(lines)), "expected lines": len(lines),
            "expected EOC pages cited": ratio(sum((p, "EOC", n) in pages for p, n in eoc), len(eoc))}


def ratio(a, b):
    return round(a / b, 3) if b else None


def cheapest(scores, ok):
    fits = [s for s in scores if ok(s)]
    return min(fits, key=lambda s: s["dollars"])["role"] if fits else None


def report(readers, verifiers, reviewer):
    best = next(s for s in readers if s["role"] == name(REVIEWER))
    reader = cheapest(readers, lambda s: (s["precision"] or 0) >= (best["precision"] or 0))
    verifier = cheapest(verifiers, lambda s: s["decoys accepted"] == 0 and not s[DISAGREE])
    lines = [f"Reviewer {name(REVIEWER)}: {reviewer['decoys accepted']} of {reviewer['decoys']} decoys accepted.", "",
             "| Reader | Facts | Accepted | Precision | Recall | Expected lines shown | Expected EOC pages cited | $ |",
             "|---|---|---|---|---|---|---|---|"]
    lines += [f"| {s['role']} | {s['facts']} | {s['accepted']} | {s['precision']} | {s['recall']} | "
              f"{s['expected lines shown']} | {s['expected EOC pages cited']} | {s['dollars']:.2f} |" for s in readers]
    lines += ["", "| Verifier | Decoys accepted | Accepts reviewer's accepts | Accepts reviewer's rejects | $ |",
              "|---|---|---|---|---|"]
    lines += [f"| {s['role']} | {s['decoys accepted']} of {s['decoys']} | {s[AGREE]} | {s[DISAGREE]} | {s['dollars']:.2f} |"
              for s in verifiers]
    lines += ["", f"Cheapest reader as precise as {name(REVIEWER)}: {reader}.",
              f"Cheapest verifier that accepts no decoy and nothing the reviewer rejects: {verifier}."]
    return "\n".join(lines) + "\n", {"reader": reader, "verifier": verifier}


def main(year, work, root, group, which, mode=""):
    data = years.data_dir(int(year))
    asker = ask.api() if mode == "api" else None
    out = data / "evaluations" / group
    saved = out / "answers"
    docs = [d for d in extract.documents(data) if extract.relevant(Doc(work, d["id"]).pages("layout"), group)]
    plan_rows = extract.plans(data)
    docs = docs if which == "all" else sample(docs, plan_rows)
    by_reader, dollars = {}, {}
    for role in GRID:
        by_reader[name(role)], dollars[name(role)] = read(work, data, root, group, role, docs, saved, asker)

    with open(f"{root}/pool.json", "w") as f:
        json.dump(pool(by_reader), f, indent=1)
    check = f"{root}/check"
    quiet(extract.verify, work, f"{root}/pool.json", check, data)
    with open(f"{check}/items.json") as f:
        items = json.load(f)
    verdicts, verifier_dollars = {}, {}
    for role in [REVIEWER] + [r for r in GRID if r != REVIEWER]:
        d = f"{check}/{name(role)}"
        os.makedirs(d, exist_ok=True)
        for t in glob.glob(f"{check}/v-*.md"):
            shutil.copy(t, d)
        tasks = sorted(glob.glob(f"{d}/v-*.md"))
        answer(tasks, role, saved, asker)
        verdicts[name(role)] = judged(items, blanks.verdicts(items, d))
        verifier_dollars[name(role)] = spent(tasks, role, saved)

    reviewer = verdicts[name(REVIEWER)]
    truth = accepted_claims(items, reviewer)
    sheet, column = COLUMN[group]
    wanted = [w for w in expected.load() if (w["sheet"], w["column"]) == (sheet, column)]
    readers = [dict(role=n, dollars=dollars[n], **score_reader(found, truth),
                    **score_expected(found, truth, wanted, docs, plan_rows)) for n, found in by_reader.items()]
    verifiers = [dict(role=n, dollars=verifier_dollars[n], **score_verifier(items, v, reviewer))
                 for n, v in verdicts.items() if n != name(REVIEWER)]
    review = score_verifier(items, reviewer, reviewer)
    text, picks = report(readers, verifiers, review)
    with open(out / f"{which}.json", "w") as f:
        json.dump({"documents": [d["id"] for d in docs], "readers": readers, "verifiers": verifiers,
                   "reviewer": review, "picks": picks}, f, indent=1)
        f.write("\n")
    with open(out / f"{which}.md", "w") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    if len(sys.argv) not in (6, 7) or sys.argv[5] not in ("all", "sample"):
        raise SystemExit(__doc__)
    try:
        main(*sys.argv[1:])
    except Unanswered as e:
        raise SystemExit(str(e))
