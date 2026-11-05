"""A reviewer checks each fact that a presented cell cites, unless an earlier run trusted it.

Each review task holds one fact, so a rerun asks again only for facts it has not seen.
"""
import os, shutil

import ask, blanks, extract, facts, present
from eoc import Doc

REVIEWED = "machine/reviewed_facts.csv"


def row(f):
    return tuple(f[c] for c in facts.COLUMNS)


def cited(data, document, held):
    """The rows of the facts in document that a presented cell cites, but for the held cells."""
    return {row(f) for column in present.COLUMNS
            for plan_id, got in present.lines(data, column, document).items() if (column, plan_id) not in held
            for _, used in got for f in used}


def trusted(data, old, held):
    """The rows an earlier run reviewed. Before the first review, the cited rows of the old facts."""
    path = data / REVIEWED
    return {row(f) for f in facts.read(path)} if path.exists() else cited(data, old, held)


def to_review(data, trusted_rows, new, held):
    """The facts in new, once each, that a presented cell cites and that are not trusted."""
    rows = cited(data, new, held) - trusted_rows
    return list({row(f): f for f in new if row(f) in rows}.values())


def task(data, texts):
    docs = {d["sha256"]: d for d in extract.documents(data)}
    plan_rows = extract.plans(data)

    def of(f):
        doc = docs[f["doc_sha"]]
        return extract.verifier_task(doc, plan_rows, Doc(texts, doc["id"]).pages("layout"), [f], data)
    return of


def saved(data, model, text, effort):
    return (data / "answers" / f"{ask.key(model, text, effort)}.json").exists()


def gate(data, texts, work, answer, trusted_rows, new, version, held, task_of=None):
    """new without the facts the reviewer rejects, and the kept facts that are cited or trusted, which a later run trusts.
    Stops if more facts than version["review_cap"] lack a saved answer."""
    task_of = task_of or task(data, texts)
    model, effort = version["reviewer"]
    verdict, unsaved = {}, 0
    while True:
        kept = [f for f in new if verdict.get(row(f)) is not False]
        pending = [f for f in to_review(data, trusted_rows, kept, held) if row(f) not in verdict]
        if not pending:
            rows = cited(data, kept, held) | trusted_rows
            return kept, [f for f in kept if row(f) in rows]
        texts_of = [task_of(f) for f in pending]
        unsaved += sum(not saved(data, model, t, effort) for t in texts_of)
        if unsaved > version["review_cap"]:
            raise SystemExit(f"The review needs {unsaved} new answers, more than the cap of {version['review_cap']}.")
        out = f"{work}/review"
        shutil.rmtree(out, ignore_errors=True)
        os.makedirs(out)
        for n, text in enumerate(texts_of):
            with open(f"{out}/v-{n}.md", "w") as f:
                f.write(text)
        answer(out, model, effort)
        got = {v["id"]: v for v in blanks.verdicts([dict(task=str(n)) for n in range(len(pending))], out)}
        for n, f in enumerate(pending):
            verdict[row(f)] = got.get(n, {}).get("ok") is True
            if not verdict[row(f)]:
                print(f"Reviewer rejected {f['plan_id']} {f['benefit']} {f['amount']}: {got.get(n, {}).get('reason', 'no verdict')}")
