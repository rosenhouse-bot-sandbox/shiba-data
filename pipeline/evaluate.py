"""Measures fact readers and verifiers at each model and effort on one benefit group.

Usage: python3 -I pipeline/evaluate.py <year> <work> <dir> <group> <all|sample> <dollars> [api]

Every reader extracts facts from the same documents: all of them, or one per carrier and kind.
The reviewer judges each reader's facts, mixed with decoys, and each verifier judges the same items.
<dir> holds the task files. data/<year>/evaluations/<group> holds the saved answers and the report.
A rerun asks only new tasks. Without `api`, the run stops at the first step with unanswered tasks.
With `api`, a task left unanswered counts against its role, and no role starts once the saved answers cost <dollars>.
"""
import collections, contextlib, glob, io, json, math, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ask, blanks, expected, extract, facts, years
from eoc import Doc
from filled import numbers

MODELS = ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5")
EFFORTS = ("low", "medium", "high")
READERS = [(m, e) for m in MODELS for e in EFFORTS]
REVIEWER = ("claude-opus-5-5", "high")
# Haiku never judges a fact.
VERIFIERS = [r for r in READERS if r[0] != "claude-haiku-5-5" and r != REVIEWER]
# Dollars per million tokens: input, output, cache read, cache write.
PRICES = {"claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125), "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50),
          "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00)}
COLUMN = {"imaging": ("main", "L_xray_imaging")}
# A verifier must accept this share of the facts the reviewer accepts.
AGREEMENT = 0.9
Z = 1.96


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
    prices = PRICES[model]
    tokens = [usage.get(k, 0) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                         "cache_creation_input_tokens")]
    return sum(t * p for t, p in zip(tokens, prices)) / 1e6


def spent(tasks, role, saved):
    """Dollars the saved answers to these tasks cost. A task whose replies never parsed has no saved answer."""
    total = 0.0
    for t in tasks:
        with open(t) as f:
            path = os.path.join(saved, ask.key(role[0], f.read(), role[1]) + ".json")
        if os.path.exists(path):
            with open(path) as f:
                total += cost(role[0], json.load(f).get("usage", {}))
    return total


def all_spent(saved):
    total = 0.0
    for path in glob.glob(f"{saved}/*.json"):
        with open(path) as f:
            a = json.load(f)
        total += cost(a["model"], a.get("usage", {}))
    return total


class Unanswered(Exception):
    pass


class Runner:
    def __init__(self, saved, asker, budget):
        self.saved, self.asker, self.budget = saved, asker, budget

    def affordable(self):
        return all_spent(self.saved) < self.budget

    def answer(self, tasks, role):
        """The tasks left unanswered."""
        left = ask.answer(tasks, role[0], self.saved, self.asker, role[1])
        if left and not self.asker:
            raise Unanswered(f"{len(left)} tasks for {name(role)} have no answer, such as {left[0]}")
        return left


def quiet(f, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        f(*args, **kwargs)


def read(work, data, root, group, role, docs, runner):
    """The reader's facts, its count of unanswered tasks, and the dollars its answers cost."""
    d = f"{root}/read/{name(role)}"
    shutil.rmtree(d, ignore_errors=True)
    extract.read(work, d, group, data, ids={doc["id"] for doc in docs})
    left = runner.answer(sorted(glob.glob(f"{d}/*.md")), role)
    quiet(extract.extract_facts, work, d, group, f"{d}/facts.json", data)
    left += runner.answer(sorted(glob.glob(f"{d}/*.retry.md")), role)
    quiet(extract.extract_facts, work, d, group, f"{d}/facts.json", data)
    with open(f"{d}/facts.json") as f:
        return json.load(f), len(left), spent(sorted(glob.glob(f"{d}/*.md")), role, runner.saved)


def seen(fact):
    """The fields a verifier sees."""
    return tuple(fact[c] for c in facts.COLUMNS if c != "note")


def claim(fact):
    return fact["doc_sha"], fact["fact_id"], fact["amount"]


def pool(by_reader):
    """Every reader's facts, once for each way a verifier would see them."""
    return sorted({seen(f): f for found in by_reader.values() for f in found}.values(), key=seen)


def judged(items, verdicts):
    """{item index: accepted}. An item without a verdict is rejected."""
    ok = collections.defaultdict(lambda: True)
    for v in verdicts:
        ok[v["id"]] &= v.get("ok") is True
    return {i: i in ok and ok[i] for i in range(len(items))}


def wilson(hits, n):
    """The 95% interval of a share, or None for no trials."""
    if not n:
        return None
    p = hits / n
    mid, half = p + Z * Z / (2 * n), Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n))
    scale = 1 + Z * Z / n
    return round((mid - half) / scale, 3), round((mid + half) / scale, 3)


