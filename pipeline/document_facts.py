"""Writes data/<year>/machine/document_facts.csv: the facts a version's reader states and its verifier accepts."""
import concurrent.futures, json, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import extract, facts

VERSIONS = {
    # evaluate.py picked these models.
    1: dict(groups=("imaging",), reader=("claude-opus-5-5", "high"), verifier=("claude-opus-5-5", "medium")),
}
VERSIONS[3] = dict(VERSIONS[1], groups=("imaging", "ambulance"))
VERSIONS[4] = dict(VERSIONS[1], groups=("imaging", "ambulance", "surgery"))
# Version 6 replaced 5, whose inpatient readers had to drop day tiers: tiers differ only in `limit`, which is not
# part of a fact's identity.
VERSIONS[6] = dict(VERSIONS[4], groups=VERSIONS[4]["groups"] + ("tests", "visits", "rehab", "inpatient"))
VERSIONS[7] = dict(VERSIONS[6], groups=VERSIONS[6]["groups"] + ("giveback", "part_b_drugs", "medical_deductible", "dental", "extras"))
VERSIONS[8] = dict(VERSIONS[7], groups=tuple(g for g in VERSIONS[7]["groups"] if g != "dental"))
VERSIONS[9] = dict(VERSIONS[7], groups=VERSIONS[7]["groups"] + ("vision", "hearing", "fitness", "otc", "packages"))
# A second reader looks again at the documents of plans whose cells the first readers left short.
KAISER = ("H9003-001-0", "H9003-006-0", "H9003-009-0")
VERSIONS[10] = dict(VERSIONS[9], recheck={
    "tests": ("H2406-070-0", "H2923-009-0", "H3817-008-1", "H5439-010-0", "H5439-011-0", "H5439-015-0", "H5439-019-0",
              "H6815-038-0", "H7006-021-0"),
    "part_b_drugs": KAISER, "medical_deductible": ("H1036-317-0",), "hearing": ("H9003-009-0",),
    "surgery": KAISER + ("H3817-008-1",)})


def fresh(path):
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path)
    return path


def group_facts(texts, work, group, answer, v, data):
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
    accepted = facts.read(f"{check}/accepted.csv")
    recheck = v.get("recheck", {}).get(group)
    return accepted + (second_facts(texts, work, group, answer, v, data, recheck, accepted) if recheck else [])


def second_facts(texts, work, group, answer, v, data, plan_ids, known):
    """The facts a second reader adds for plan_ids and its verifier accepts."""
    read, check = fresh(f"{work}/{group}/reread"), fresh(f"{work}/{group}/recheck")
    found = f"{read}/facts.json"
    extract.reread(texts, read, group, plan_ids, known, data)
    for _ in range(2):
        answer(read, *v["reader"])
        extract.extract_facts(texts, read, group, found, data)
    seen = {tuple(f[c] for c in facts.IDENTITY) for f in known}
    with open(found) as f:
        new = [r for r in json.load(f) if r["plan_id"] in plan_ids and tuple(r[c] for c in facts.IDENTITY) not in seen]
    with open(found, "w") as f:
        json.dump(new, f, indent=1)
    extract.verify(texts, found, check, data)
    answer(check, *v["verifier"])
    extract.accept(check, f"{check}/accepted.csv")
    return facts.read(f"{check}/accepted.csv")


def step(data, texts, work, answer, version):
    """answer(task_dir, model, effort) answers every task file in task_dir. The groups run at the same time."""
    v = VERSIONS[version]
    with concurrent.futures.ThreadPoolExecutor(len(v["groups"])) as pool:
        found = list(pool.map(lambda group: group_facts(texts, work, group, answer, v, data), v["groups"]))
    os.makedirs(f"{data}/machine", exist_ok=True)
    facts.write(f"{data}/machine/document_facts.csv", [row for rows in found for row in rows])
