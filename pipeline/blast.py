"""Shows, without the API, which plans a candidate document_facts version would change, and fails if any plan is
outside the version's targets.

Usage: python3 -I pipeline/blast.py <year> <work_dir> document_facts@<version>

<work_dir> needs the PDF texts that run.py's replay reads. This runs the model steps twice: pinned, then with the
candidate. In the candidate run, a task without a saved answer gets the answer the pinned run implies: a reader gets the
pinned run's answer for the same document, and a verifier or reviewer keeps what the pinned run kept. A plan fails if a
task without a saved answer is about it, or if its document facts or presented cells change. Each run writes
data/<year>, so data/<year> must be clean, and is restored after.
"""
import contextlib
import glob
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__))]
import ask  # noqa: E402
import blobs  # noqa: E402
import extract  # noqa: E402
import facts  # noqa: E402
import layers  # noqa: E402
import reach  # noqa: E402
import run  # noqa: E402
import steps  # noqa: E402
import years  # noqa: E402


def judged(f):
    """What a verdict judged of a fact. A review item does not name its document, so a reviewer looks only at the first two."""
    return (f.get("fact_id") or facts.fact_id({k: f.get(k, "") for k in facts.KEY}), str(f["page"]), f.get("doc_sha", ""),
            f.get("amount", ""))


class Pinned:
    """What the pinned run answered and kept, read from its work dir before the candidate run replaces it."""

    def __init__(self, work, rows):
        self.answer = {(r["dir"], r["task"]): r["key"] for r in rows}
        self.kept = {os.path.relpath(os.path.dirname(p), work): {judged(f) for f in facts.read(p)}
                     for p in glob.glob(f"{work}/facts/*/*/accepted.csv")}
        self.reviewed = {}
        for p in glob.glob(f"{work}/facts/review/**/{extract.OUTCOMES}", recursive=True):
            with open(p) as f:
                self.reviewed |= {judged(o["fact"])[:2]: o["ok"] is True for o in json.load(f)}


class Stub:
    """An asker that answers each task as the pinned run implies."""

    def __init__(self, pinned, saved, work):
        self.pinned, self.saved, self.work = pinned, saved, work

    def __call__(self, model, effort, texts):
        # Answers lists a task in the ledger before asking.
        row = {r["prompt"]: r for r in reach.ledger(self.work)}
        return {k: (json.dumps(self.reply(row[ask.sha(text)], text)), {}) for k, text in texts.items()}

    def reply(self, row, text):
        name = row["task"].removeprefix("v-").split(".")[0]
        if row["dir"].startswith("facts/review"):
            return [{"id": i["id"], "ok": self.pinned.reviewed.get(judged(i)[:2], True)}
                    for i in map(json.loads, reach.ITEM.findall(text))]
        if row["task"].startswith("v-"):
            with open(f"{self.work}/{row['dir']}/items.json") as f:
                items = [i for i in json.load(f) if i["task"] == name]
            ok = self.pinned.kept.get(row["dir"], set())
            return [{"id": n, "ok": not i["decoy"] and judged(i) in ok} for n, i in enumerate(items)]
        key = self.pinned.answer.get((row["dir"], row["task"]))
        if key is None:
            return []
        with open(os.path.join(self.saved, f"{key}.json")) as f:
            return ask.array(json.load(f)["reply"])


def changed_plans(before, after):
    """The (group, plan) pairs whose document facts differ, and the plans whose presented rows differ."""
    def facts_by(rows):
        return {(r["benefit"].split(".")[0], r["plan_id"], *r.values()) for r in rows}

    def presented_by(rows):
        return {(r["plan_id"], *r.values()) for r in rows}
    pairs = {f[:2] for f in facts_by(before["facts"]) ^ facts_by(after["facts"])}
    plans = {p[0] for p in presented_by(before["presented"]) ^ presented_by(after["presented"])}
    return pairs, plans


def asked(rows, work, docs, version):
    """The (group, plan) pairs the tasks are about."""
    pairs = set()
    for r in rows:
        with open(f"{work}/{blobs.PROMPTS}/{r['prompt']}") as f:
            pairs |= reach.touched(r, f.read(), docs, version)
    return pairs


def outputs(data):
    return dict(facts=facts.read(data / "machine/document_facts.csv"), presented=layers.rows(data / layers.PRESENTED))


def git(*args):
    return subprocess.run(["git", "-C", str(years.REPO), *args], check=True, capture_output=True, text=True).stdout


def restore(data):
    git("checkout", "--", str(data))
    git("clean", "-fdq", "--", str(data))


def model_steps(data, work, versions, asker, saved):
    """The ledger of one quiet run of the model steps. The work dir keeps no ledger, so a later run.py lists only its own
    tasks."""
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            run.model_steps(data, f"{work}/texts", work, run.Answers(data, asker, work, saved), versions)
        return reach.ledger(work)
    except BaseException as e:
        print(out.getvalue(), end="")
        if asker is None and isinstance(e, SystemExit):
            raise SystemExit("The pinned version has tasks without saved answers.") from e
        raise
    finally:
        if os.path.exists(f"{work}/{blobs.LEDGER}"):
            os.remove(f"{work}/{blobs.LEDGER}")


def main(year, work, candidate):
    data, work = years.data_dir(year), os.path.abspath(work)
    if candidate.partition("@")[0] != "document_facts" or "," in candidate:
        raise SystemExit("blast.py checks one document_facts candidate.")
    if git("status", "--porcelain", "--ignored", "--", str(data)):
        raise SystemExit(f"{data} has uncommitted changes.")
    saved = set(os.listdir(data / "answers"))
    versions = steps.versions(data, run.STEPS, candidate)
    try:
        pinned = Pinned(work, model_steps(data, work, steps.versions(data, run.STEPS), None, None))
        before = outputs(data)
        restore(data)
        # The stand-in answers go to a copy, so data/<year>/answers never holds them.
        with tempfile.TemporaryDirectory() as copy:
            shutil.copytree(data / "answers", copy, dirs_exist_ok=True)
            rows = model_steps(data, work, versions, Stub(pinned, copy, work), copy)
        after = outputs(data)
    finally:
        restore(data)
    version = run.STEPS["document_facts"][versions["document_facts"]]
    new = [r for r in rows if f"{r['key']}.json" not in saved]
    pairs = asked(new, work, {d["id"]: d for d in extract.documents(data)}, version)
    changed, plans = changed_plans(before, after)
    print(f"{len(new)} of {len(rows)} tasks would call the API.")
    wide = reach.outside(pairs | changed, version.get("targets", {}), plans)
    print("Plans these tasks are about, or whose document facts or presented cells change:\n"
          + "\n".join(f"  {g} {p}" for g, p in sorted(pairs | changed | {("presented", p) for p in plans})))
    if wide:
        raise SystemExit("Outside the version's targets:\n" + "\n".join(f"  {g} {p}" for g, p in wide))


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
