"""A reviewer checks each new fact that a presented cell cites, before the facts are written.

A fact that no cell cites changes nothing on the sheet, so it goes unreviewed. Each review task holds one fact, so a
rerun asks again only for facts it has not seen. Facts the reviewer rejects are dropped. Dropping one can let a cell
cite another new fact, so the review repeats until every cited new fact has a verdict.
"""
import json, os, shutil

import ask, blanks, extract, facts, present
from eoc import Doc


def row(f):
    return tuple(f[c] for c in facts.COLUMNS)


def to_review(data, old, new):
    """The facts in new and not in old that a presented cell cites."""
    known = {row(f) for f in old}
    cited = {row(f) for column in present.COLUMNS
             for plan_id, got in present.lines(data, column, new).items() if (column, plan_id) not in present.HELD
             for _, used in got for f in used}
    return [f for f in new if row(f) in cited and row(f) not in known]


def task(data, work):
    docs = {d["sha256"]: d for d in extract.documents(data)}
    plan_rows = extract.plans(data)

    def of(f):
        doc = docs[f["doc_sha"]]
        return extract.verifier_task(doc, plan_rows, Doc(work, doc["id"]).pages("layout"), [f], data)
    return of


def gate(data, texts, work, answer, old, new, version, task_of=None):
    """new without the facts the reviewer rejects. Stops if more facts than version["review_cap"] lack a saved answer."""
    task_of = task_of or task(data, texts)
    model, effort = version["reviewer"]
    verdict = {}
    while True:
        pending = [f for f in to_review(data, old, [f for f in new if verdict.get(row(f)) is not False])
                   if row(f) not in verdict]
        if not pending:
            return [f for f in new if verdict.get(row(f)) is not False]
        texts_of = {f["fact_id"] + f["doc_sha"][:8] + f["page"]: task_of(f) for f in pending}
        unsaved = [t for t in texts_of.values() if not os.path.exists(data / "answers" / f"{ask.key(model, t, effort)}.json")]
        if len(unsaved) > version["review_cap"]:
            raise SystemExit(f"{len(unsaved)} facts need review, more than the cap of {version['review_cap']}.")
        out = f"{work}/review"
        shutil.rmtree(out, ignore_errors=True)
        os.makedirs(out)
        for name, text in texts_of.items():
            with open(f"{out}/v-{name}.md", "w") as f:
                f.write(text)
        answer(out, model, effort)
        items = [dict(f, task=name) for name, f in zip(texts_of, pending)]
        ok = {v["id"] for v in blanks.verdicts(items, out) if v.get("ok") is True}
        verdict.update({row(f): i in ok for i, f in enumerate(pending)})