def share(hits, n):
    return {"hits": hits, "n": n, "share": round(hits / n, 3) if n else None, "interval": wilson(hits, n)}


def score_reader(found, verdict_of, truth):
    """Precision by the verdict on the reader's own items; recall over the claims the reviewer accepted from any reader."""
    good = [f for f in found if verdict_of[seen(f)]]
    return {"precision": share(len(good), len(found)), "recall": share(len({claim(f) for f in good} & truth), len(truth))}


def score_verifier(items, verdict, reviewer):
    real = [i for i, c in enumerate(items) if not c["decoy"]]
    decoys = [i for i, c in enumerate(items) if c["decoy"]]
    return {"decoys_accepted": share(sum(verdict[i] for i in decoys), len(decoys)),
            "agrees_accepted": share(sum(verdict[i] for i in real if reviewer[i]), sum(reviewer[i] for i in real)),
            "agrees_rejected": share(sum(not verdict[i] for i in real if not reviewer[i]),
                                     sum(not reviewer[i] for i in real))}


def score_expected(found, wanted, docs, group):
    """The share of expected cell lines whose numbers all appear in in-network facts of the group that passed the code checks.
    It does not use the reviewer, so it checks the reviewer too."""
    amounts = collections.defaultdict(collections.Counter)
    for f in found:
        if facts.covers(group, f["benefit"]) and f["network"] in ("in", "any"):
            amounts[f["plan_id"]] |= numbers(f["amount"])
    covered = {p for d in docs for p in d["plan_ids"]}
    lines = [w for w in wanted if w["plan_id"] in covered]
    return share(sum(not numbers(w["value"]) - amounts[w["plan_id"]] for w in lines), len(lines))


def upper(s):
    return s["interval"][1] if s["interval"] else 0


def picks(readers, verifiers, reviewer):
    """The cheapest reader whose precision and recall could match the reviewer's model as a reader,
    and the cheapest verifier that rejects every decoy and accepts what the reviewer accepts."""
    decoys = reviewer["decoys_accepted"]
    best = next((s for s in readers if s["role"] == name(REVIEWER)), None)
    if not decoys["n"] or decoys["hits"] or not best or not best["precision"]["n"]:
        return {"reader": None, "verifier": None}

    def cheapest(scores, ok):
        fits = [s for s in scores if ok(s)]
        return min(fits, key=lambda s: s["dollars"])["role"] if fits else None

    return {
        "reader": cheapest(readers, lambda s: not s["unanswered"]
                           and upper(s["precision"]) >= best["precision"]["share"]
                           and upper(s["recall"]) >= best["recall"]["share"]),
        "verifier": cheapest(verifiers, lambda s: not s["unanswered"] and s["decoys_accepted"]["n"]
                             and not s["decoys_accepted"]["hits"]
                             and (s["agrees_accepted"]["share"] or 0) >= AGREEMENT),
    }


def shown(s):
    return "n/a" if s["share"] is None else f"{s['hits']}/{s['n']} ({s['interval'][0]}-{s['interval'][1]})"


