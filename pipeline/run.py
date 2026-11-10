"""Rebuilds data/<year>/generated from the sources in data/<year>/config.json, found.csv and links.csv,
then the live year's machine/document_facts.csv and generated/presented.csv.

Usage: python3 -I pipeline/run.py <year> <work_dir> [api|replay] [<step>@<version>[,...]]

Saved answers in data/<year>/answers are reused. Without `api`, the run stops at the first model step
with tasks that have no saved answer, and lists them. With `api`, the Claude API answers them.
Each <step>@<version> candidate runs in place of that step's pinned version (see steps.py).
`replay` reads nothing from the web. It needs the committed run's PDFs, texts and CMS zips in <work_dir>,
where blobs.py names them, and keeps the committed documents lists.
Needs pypdfium2, poppler's pdftotext and `npm ci` here, and the anthropic package for `api`.
"""
import csv
import glob
import hashlib
import os
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
import layers  # noqa: E402
import present  # noqa: E402
import steps  # noqa: E402
import years  # noqa: E402

CMS = ("landscape", "pbp")
STEPS = {"document_facts": document_facts.VERSIONS, "present": present.VERSIONS}


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
                dst = blobs.pdf_path(work, d["sha256"])
                if not os.path.exists(dst):
                    os.link(src, dst)


def lost_quotes(data, texts):
    """Layer rows whose quote the site cannot highlight on its page."""
    with open(data / "generated" / "documents_checked.csv") as f:
        doc = {d["url"]: d["sha256"][:16] for d in csv.DictReader(f)}
    cites = [dict(c, doc=doc[c["url"]], page=c["pdf_page"]) for name in layers.LAYERS for c in layers.layer(data, name)
             if c["quote"].strip() and c["url"] in doc]
    return [c for c, found in zip(cites, eoc.highlights(texts, cites, "found")) if not found]


def check_quotes(data, texts):
    lost = lost_quotes(data, texts)
    if lost:
        raise SystemExit("The site cannot highlight these quotes:\n" + "\n".join(f"{layers.where(c)}: {c['quote']}" for c in lost))


LEDGER_COLUMNS = ["dir", "task", "model", "effort", "key", "prompt"]


class Answers:
    """Answers each model step's task files from saved answers, or from the asker.
    With a work dir, it also keeps each task's text as <work>/prompts/<sha256>, and lists the task in <work>/ledger.csv."""

    def __init__(self, data, asker, work=None):
        self.saved, self.asker, self.work = data / "answers", asker, work
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


def model_steps(data, texts, work, answer, versions):
    document_facts.step(data, texts, f"{work}/facts", answer, versions["document_facts"], present_version=versions["present"])
    present.write(data, versions["present"])


def unit_tests(candidate):
    subprocess.run([sys.executable, "-I", "-m", "unittest", "discover", "-s", os.path.join(HERE, "tests")], check=True,
                   env=dict(os.environ, **{present.CANDIDATE: candidate}))


def main(year, work, mode="", candidate=""):
    if mode not in ("", "api", "replay"):
        raise SystemExit(__doc__)
    data = years.data_dir(year)
    config = years.config(data)
    if candidate and config["year"] != years.LIVE:
        raise SystemExit(f"Only the live year, {years.LIVE}, runs model steps.")
    unit_tests(candidate)
    work = os.path.abspath(work)
    os.makedirs(work, exist_ok=True)
    web = mode != "replay"
    for name in CMS:
        if web:
            get(config[f"{name}_zip"], blobs.cms_path(work, name))
    subprocess.run(["unzip", "-oq", blobs.cms_path(work, "landscape"), "-d", work], check=True)
    subprocess.run(["unzip", "-oq", blobs.cms_path(work, "pbp"), "-d", f"{work}/pbp"], check=True)

    gen = data / "generated"
    os.makedirs(gen, exist_ok=True)
    blobs.record_cms(CMS, work, gen / blobs.CMS_FILES)
    py("universe.py", f"{work}/{config['landscape_csv']}", gen / "plans.csv", gen / "landscape_reads.csv", config["state"],
       *config["counties"])
    baseline = [years.REPO / config["baseline_manifest"]] if "baseline_manifest" in config else []
    if web:
        py("find_docs.py", gen / "plans.csv", data / "found.csv", data / "links.csv", gen / "documents.csv",
           config["year"])
        py("fetch_docs.py", gen / "documents.csv", gen / "plans.csv", f"{work}/docs", gen / "documents_checked.csv",
           config["year"], ",".join(config["counties"]), *baseline)
        pdfs(gen, work)
    py("texts.py", f"{work}/pdfs", f"{work}/texts")
    blobs.record_texts(gen, work)
    py("cite.py", gen / "documents_checked.csv", f"{work}/texts/text", gen / "citations.csv")
    py("main_chart.py", gen / "plans.csv", f"{work}/pbp", gen / "main_chart.csv", gen / "cms_reads.csv")
    py("pbp_facts.py", gen / "plans.csv", gen / "landscape_reads.csv", f"{work}/pbp", gen / "pbp_facts.csv",
       config["part_b_deductible"])
    py("dvha.py", gen / "plans.csv", f"{work}/pbp", gen / "dvha.csv", gen / "dvha_reads.csv")
    py("cms_sources.py", f"{work}/{config['landscape_csv']}", gen / "plans.csv", f"{work}/pbp", gen / "cms_sources.csv",
       config["state"])
    if config["year"] == appendix_b.YEAR:
        py("tests/make_fixture.py", f"{work}/pbp")

    check_quotes(data, f"{work}/texts")
    if config["year"] == years.LIVE:
        versions = steps.versions(data, STEPS, candidate)
        answer = Answers(data, ask.api() if mode == "api" else None, work)
        model_steps(data, f"{work}/texts", work, answer, versions)
        check_quotes(data, f"{work}/texts")


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4, 5):
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
