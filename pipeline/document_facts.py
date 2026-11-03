"""Writes data/<year>/machine/document_facts.csv: the facts a version's reader states and its verifier accepts."""
import os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import extract, facts

VERSIONS = {
    # evaluate.py picked these models.
    1: dict(groups=("imaging",), reader=("claude-opus-5-5", "high"), verifier=("claude-opus-5-5", "medium")),
}
VERSIONS[3] = dict(VERSIONS[1], groups=("imaging", "ambulance"))


def fresh(path):
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path)
    return path


def step(data, texts, work, answer, version):
    """answer(task_dir, model, effort) answers every task file in task_dir."""
    v = VERSIONS[version]
    rows = []
    for group in v["groups"]:
        read, check = fresh(f"{work}/{group}/read"), fresh(f"{work}/{group}/check")
        found = f"{read}/facts.json"
        extract.read(texts, read, group, data)
        answer(read, *v["reader"])
        extract.extract_facts(texts, read, group, found, data)
        answer(read, *v["reader"])
        extract.extract_facts(texts, read, group, found, data)
        extract.verify(texts, found, check, data)
        answer(check, *v["verifier"])
        extract.accept(check, f"{check}/accepted.csv")
        rows += facts.read(f"{check}/accepted.csv")
    os.makedirs(f"{data}/machine", exist_ok=True)
    facts.write(f"{data}/machine/document_facts.csv", rows)