def report(readers, verifiers, reviewer, chosen):
    lines = [f"Reviewer {name(REVIEWER)} accepted {shown(reviewer['decoys_accepted'])} decoys "
             f"and cost ${reviewer['dollars']:.2f}.",
             "The reviewer is the same model as one reader and some verifiers, so it may favor them.", "",
             "| Reader | Precision | Recall | Expected lines shown | Unanswered | $ |", "|---|---|---|---|---|---|"]
    lines += [f"| {s['role']} | {shown(s['precision'])} | {shown(s['recall'])} | {shown(s['expected'])} | "
              f"{s['unanswered']} | {s['dollars']:.2f} |" for s in readers]
    lines += ["", "| Verifier | Decoys accepted | Accepts the reviewer's accepts | Rejects the reviewer's rejects "
              "| Unanswered | $ |", "|---|---|---|---|---|---|"]
    lines += [f"| {s['role']} | {shown(s['decoys_accepted'])} | {shown(s['agrees_accepted'])} | "
              f"{shown(s['agrees_rejected'])} | {s['unanswered']} | {s['dollars']:.2f} |" for s in verifiers]
    lines += ["", "Intervals are 95% Wilson intervals.",
              f"Cheapest reader whose intervals reach {name(REVIEWER)}'s precision and recall: {chosen['reader']}.",
              f"Cheapest verifier that accepts no decoy and at least {AGREEMENT:.0%} of the reviewer's accepts: "
              f"{chosen['verifier']}."]
    return "\n".join(lines) + "\n"


def main(year, work, root, group, which, budget, mode=""):
    data = years.data_dir(int(year))
    sheet, column = COLUMN[group]
    wanted = [w for w in expected.load() if (w["sheet"], w["column"]) == (sheet, column)]
    out = data / "evaluations" / group
    runner = Runner(out / "answers", ask.api() if mode == "api" else None, float(budget))
    docs = [d for d in extract.documents(data) if extract.relevant(Doc(work, d["id"]).pages("layout"), group)]
    docs = docs if which == "all" else sample(docs, extract.plans(data))

    by_reader, readers = {}, []
    for role in READERS:
        if not runner.affordable():
            print(f"Over budget before {name(role)}")
            break
        found, left, dollars = read(work, data, root, group, role, docs, runner)
        by_reader[name(role)] = found
        readers.append({"role": name(role), "unanswered": left, "dollars": dollars,
                        "expected": score_expected(found, wanted, docs, group)})

    check = f"{root}/check"
    shutil.rmtree(check, ignore_errors=True)
    os.makedirs(check)
    with open(f"{check}/pool.json", "w") as f:
        json.dump(pool(by_reader), f, indent=1)
    quiet(extract.verify, work, f"{check}/pool.json", check, data)
    with open(f"{check}/items.json") as f:
        items = json.load(f)
    verdicts, scores = {}, []
    for role in [REVIEWER] + VERIFIERS:
        if role != REVIEWER and not runner.affordable():
            print(f"Over budget before {name(role)}")
            break
        d = f"{check}/{name(role)}"
        os.makedirs(d)
        for t in glob.glob(f"{check}/v-*.md"):
            shutil.copy(t, d)
        tasks = sorted(glob.glob(f"{d}/v-*.md"))
        left = runner.answer(tasks, role)
        verdicts[name(role)] = judged(items, blanks.verdicts(items, d))
        scores.append({"role": name(role), "unanswered": len(left), "dollars": spent(tasks, role, runner.saved)})

    reviewer = verdicts[name(REVIEWER)]
    verdict_of = {seen(c): reviewer[i] for i, c in enumerate(items) if not c["decoy"]}
    truth = {claim(c) for i, c in enumerate(items) if reviewer[i] and not c["decoy"]}
    for s in readers:
        s.update(score_reader(by_reader[s["role"]], verdict_of, truth))
    for s in scores:
        s.update(score_verifier(items, verdicts[s["role"]], reviewer))
    review, verifiers = scores[0], scores[1:]
    chosen = picks(readers, verifiers, review)
    text = report(readers, verifiers, review, chosen)
    with open(out / f"{which}.json", "w") as f:
        json.dump({"documents": [d["id"] for d in docs], "readers": readers, "verifiers": verifiers,
                   "reviewer": review, "picks": chosen}, f, indent=1)
        f.write("\n")
    with open(out / f"{which}.md", "w") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    if len(sys.argv) not in (7, 8) or sys.argv[5] not in ("all", "sample"):
        raise SystemExit(__doc__)
    try:
        main(*sys.argv[1:])
    except Unanswered as e:
        raise SystemExit(str(e))
