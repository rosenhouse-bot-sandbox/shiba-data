"""Writes data/<year>/machine/document_facts.csv: the facts a version's reader states and its verifier accepts."""
import concurrent.futures, json, os, pathlib, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import extract, facts, present, review

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
# It can only add facts, so cells with wrong facts are not here.
KAISER = ("H9003-001-0", "H9003-006-0", "H9003-009-0")
VERSIONS[10] = dict(VERSIONS[9], recheck={
    "tests": ("H2406-070-0", "H2923-009-0", "H3817-008-1", "H5439-010-0", "H5439-011-0", "H5439-015-0", "H5439-019-0",
              "H7006-021-0"),
    "part_b_drugs": KAISER, "hearing": ("H9003-009-0",),
    "surgery": KAISER + ("H3817-008-1",)})
# A reviewer checks each untrusted fact that a cell cites (review.py). The cap stops a run that would ask about too many.
VERSIONS[11] = dict(VERSIONS[10], reviewer=("claude-opus-5-5", "high"), review_cap=100)
VERSIONS[12] = dict(VERSIONS[11], groups=VERSIONS[11]["groups"] + ("plan_premium", "emergency", "foot_care", "meals",
                                                             "other_supplemental"))


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


# The second reader's verifier skips a fact that passed the code checks for one of these reasons.
FOUND_BEFORE, NOT_RECHECKED = "an earlier reader found the same fact", "the second reader does not recheck its plan"


def second_facts(texts, work, group, answer, v, data, plan_ids, known):
    """The facts a second reader adds for plan_ids and its verifier accepts."""
    read, check = fresh(f"{work}/{group}/reread"), fresh(f"{work}/{group}/recheck")
    found = f"{read}/facts.json"
    extract.reread(texts, read, group, plan_ids, known, data)
    for _ in range(2):
        answer(read, *v["reader"])
        extract.extract_facts(texts, read, group, found, data)
    seen = {tuple(f[c] for c in facts.KEY) for f in known}

    def skipped(r):
        return NOT_RECHECKED if r["plan_id"] not in plan_ids else FOUND_BEFORE if tuple(r[c] for c in facts.KEY) in seen else None
    with open(found) as f:
        stated = json.load(f)
    with open(found, "w") as f:
        json.dump([r for r in stated if not skipped(r)], f, indent=1)
    why = {facts.identity(r): skipped(r) for r in stated if skipped(r)}
    with open(f"{read}/{extract.OUTCOMES}") as f:
        outcomes = json.load(f)
    extract.write_outcomes(read, [dict(o, skipped=why[tuple(o["fact"][c] for c in facts.IDENTITY)])
                                  if o["fact"] and tuple(o["fact"][c] for c in facts.IDENTITY) in why else o for o in outcomes])
    extract.verify(texts, found, check, data, known)
    answer(check, *v["verifier"])
    extract.accept(check, f"{check}/accepted.csv")
    return facts.read(f"{check}/accepted.csv")


def step(data, texts, work, answer, version, reviewed=True, present_version=None):
    """answer(task_dir, model, effort) answers every task file in task_dir. The groups run at the same time.
    reviewed=False skips the version's reviewer. The reviewer sees the cells that present_version presents."""
    v = VERSIONS[version]
    shutil.rmtree(work, ignore_errors=True)
    with concurrent.futures.ThreadPoolExecutor(len(v["groups"])) as pool:
        found = list(pool.map(lambda group: group_facts(texts, work, group, answer, v, data), v["groups"]))
    rows = [row for rows in found for row in rows]
    data = pathlib.Path(data)
    path = data / "machine/document_facts.csv"
    os.makedirs(data / "machine", exist_ok=True)
    if reviewed and "reviewer" in v:
        old = facts.read(path) if path.exists() else []
        held = present.held(data, present_version)
        rows, trusted = review.gate(data, texts, work, answer, review.trusted(data, old, held), rows, v, held)
        facts.write(str(data / review.REVIEWED), trusted)
    facts.write(str(path), rows)
