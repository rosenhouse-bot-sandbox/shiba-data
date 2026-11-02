"""Writes data/<year>/machine/document_facts.csv: the facts the picked reader states and the picked verifier accepts.

Usage: python3 -I pipeline/document_facts.py <year> <work_dir> [api]
"""
import os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import extract, facts

GROUPS = ("imaging",)
# evaluate.py picked these.
READER = ("claude-opus-5-5", "high")
VERIFIER = ("claude-opus-5-5", "medium")


def fresh(path):
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path)
    return path


def step(data, texts, work, answer):
    """answer(task_dir, model, effort) answers every task file in task_dir."""
    rows = []
    for group in GROUPS:
        read, check = fresh(f"{work}/{group}/read"), fresh(f"{work}/{group}/check")
        found = f"{read}/facts.json"
        extract.read(texts, read, group, data)
        answer(read, *READER)
        extract.extract_facts(texts, read, group, found, data)
        answer(read, *READER)
        extract.extract_facts(texts, read, group, found, data)
        extract.verify(texts, found, check, data)
        answer(check, *VERIFIER)
        extract.accept(check, f"{check}/accepted.csv")
        rows += facts.read(f"{check}/accepted.csv")
    os.makedirs(f"{data}/machine", exist_ok=True)
    facts.write(f"{data}/machine/document_facts.csv", rows)


def main(year, work, mode=""):
    import ask, run, years
    data = years.data_dir(int(year))
    step(data, f"{work}/texts", f"{work}/facts", run.Answers(data, ask.api() if mode == "api" else None))


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
