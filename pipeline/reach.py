"""Which plans a document_facts task is about, and an asker that asks only about a version's target plans."""
import csv
import json
import os
import re

import ask
import blobs
import extract

# A verifier or review task lists each fact it judges as one JSON line.
ITEM = re.compile(r'^\{"id": \d+, .*\}$', re.M)


def ledger(work):
    path = f"{work}/{blobs.LEDGER}"
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return list(csv.DictReader(f))


def touched(row, text, docs, version):
    """The (group, plan) pairs a task is about."""
    group, doc = row["dir"].split("/")[-2], docs.get(row["task"].removeprefix("v-").split(".")[0])
    if doc is None:
        pairs = {(i["benefit"].split(".")[0], i["plan_id"]) for i in map(json.loads, ITEM.findall(text))}
    else:
        second = row["dir"].rsplit("/", 1)[1] in ("reread", "recheck")
        pairs = {(group, p) for p in doc["plan_ids"] if not second or p in version.get("recheck", {}).get(group, ())}
    if not pairs:
        raise SystemExit(f"Cannot tell which plans {row['dir']}/{row['task']} is about.")
    return pairs


def outside(pairs, targets, presented=()):
    """The (group, plan) pairs, and ("presented", plan) for the presented plans, that the targets do not name."""
    every = {p for ps in targets.values() for p in ps}
    return sorted({(g, p) for g, p in pairs if p not in targets.get(g, ())} | {("presented", p) for p in set(presented) - every})


class Guard:
    """An asker that stops before asking about a plan outside the version's targets."""

    def __init__(self, asker, data, work, version):
        self.asker, self.data, self.work, self.version = asker, data, work, version
        self.batch = getattr(asker, "batch", False)

    def __call__(self, model, effort, texts):
        rows = {r["prompt"]: r for r in ledger(self.work)}
        docs = {d["id"]: d for d in extract.documents(self.data)}
        pairs = set().union(*(touched(rows[ask.sha(t)], t, docs, self.version) for t in texts.values()))
        wide = outside(pairs, self.version.get("targets", {}))
        if wide:
            raise SystemExit("Not asking about plans outside the version's targets:\n"
                             + "\n".join(f"  {g} {p}" for g, p in wide))
        return self.asker(model, effort, texts)
