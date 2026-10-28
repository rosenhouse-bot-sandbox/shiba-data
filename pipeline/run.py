"""Rebuilds data/<year>/generated from the sources in data/<year>/config.json, found.csv and links.csv,
then the live year's machine/blanks.csv and machine/filled.csv from model answers.

Usage: python3 -I pipeline/run.py <year> <work_dir> [api]

Saved answers in data/<year>/answers are reused. Without `api`, the run stops at the first model step
with tasks that have no saved answer, and lists them. With `api`, the Claude API answers them.
Needs pypdfium2, poppler's pdftotext and `npm ci` here, and the anthropic package for `api`.
"""
import csv
import glob
import hashlib
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "tests")]
import appendix_b  # noqa: E402
import ask  # noqa: E402
import eoc  # noqa: E402
import layers  # noqa: E402
import years  # noqa: E402

READER, VERIFIER, SECOND_VERIFIER = "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"


def get(url, path):
    if not (os.path.exists(path) and os.path.getsize(path)):
        subprocess.run(["curl", "-sS", "-L", "--fail", "--max-time", "900", "-A", "Mozilla/5.0", "-o", path, url],
                       check=True)


def py(script, *args):
    subprocess.run([sys.executable, "-I", os.path.join(HERE, script), *map(str, args)], check=True)


def pdfs(gen, work):
    """Links each fetched PDF as <work>/pdfs/<document id>.pdf, the name texts.py and the site use."""
    os.makedirs(f"{work}/pdfs", exist_ok=True)
    with open(gen / "documents_checked.csv") as f:
        for d in csv.DictReader(f):
            if d["sha256"]:
                src = f"{work}/docs/pdf/{hashlib.sha256(d['url'].encode()).hexdigest()[:16]}.pdf"
                dst = f"{work}/pdfs/{d['sha256'][:16]}.pdf"
                if not os.path.exists(dst):
                    os.link(src, dst)


def lost_quotes(data, texts):
    """Layer rows whose quote the site cannot highlight on its page."""
    with open(data / "generated" / "documents_checked.csv") as f:
        doc = {d["url"]: d["sha256"][:16] for d in csv.DictReader(f)}
    cites = [dict(c, doc=doc[c["url"]], page=c["pdf_page"]) for name in layers.LAYERS for c in layers.layer(data, name)
             if c["quote"].strip() and c["url"] in doc]
    return [c for c, found in zip(cites, eoc.highlights(texts, cites, "found")) if not found]


class Answers:
    """Answers each model step's task files from saved answers, or from the asker."""

    def __init__(self, data, asker):
        self.saved, self.asker = data / "answers", asker

    def __call__(self, task_dir, model):
        tasks = sorted(glob.glob(f"{task_dir}/*.md"))
        missing = ask.answer(tasks, model, self.saved, self.asker)
        if missing:
            print("\n".join(missing))
            raise SystemExit(f"{len(missing)} of {len(tasks)} tasks in {task_dir} have no answer from {model}. "
                             + ("Rerun to ask again." if self.asker else "Rerun with `api` to ask the Claude API."))


def fresh(path):
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path)
    return path


def blanks_step(texts, work, answer):
    import blanks
    read, check, recheck = (fresh(f"{work}/blanks/{d}") for d in ("read", "check", "recheck"))
    blanks.bundle(texts, read)
    answer(read, READER)
    blanks.claims(texts, read, f"{work}/blanks/claims.json")
    blanks.verify(texts, f"{work}/blanks/claims.json", check)
    answer(check, VERIFIER)
    blanks.accept(texts, check, f"{work}/blanks/checked.json")
    blanks.verify(texts, f"{work}/blanks/checked.json", recheck)
    answer(recheck, SECOND_VERIFIER)
    blanks.accept(texts, recheck, f"{work}/blanks/accepted.json")
    blanks.publish(f"{work}/blanks/accepted.json")


def filled_step(texts, work, answer, every=False):
    import filled
    read, check, recheck = (fresh(f"{work}/filled/{d}") for d in ("read", "check", "recheck"))
    filled.bundle(texts, read, "every" if every else "")
    answer(read, READER)
    filled.claims(texts, read, f"{work}/filled/claims.json")
    answer(read, READER)  # the retry tasks
    filled.claims(texts, read, f"{work}/filled/claims.json")
    filled.verify(texts, f"{work}/filled/claims.json", check)
    answer(check, VERIFIER)
    filled.accept(check, f"{work}/filled/checked.json")
    filled.verify(texts, f"{work}/filled/checked.json", recheck)
    answer(recheck, SECOND_VERIFIER)
    filled.accept(recheck, f"{work}/filled/accepted.json")
    filled.publish(f"{work}/filled/accepted.json")


def main(year, work, mode=""):
    if mode not in ("", "api"):
        raise SystemExit(__doc__)
    data = years.data_dir(year)
    config = years.config(data)
    work = os.path.abspath(work)
    os.makedirs(work, exist_ok=True)
    get(config["landscape_zip"], f"{work}/landscape.zip")
    get(config["pbp_zip"], f"{work}/pbp.zip")
    subprocess.run(["unzip", "-oq", f"{work}/landscape.zip", "-d", work], check=True)
    subprocess.run(["unzip", "-oq", f"{work}/pbp.zip", "-d", f"{work}/pbp"], check=True)

    gen = data / "generated"
    os.makedirs(gen, exist_ok=True)
    py("universe.py", f"{work}/{config['landscape_csv']}", gen / "plans.csv", config["state"], *config["counties"])
    baseline = [years.REPO / config["baseline_manifest"]] if "baseline_manifest" in config else []
    py("find_docs.py", gen / "plans.csv", data / "found.csv", data / "links.csv", gen / "documents.csv", config["year"])
    py("fetch_docs.py", gen / "documents.csv", gen / "plans.csv", f"{work}/docs", gen / "documents_checked.csv",
       config["year"], ",".join(config["counties"]), *baseline)
    py("cite.py", gen / "documents_checked.csv", f"{work}/docs/text", gen / "citations.csv")
    py("main_chart.py", gen / "plans.csv", f"{work}/pbp", gen / "main_chart.csv")
    py("dvha.py", gen / "plans.csv", f"{work}/pbp", gen / "dvha.csv")
    if config["year"] == appendix_b.YEAR:
        py("tests/make_fixture.py", f"{work}/pbp")

    pdfs(gen, work)
    py("texts.py", f"{work}/pdfs", f"{work}/texts")
    lost = lost_quotes(data, f"{work}/texts")
    if lost:
        raise SystemExit("The site cannot highlight these quotes:\n" + "\n".join(f"{layers.where(c)}: {c['quote']}" for c in lost))
    if config["year"] == years.LIVE:  # blanks.py and filled.py read the live year
        answer = Answers(data, ask.api() if mode == "api" else None)
        before = {name: len(layers.layer(data, name)) for name in (layers.BLANKS, layers.FILLED)}
        blanks_step(f"{work}/texts", work, answer)
        filled_step(f"{work}/texts", work, answer)
        for name, was in before.items():
            now = len(layers.layer(data, name))
            print(f"{'::warning::' if now < was / 2 else ''}{name} has {now} rows, and had {was}.")
    subprocess.run([sys.executable, "-I", "-m", "unittest", "discover", "-s", os.path.join(HERE, "tests")], check=True)


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
