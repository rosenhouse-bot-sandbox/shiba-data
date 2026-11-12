"""Shows, without the API, which plans a candidate document_facts version would change, and fails if any plan is
outside the version's targets.

Usage: python3 -I pipeline/blast.py <year> <work_dir> document_facts@<version>

<work_dir> needs the PDF texts that run.py's replay reads. This runs the model steps twice: pinned, then with the
candidate. In the candidate run, a task without a saved answer gets the answer the pinned run implies: a reader gets the
pinned run's answer for the same document, and a verifier or reviewer keeps what the pinned run kept. A plan fails if a
task without a saved answer is about it, or if its document facts or presented cells change. Each run writes
data/<year>, so data/<year> must be clean, and is restored after.
"""
import csv
import glob
import json
import os
import re
import subprocess
import sys

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__))]
import ask  # noqa: E402
import blobs  # noqa: E402
import extract  # noqa: E402
import facts  # noqa: E402
import layers  # noqa: E402
import run  # noqa: E402
import steps  # noqa: E402
import years  # noqa: E402

# A verifier or review task lists each fact it judges as one JSON line.
ITEM = re.compile(r'^\{"id": \d+, .*\}$', re.M)


def ledger(work):
    path = f"{work}/{blobs.LEDGER}"
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return list(csv.DictReader(f))


def kept(f):
    """What a verdict judged of a fact."""
    return f.get("fact_id") or facts.fact_id({k: f.get(k, "") for k in facts.KEY}), str(f["page"]), f.get("amount", "")


class Pinned:
    """What the pinned run answered and kept, read from its work dir before the candidate run replaces it."""

    def __init__(self, work, rows):
        self.answer = {(r["dir"], r["task"]): r["key"] for r in rows}
        self.kept = {os.path.relpath(os.path.dirname(p), work): {kept(f) for f in facts.read(p)}
                     for p in glob.glob(f"{work}/facts/*/*/accepted.csv")}
        self.reviewed = {}
        for p in glob.glob(f"{work}/facts/review/**/{extract.OUTCOMES}", recursive=True):
            with open(p) as f:
                self.reviewed |= {(o["fact"]["fact_id"], str(o["fact"]["page"])): o["ok"] is True for o in json.load(f)}


class Stub:
    """An asker that answers each task as the pinned run implies."""

    def __init__(self, pinned, saved, work):
        self.pinned, self.saved, self.work = pinned, saved, work

    def __call__(self, model, effort, texts):
        # Answers lists a task in the ledger before asking.
        row = {r["prompt"]: r for r in ledger(self.work) if r["prompt"]}
        return {k: (json.dumps(self.reply(row[ask.sha(text)], text)), {}) for k, text in texts.items()}

    def reply(self, row, text):
        name = row["task"].removeprefix("v-").split(".")[0]
        if row["dir"].startswith("facts/review"):
            return [{"id": i["id"], "ok": self.pinned.reviewed.get(kept(i)[:2], True)} for i in map(json.loads, ITEM.findall(text))]
        if row["task"].startswith("v-"):
            with open(f"{self.work}/{row['dir']}/items.json") as f:
                items = [i for i in json.load(f) if i["task"] == name]
            ok = self.pinned.kept.get(row["dir"], set())
            return [{"id": n, "ok": not i["decoy"] and kept(i) in ok} for n, i in enumerate(items)]
        key = self.pinned.answer.get((row["dir"], row["task"]))
        if key is None:
            return []
        with open(os.path.join(self.saved, f"{key}.json")) as f:
            return ask.array(json.load(f)["reply"])


def touched(row, text, docs, version):
    """The (group, plan) pairs a task is about."""
    group, doc = row["dir"].split("/")[1], docs.get(row["task"].removeprefix("v-").split(".")[0])
    if doc is None:
        pairs = {(i["benefit"].split(".")[0], i["plan_id"]) for i in map(json.loads, ITEM.findall(text))}
    else:
        second = row["dir"].rsplit("/", 1)[1] in ("reread", "recheck")
        pairs = {(group, p) for p in doc["plan_ids"] if not second or p in version.get("recheck", {}).get(group, ())}
    if not pairs:
        raise SystemExit(f"Cannot tell which plans {row['dir']}/{row['task']} is about.")
    return pairs


def changed_plans(before, after):
    """The (group, plan) pairs whose document facts differ, and the plans whose presented rows differ."""
    def facts_by(rows):
        return {(r["benefit"].split(".")[0], r["plan_id"], *r.values()) for r in rows}

    def presented_by(rows):
        return {(r["plan_id"], *r.values()) for r in rows}
    pairs = {f[:2] for f in facts_by(before["facts"]) ^ facts_by(after["facts"])}
    plans = {p[0] for p in presented_by(before["presented"]) ^ presented_by(after["presented"])}
    return pairs, plans


def outside(pairs, plans, targets):
    every = {p for ps in targets.values() for p in ps}
    return sorted({(g, p) for g, p in pairs if p not in targets.get(g, ())} | {("presented", p) for p in plans - every})


def outputs(data):
    return dict(facts=facts.read(data / "machine/document_facts.csv"), presented=layers.rows(data / layers.PRESENTED))


def git(*args):
    return subprocess.run(["git", "-C", str(years.REPO), *args], check=True, capture_output=True, text=True).stdout


def restore(data):
    git("checkout", "--", str(data))
    git("clean", "-fdq", "--", str(data))


def model_steps(data, work, versions, asker):
    """The ledger of one run of the model steps. The work dir keeps no ledger, so a later run.py lists only its own tasks."""
    try:
        run.model_steps(data, f"{work}/texts", work, run.Answers(data, asker, work), versions)
        return ledger(work)
    finally:
        if os.path.exists(f"{work}/{blobs.LEDGER}"):
            os.remove(f"{work}/{blobs.LEDGER}")


def main(year, work, candidate):
    data, work = years.data_dir(year), os.path.abspath(work)
    if candidate.partition("@")[0] != "document_facts" or "," in candidate:
        raise SystemExit("blast.py checks one document_facts candidate.")
    if git("status", "--porcelain", "--ignored", "--", str(data)):
        raise SystemExit(f"{data} has uncommitted changes.")
    try:
        before = outputs(data)
        pinned = Pinned(work, model_steps(data, work, steps.versions(data, run.STEPS), None))
        restore(data)
        saved = set(os.listdir(data / "answers"))
        versions = steps.versions(data, run.STEPS, candidate)
        rows = model_steps(data, work, versions, Stub(pinned, data / "answers", work))
        after = outputs(data)
    finally:
        restore(data)
    docs = {d["id"]: d for d in extract.documents(data)}
    version = run.STEPS["document_facts"][versions["document_facts"]]
    new = [r for r in rows if f"{r['key']}.json" not in saved]
    asked = set()
    for r in new:
        with open(f"{work}/{blobs.PROMPTS}/{r['prompt']}") as f:
            asked |= touched(r, f.read(), docs, version)
    pairs, plans = changed_plans(before, after)
    print(f"{len(new)} of {len(rows)} tasks would call the API, about:")
    print("\n".join(f"  {g} {p}" for g, p in sorted(asked)))
    print("Changed document facts:\n" + "\n".join(f"  {g} {p}" for g, p in sorted(pairs)))
    print("Changed presented cells:\n" + "\n".join(f"  {p}" for p in sorted(plans)))
    wide = outside(asked | pairs, plans, version.get("targets", {}))
    if wide:
        raise SystemExit("Outside the version's targets:\n" + "\n".join(f"  {g} {p}" for g, p in wide))


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
