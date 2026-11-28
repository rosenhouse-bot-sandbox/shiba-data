"""A reviewer checks each fact that a presented cell cites.

Each review task holds one fact, so a saved answer settles a fact until its task changes.
"""
import os, shutil

import ask, extract, facts, present
from eoc import Doc

# Facts a cell keeps citing although the reviewer rejects them. This list should only shrink.
KEPT = "machine/kept_rejected.csv"


def row(f):
    return tuple(f[c] for c in facts.COLUMNS)


def cited(data, document, version):
    """The rows of the facts in document that a cell cites in a present version, but for the held cells."""
    held = present.held(data, version)
    return {row(f) for sheet, (rules, _) in present.SHEETS.items() for column in rules
            for plan_id, got in present.lines(data, column, document, sheet, version).items()
            if present.cell(sheet, column, plan_id) not in held for _, used in got for f in used}


def kept(data):
    """The rows of KEPT, if the year has one."""
    path = data / KEPT
    return {row(f) for f in facts.read(path)} if path.exists() else set()


def to_review(data, new, version):
    """The facts in new, once each, that a presented cell cites."""
    rows = cited(data, new, version)
    return list({row(f): f for f in new if row(f) in rows}.values())


def joined(*notes):
    """Each group's notes, in order."""
    return {g: " ".join(n[g] for n in notes if n.get(g)) for g in set().union(*notes)}


def checker_notes(version):
    """The notes for each group's verifier: the version's notes, then its check_notes."""
    return joined(version.get("notes", {}), version.get("check_notes", {}))


def second_notes(version):
    """The notes for each group's second verifier and reviewer: the checker notes, then the recheck_notes."""
    return joined(checker_notes(version), version.get("recheck_notes", {}))


def plan_notes(version):
    """Each group's notes per plan for second readers, their checkers and the reviewer: the plan_notes, then the
    recheck_plan_notes. Plans keep their order, so a prompt that names two plans stays the same."""
    first, second = version.get("plan_notes", {}), version.get("recheck_plan_notes", {})
    return {g: {p: " ".join(n[p] for n in (first.get(g, {}), second.get(g, {})) if n.get(p))
                for p in dict.fromkeys([*first.get(g, {}), *second.get(g, {})])} for g in set(first) | set(second)}


def task(data, texts, notes={}, after={}, before={}, plan_notes={}, kinds={}):
    docs = {d["sha256"]: d for d in extract.documents(data)}
    plan_rows = extract.plans(data)
    pages = {}

    def of(f):
        doc, group = docs[f["doc_sha"]], f["benefit"].split(".")[0]
        if doc["id"] not in pages:
            pages[doc["id"]] = Doc(texts, doc["id"]).pages("layout")
        return extract.verifier_task(doc, plan_rows, pages[doc["id"]], [f], data, extract.doc_notes(
            doc, (group,), notes, plan_notes, (f["plan_id"],), kinds.get(group, {})), after=after, before=before)
    return of


def reviewer_task(data, texts, version):
    return task(data, texts, second_notes(version), version.get("check_after", {}), version.get("check_before", {}),
                plan_notes(version), version.get("kinds", {}) if version.get("reviewer_sees_kinds") else {})


def saved(data, model, text, effort):
    return (data / "answers" / f"{ask.key(model, text, effort)}.json").exists()


def gate(data, texts, work, answer, new, version, present_version, task_of=None):
    """new without the facts the reviewer rejects, but for those in KEPT.
    Stops if more cited facts than version["review_cap"] lack a saved answer. Writes <work>/review/outcomes.json."""
    task_of = task_of or reviewer_task(data, texts, version)
    model, effort = version["reviewer"]
    frozen = kept(data)
    verdict, unsaved, outcomes, out = {}, 0, [], f"{work}/review"
    while True:
        kept_rows = [f for f in new if verdict.get(row(f)) is not False or row(f) in frozen]
        pending = [f for f in to_review(data, kept_rows, present_version) if row(f) not in verdict]
        if not pending:
            break
        texts_of = [task_of(f) for f in pending]
        unsaved += sum(not saved(data, model, t, effort) for t in texts_of)
        if unsaved > version["review_cap"]:
            raise SystemExit(f"The review needs {unsaved} new answers, more than the cap of {version['review_cap']}.")
        got = ask_each(out, answer, model, effort, texts_of)
        for f, text, v in zip(pending, texts_of, got):
            verdict[row(f)] = v.get("ok") is True
            outcomes.append(outcome(f, text, v))
            if not verdict[row(f)] and row(f) not in frozen:
                print(f"Reviewer rejected {f['plan_id']} {f['benefit']} {f['amount']}: {v.get('reason', 'no verdict')}")
    stale = {row(f) for f in new if row(f) in frozen and verdict.get(row(f)) is not False}
    if stale:
        raise SystemExit(f"{KEPT} lists {len(stale)} facts that no cell cites or that the reviewer accepts. Remove them:\n"
                         + "\n".join(f"{r[1]} {r[2]} {r[11]}" for r in sorted(stale)))
    os.makedirs(out, exist_ok=True)
    extract.write_outcomes(out, outcomes)
    return kept_rows


def ask_each(out, answer, model, effort, texts):
    """The verdict on each text, asked as its own task in a fresh out."""
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    for n, text in enumerate(texts):
        with open(f"{out}/v-{n}.md", "w") as f:
            f.write(text)
    answer(out, model, effort)
    got = {v["id"]: v for v in extract.verdicts([dict(task=str(n)) for n in range(len(texts))], out)}
    return [got.get(n, {}) for n in range(len(texts))]


def outcome(f, text, v):
    return dict(step="reviewer", prompt=ask.sha(text), item=0, fact=extract.named(f), ok=v.get("ok"), reason=v.get("reason", ""))
