"""Rebuilds data/<year>/generated from the sources in data/<year>/config.json, found.csv and links.csv,
then the live year's machine/document_facts.csv, sheets and generated/presented.csv.

Usage: python3 -I pipeline/run.py <year> <work_dir> [api|replay] [<step>@<version>[,...]]

Saved answers in data/<year>/answers are reused. Without `api`, the run stops at the first model step
with tasks that have no saved answer, and lists them. With `api`, the Claude API answers them.
Each <step>@<version> candidate runs in place of that step's pinned version (see steps.py).
`replay` reads nothing from the web. It needs the committed run's PDFs, texts and CMS zips in <work_dir>,
where blobs.py names them, and keeps the committed documents_checked.csv.
Needs pypdfium2, poppler's pdftotext and `npm ci` here, and the anthropic package for `api`.
"""
import csv
import glob
import os
import pathlib
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "tests")]
import appendix_b  # noqa: E402
import ask  # noqa: E402
import blobs  # noqa: E402
import document_facts  # noqa: E402
import eoc  # noqa: E402
import fetch_docs  # noqa: E402
import sheets  # noqa: E402
import present  # noqa: E402
import reach  # noqa: E402
import steps  # noqa: E402
import store  # noqa: E402
import years  # noqa: E402

CMS = ("landscape", "pbp")
FACTS = "machine/document_facts.csv"
STEPS = {"document_facts": document_facts.VERSIONS, "present": present.VERSIONS}


def get(url, path):
    if not (os.path.exists(path) and os.path.getsize(path)):
        subprocess.run(["curl", "-sS", "-L", "--fail", "--retry", "5", "--retry-all-errors", "--max-time", "900", "-A", "Mozilla/5.0", "-o", path, url],
                       check=True)


def py(script, *args):
    subprocess.run([sys.executable, "-I", os.path.join(HERE, script), *map(str, args)], check=True)


def pdfs(gen, work):
    """Links each fetched PDF as <work>/pdfs/<document id>.pdf, the name texts.py and the site use."""
    os.makedirs(f"{work}/pdfs", exist_ok=True)
    with open(gen / "documents_checked.csv") as f:
        for d in csv.DictReader(f):
            if d["sha256"]:
                src = fetch_docs.cached_pdf(f"{work}/docs", d["url"])
                dst = blobs.pdf_path(work, d["sha256"])
                if not os.path.exists(dst):
                    os.link(src, dst)


def reuse_checked(gen, work):
    """Links each checked PDF where fetch_docs.py looks for its download."""
    os.makedirs(f"{work}/docs/pdf", exist_ok=True)
    with open(pathlib.Path(gen, "documents_checked.csv")) as f:
        for d in csv.DictReader(f):
            src, dst = blobs.pdf_path(work, d["sha256"]), fetch_docs.cached_pdf(f"{work}/docs", d["url"])
            if not d["sha256"] or os.path.exists(dst):
                continue
            if not src.exists():
                raise SystemExit(f"A candidate run needs the checked PDFs in {work}/pdfs, such as {src.name}.")
            os.link(src, dst)


def lost_quotes(data, texts, skip=frozenset()):
    """Citations whose quote the site cannot highlight on its page, but for those of the skipped URLs."""
    with open(data / "generated" / "documents_checked.csv") as f:
        doc = {d["url"]: d["sha256"][:16] for d in csv.DictReader(f)}
    cites = [dict(c, doc=doc[c["url"]], page=c["pdf_page"]) for c in sheets.rows(data / sheets.PRESENTED)
             if c["quote"].strip() and c["url"] in doc and c["url"] not in skip]
    if failed := sorted({c["url"] for c in cites if not c["doc"]}):
        raise SystemExit("These cited documents did not download:\n" + "\n".join(failed))
    return [c for c, found in zip(cites, eoc.highlights(texts, cites, "found")) if not found]


def checked(gen):
    """Each checked URL's sha256."""
    path = pathlib.Path(gen, "documents_checked.csv")
    if not path.exists():
        return {}
    with open(path) as f:
        return {d["url"]: d["sha256"] for d in csv.DictReader(f) if d["sha256"]}


def replaced(before, after):
    """The URLs whose PDF changed."""
    return {url for url, sha in before.items() if after.get(url, sha) != sha}


def check_quotes(data, texts, skip=frozenset()):
    lost = lost_quotes(data, texts, skip)
    if lost:
        raise SystemExit("The site cannot highlight these quotes:\n" + "\n".join(f"{sheets.where(c)}: {c['quote']}" for c in lost))


LEDGER_COLUMNS = ["dir", "task", "model", "effort", "key", "prompt"]


class Answers:
    """Answers each model step's task files from saved answers, or from the asker.
    With a work dir, it also keeps each task's text as <work>/prompts/<sha256>, and lists the task in <work>/ledger.csv."""

    def __init__(self, data, asker, work=None, saved=None):
        self.saved, self.asker, self.work = saved or data / "answers", asker, work
        self.lock = threading.Lock()  # document_facts runs its groups at once

    def __call__(self, task_dir, model, effort=None):
        tasks = sorted(glob.glob(f"{task_dir}/*.md"))
        if self.work:
            with self.lock:
                self.record(task_dir, tasks, model, effort)
        missing = ask.answer(tasks, model, self.saved, self.asker, effort)
        if missing:
            print("\n".join(missing))
            raise SystemExit(f"{len(missing)} of {len(tasks)} tasks in {task_dir} have no answer from {model}. "
                             + ("Rerun to ask again." if self.asker else "Rerun with `api` to ask the Claude API."))


    def record(self, task_dir, tasks, model, effort):
        os.makedirs(f"{self.work}/{blobs.PROMPTS}", exist_ok=True)
        new = not os.path.exists(f"{self.work}/{blobs.LEDGER}")
        with open(f"{self.work}/{blobs.LEDGER}", "a", newline="") as f:
            w = csv.DictWriter(f, LEDGER_COLUMNS, lineterminator="\n")
            if new:
                w.writeheader()
            for task in tasks:
                with open(task) as t:  # as ask.answer reads it
                    text = t.read()
                prompt = ask.sha(text)
                with open(f"{self.work}/{blobs.PROMPTS}/{prompt}", "wb") as out:
                    out.write(text.encode())
                w.writerow(dict(dir=os.path.relpath(task_dir, self.work), task=os.path.basename(task), model=model,
                                effort=effort or "", key=ask.key(model, text, effort), prompt=prompt))


def asker(mode, data, work, versions, candidate):
    """The Claude API in `api` mode. A document_facts candidate may ask only about its version's targets."""
    if mode != "api":
        return None
    if "document_facts@" not in candidate:
        return ask.api()
    return reach.Guard(ask.api(), data, work, STEPS["document_facts"][versions["document_facts"]])


def model_steps(data, texts, work, answer, versions):
    document_facts.step(data, texts, f"{work}/facts", answer, versions["document_facts"], present_version=versions["present"])
    present.write(data, versions["present"])


def run_tests(kind, candidate):
    """Runs the code tests or the checks of built data (see built.py)."""
    subprocess.run([sys.executable, "-I", os.path.join(HERE, "built.py"), kind], check=True,
                   env=dict(os.environ, **{present.CANDIDATE: candidate}))


def cms_tables(data, config, work):
    """Writes the tables that the CMS zips in work, found.csv and links.csv give."""
    gen = data / "generated"
    subprocess.run(["unzip", "-oq", blobs.cms_path(work, "landscape"), "-d", work], check=True)
    subprocess.run(["unzip", "-oq", blobs.cms_path(work, "pbp"), "-d", f"{work}/pbp"], check=True)
    py("universe.py", f"{work}/{config['landscape_csv']}", gen / "plans.csv", gen / "landscape_reads.csv", config["state"],
       *config["counties"])
    py("find_docs.py", gen / "plans.csv", data / "found.csv", data / "links.csv", gen / "documents.csv", config["year"])
    py("pbp_facts.py", gen / "plans.csv", gen / "landscape_reads.csv", f"{work}/pbp", gen / "pbp_facts.csv")
    py("cms_sources.py", f"{work}/{config['landscape_csv']}", gen / "plans.csv", f"{work}/pbp", gen / "cms_sources.csv",
       config["state"])


def main(year, work, mode="", candidate=""):
    if mode not in ("", "api", "replay"):
        raise SystemExit(__doc__)
    data = years.data_dir(year)
    config = years.config(data)
    if candidate and config["year"] != years.LIVE:
        raise SystemExit(f"Only the live year, {years.LIVE}, runs model steps.")
    run_tests("code", candidate)
    work = os.path.abspath(work)
    os.makedirs(work, exist_ok=True)
    web = mode != "replay"
    gen = data / "generated"
    os.makedirs(gen, exist_ok=True)
    if web:
        for name in CMS:
            get(config[f"{name}_zip"], blobs.cms_path(work, name))
    blobs.record_cms(CMS, work, gen / blobs.CMS_FILES)
    cms_tables(data, config, work)
    live = config["year"] == years.LIVE
    earlier = live and (data / FACTS).exists()
    if live:
        versions = steps.versions(data, STEPS, candidate)
    # present.write finds each fact's URL in documents_checked.csv, so it runs before fetch_docs.py rewrites that file.
    if earlier:
        present.write(data, versions["present"])
    before = checked(gen)
    if web:
        # A candidate run changes only what its version changes, so it keeps the documents earlier runs checked.
        if candidate:
            reuse_checked(gen, work)
        py("fetch_docs.py", gen / "documents.csv", gen / "plans.csv", f"{work}/docs", gen / "documents_checked.csv",
           config["year"], ",".join(config["counties"]))
        pdfs(gen, work)
    py("texts.py", f"{work}/pdfs", f"{work}/texts")
    blobs.record_texts(gen, work)
    if config["year"] == appendix_b.YEAR:
        py("tests/make_fixture.py", f"{work}/pbp")

    if live:
        # The new texts must highlight the quotes the earlier facts give, before any model call. A replaced document
        # gets new facts.
        if earlier:
            check_quotes(data, f"{work}/texts", replaced(before, checked(gen)))
        store.pull(data, work)
        answer = Answers(data, asker(mode, data, work, versions, candidate), work)
        model_steps(data, f"{work}/texts", work, answer, versions)
        check_quotes(data, f"{work}/texts")
        # A candidate's pin PR checks its data.
        if not candidate:
            run_tests("checks", candidate)


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4, 5):
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
