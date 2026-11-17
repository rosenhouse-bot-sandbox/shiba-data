"""Writes data/<year>/machine/document_facts.csv: the facts a version's reader states and its verifier accepts."""
import concurrent.futures, json, os, pathlib, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import extract, facts, review

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


def zero(v):
    return v.get("zero_groups", extract.ZERO_GROUPS)


def merging(v, group):
    if group in v.get("merge_prices", ()):
        return "prices"
    return "limits" if group in v.get("merge_limits", ()) else v.get("merge", False)


def group_facts(texts, work, group, answer, v, data):
    read, check = fresh(f"{work}/{group}/read"), fresh(f"{work}/{group}/check")
    found = f"{read}/facts.json"
    notes, find, plan_notes = v.get("notes", {}), v.get("find", {}).get(group, ()), v.get("plan_notes", {})
    extract.read(texts, read, group, data, notes=notes, find=find, plan_notes=plan_notes)
    for _ in range(2):
        answer(read, *v["reader"])
        extract.extract_facts(texts, read, group, found, data, merging(v, group), notes, zero=zero(v), find=find,
                              plan_notes=plan_notes)
    extract.verify(texts, found, check, data, notes=review.checker_notes(v), after=v.get("check_after", {}),
                   before=v.get("check_before", {}), plan_notes=plan_notes)
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
    notes = review.joined(v.get("notes", {}), v.get("recheck_notes", {}))
    plan_notes = review.plan_notes(v)
    after, find = v.get("recheck_plan_after", {}).get(group, {}), v.get("find", {}).get(group, ())
    extract.reread(texts, read, group, plan_ids, known, data, notes, plan_notes, after, find)
    for _ in range(2):
        answer(read, *v["reader"])
        extract.extract_facts(texts, read, group, found, data, merging(v, group), notes, zero=zero(v), plan_notes=plan_notes,
                              plan_after=after, reimburses=v.get("recheck_reimburses", ()), find=find)
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
    extract.verify(texts, found, check, data, known, notes=review.second_notes(v), after=v.get("check_after", {}),
                   before=v.get("check_before", {}), plan_notes=plan_notes)
    answer(check, *v["verifier"])
    extract.accept(check, f"{check}/accepted.csv")
    return facts.read(f"{check}/accepted.csv")


def inherited(texts, work, group, answer, v, data):
    """The group's facts: those of the version it inherits, and its own whose identity that version lacks.
    A group the version reads fresh inherits nothing."""
    own = group_facts(texts, work, group, answer, v, data)
    parent = VERSIONS.get(v.get("inherits"))
    if not parent or group not in parent["groups"] or group in v.get("fresh", ()):
        return own
    if "inherits" in parent:
        raise ValueError("A version cannot inherit a version that inherits.")
    rows = group_facts(texts, f"{work}/inherited", group, answer, parent, data)
    ids = {facts.identity(r) for r in rows}
    return rows + [r for r in own if facts.identity(r) not in ids]


def step(data, texts, work, answer, version, reviewed=True, present_version=None):
    """answer(task_dir, model, effort) answers every task file in task_dir. The groups run at the same time.
    reviewed=False skips the version's reviewer. The reviewer sees the cells that present_version presents."""
    v = VERSIONS[version]
    shutil.rmtree(work, ignore_errors=True)
    with concurrent.futures.ThreadPoolExecutor(len(v["groups"])) as pool:
        found = list(pool.map(lambda group: inherited(texts, work, group, answer, v, data), v["groups"]))
    rows = [row for rows in found for row in rows]
    data = pathlib.Path(data)
    path = data / "machine/document_facts.csv"
    os.makedirs(data / "machine", exist_ok=True)
    if reviewed and "reviewer" in v:
        old = facts.read(path) if path.exists() else []
        trusted = review.trusted(data, old, present_version)
        rows, trusted = review.gate(data, texts, work, answer, trusted, rows, v, present_version)
        facts.write(str(data / review.REVIEWED), trusted)
    facts.write(str(path), rows)
VERSIONS[13] = dict(VERSIONS[12], review_cap=200, recheck=VERSIONS[12]["recheck"] | {
    "dental": ("H3805-041-0", "H2406-042-0", "H1372-003-0", "H2406-073-0", "H7199-002-0", "H2923-025-0", "H1036-153-0",
               "H1036-306-0", "H1036-317-0", "H5216-427-2", "H5216-455-0"),
    "emergency": ("H7006-018-0", "H7006-021-0"), "meals": ("H1036-306-0",),
    "other_supplemental": ("H1036-323-0", "H1036-317-0", "H5216-455-0")})
HEARING_EXAM = ("H7006-018-0", "H6815-038-0", "H5439-019-0", "H5439-011-0", "H1372-003-0", "H7006-021-0", "H5439-010-0",
                "H7199-002-0", "H2923-001-0", "H2923-028-3", "H2923-025-0", "H2923-005-0", "H2923-009-0", "H2923-019-0")
VERSIONS[14] = dict(VERSIONS[13], recheck=VERSIONS[13]["recheck"] | {"hearing": VERSIONS[13]["recheck"]["hearing"] + HEARING_EXAM})
# Readers often state one fact twice on a page, once per quote. Version 15 merges such answers instead of dropping both.
VERSIONS[15] = dict(VERSIONS[14], merge=True)
# Version 16 reads the costs that only CMS facts gave, so the sheets can cite them.
VERSIONS[16] = dict(VERSIONS[15], groups=VERSIONS[15]["groups"] + ("moop", "part_d_deductible"))
# Verifiers rejected true facts whose network another page gave, and readers took urgent care for emergency care.
# Its notes change every dental and emergency prompt, so more facts need review.
VERSIONS[17] = dict(VERSIONS[16], review_cap=250, notes={
    "dental": "A dental chart row that names no network gives in-network costs, even when another page says members "
              "may see any dentist.",
    "emergency": "Care outside the U.S. has `network` `any`, even under a network heading. A cost only for urgently "
                 "needed care, as at an urgent care center, has the page's name for that care as its `condition`, such "
                 "as `urgently needed services`. A cost for both emergency and urgently needed care has none."})
# Version 18 merges dental prices whose limits differ, as when a page prices each service with its own limit.
# It tells dental checkers that reimbursement gives coinsurance and that an any-provider allowance has network any.
VERSIONS[18] = dict(VERSIONS[17], merge_limits=("dental",), check_notes={
    "dental": "A page that says the plan reimburses a percent of a cost gives the member the rest as `coinsurance`: 50% "
              "reimbursement is 50% coinsurance. A cost under an allowance that members may use with any licensed "
              "provider may have `network` `any`, though its row names no network."})
# A dental price list can go on past its page, so version 19 shows dental checkers the next page too.
VERSIONS[19] = dict(VERSIONS[18], check_after={"dental": 1})
# Version 20 takes a second look at the cells readers left short. Part D deductibles and plan premiums may be $0 in words.
# Hearing checkers see the page before, where a price's row can start.
VERSIONS[20] = dict(VERSIONS[19], zero_groups=extract.ZERO_GROUPS + ("part_d_deductible", "plan_premium"),
                    check_before={"hearing": 1}, recheck=VERSIONS[19]["recheck"] | {
                        "plan_premium": ("H3817-010-0",), "emergency": VERSIONS[19]["recheck"]["emergency"] + ("H5439-019-0",)},
                    recheck_notes={
    "plan_premium": "When a page says in words that the member pays no plan premium, quote those words.",
    "emergency": "A page that says the plan covers emergency care worldwide gives a `covered` fact with `setting` "
                 "`outside_us`.",
    "tests": "A dedicated or independent testing laboratory is `freestanding`.",
    "surgery": "A price for outpatient surgery that names no place has `setting` `any`."})
# Version 21 rechecks ambulance prices for Kaiser members in a home treatment plan. Its recheck notes say that care
# abroad is supplemental, that a unit keeps the page's words, and that rows with one price may share a fact.
VERSIONS[21] = dict(VERSIONS[20], recheck=VERSIONS[20]["recheck"] | {
    "ambulance": ("H9003-001-0", "H9003-006-0", "H9003-009-0")}, recheck_notes=VERSIONS[20]["recheck_notes"] | {
    "ambulance": "A price for members in a home treatment plan has that plan in `condition`.",
    "emergency": VERSIONS[20]["recheck_notes"]["emergency"] + " Care outside the U.S. has `covered_by` `supplemental`.",
    "tests": VERSIONS[20]["recheck_notes"]["tests"] + " A `unit` keeps the page's words, such as `per provider per day`.",
    "hearing": "Rows that give the same price may share one fact, whatever each row's visit limit."})
KAISER_HEARING = ("A price list can continue across a page break. `$0 for Value plan members` at the top of page 65 "
                  "ends page 64's list of routine hearing exam prices. The Value plan and the Value Lane plan are "
                  "different plans.")
# Version 22 says that a hearing price list can continue across a page break, as in Kaiser's EOC.
VERSIONS[22] = dict(VERSIONS[21], recheck_notes=VERSIONS[21]["recheck_notes"] | {
    "hearing": VERSIONS[21]["recheck_notes"]["hearing"] + " " + KAISER_HEARING})
# Version 23 gives 22's note only to tasks about Kaiser's Value plan, since 22 moved other plans' prices.
VERSIONS[23] = dict(VERSIONS[21], recheck_plan_notes={"hearing": {"H9003-009-0": KAISER_HEARING}},
                    targets={"hearing": ("H9003-009-0",)})
# Version 24 merges hearing, dental and vision prices that differ only in unit or limit, instead of dropping both.
# It keeps version 23's facts. A merge changes the retry and verifier tasks of the merged prices' documents, so their
# new answers can add other facts of those documents too.
# Its targets are the plans whose tasks a dry run (blast.py) found it asks about.
VERSIONS[24] = dict(VERSIONS[23], inherits=23, merge_prices=("hearing", "dental", "vision"), targets={
    "dental": ("H1036-317-0", "H5439-011-0", "H5439-015-0", "H5439-019-0", "H6815-038-0"),
    "hearing": HEARING_EXAM + ("H5439-015-0",),
    "vision": ("H2056-003-0", "H2056-018-0", "H2406-042-0", "H3805-048-0", "H5439-011-0", "H6815-038-0", "H7006-018-0")})
# Humana dental code tables price comprehensive codes at one rate, but a few codes at 0%.
CODE_TABLE = ("Pages {pages} give the dental code table. In-network, most comprehensive codes cost {most}, and some, such "
              "as recementation and root canal retreatment, cost 0%. Prices that differ by code are one "
              "`dental.comprehensive` fact with amount `0% or {most}`. Page {both} has rows at both prices.")
# Version 25 adds the comprehensive dental prices that two Humana code tables give, and Devoted's preventive dental price.
# It keeps version 23's facts.
VERSIONS[25] = dict(VERSIONS[24], recheck_plan_notes=VERSIONS[24]["recheck_plan_notes"] | {"dental": {
    "H1036-306-0": CODE_TABLE.format(pages="78 to 80", most="50%", both="79"),
    "H5216-427-2": CODE_TABLE.format(pages="72 to 75", most="30%", both="74"),
    "H7199-002-0": "Page 63 says members get 100% reimbursement for covered preventive services, which is "
                   "`dental.preventive` coinsurance 0%."}},
    targets={"dental": ("H1036-306-0", "H5216-427-2", "H7199-002-0")})
# Version 26 shows the second dental readers of those plans the pages after each dental page, where Humana's code tables
# go on without saying "dental". Their code check takes "100% reimbursement" as 0% coinsurance.
VERSIONS[26] = dict(VERSIONS[25], recheck_plan_after={"dental": {"H1036-306-0": 2, "H5216-427-2": 3}},
                    recheck_reimburses=("dental",))
# Version 27 asks readers to name every tier a drug deductible skips. Readers assumed five tiers and left out tier 6.
EVERY_TIER = ("Name every tier the deductible skips, including tier 6 or higher when the plan has them, "
              "such as `not tiers 1,2,6`.")
PART_D_PLANS = (
    "H1036-153-0", "H1036-306-0", "H1036-317-0", "H1036-323-0", "H1372-003-0", "H2001-045-0",
    "H2056-003-0", "H2406-042-0", "H2406-070-0", "H2923-001-0", "H2923-005-0", "H2923-009-0",
    "H2923-019-0", "H2923-025-0", "H2923-028-3", "H3805-040-0", "H3805-041-0", "H3805-048-0",
    "H3817-008-1", "H3817-009-1", "H3817-011-1", "H5216-048-0", "H5216-428-2", "H5439-011-0",
    "H5439-015-0", "H5439-019-0", "H6815-038-0", "H7006-018-0", "H7199-002-0", "H9003-001-0",
    "H9003-006-0", "H9003-009-0")
# Its targets are the plans a dry run (blast.py) found it asks about: every plan with Part D.
VERSIONS[27] = dict(VERSIONS[26], notes=VERSIONS[26]["notes"] | {"part_d_deductible": EVERY_TIER},
                    targets={"part_d_deductible": PART_D_PLANS})
# Version 28 also shows those readers the pages that name tier 6, which rarely mention the deductible.
# Its checkers see the page after the cited one, where those plans name tier 6.
# It reads drug deductibles fresh, since version 23's tier lists leave out tier 6.
VERSIONS[28] = dict(VERSIONS[27], find={"part_d_deductible": (r"\btier 6\s*[-–—(]",)},
                    check_after=VERSIONS[27]["check_after"] | {"part_d_deductible": 1}, fresh=("part_d_deductible",))
WELLCARE_EKG = ("In the Evidence of Coverage, page 83's row for diagnostic non-laboratory tests such as CT scans, MRIs, "
                "EKGs and PET scans gives imaging prices, so it gives no `tests` fact. Its $200 in other settings is the "
                "imaging price outside a hospital. Page 84's row for other outpatient diagnostic tests gives the "
                "`tests.diagnostic` coinsurance.")
# Version 29 tells every tests reader of one Wellcare plan that its EKG row prices imaging, as other Wellcare plans read it.
# It reads tests fresh, since version 23 took that row's $200 for tests.
VERSIONS[29] = dict(VERSIONS[28], plan_notes={"tests": {"H6815-038-0": WELLCARE_EKG}},
                    fresh=VERSIONS[28]["fresh"] + ("tests",), targets={"tests": ("H6815-038-0",)})
SPIROMETRY = ("In the Evidence of Coverage, the spirometry row prices a diagnostic test: it gives a `tests.diagnostic` "
              "coinsurance fact with `condition` `Spirometry` for each network it prices.")
# Version 30 adds prices that readers missed: two plans' comprehensive dental and three Wellcare plans' spirometry,
# which other Wellcare plans read.
VERSIONS[30] = dict(VERSIONS[29], recheck_plan_notes=VERSIONS[29]["recheck_plan_notes"] | {"dental": VERSIONS[29][
    "recheck_plan_notes"]["dental"] | {
    "H5216-455-0": "Pages 71 to 75 give the dental code table. Every code under `Comprehensive Services`, such as "
                   "fillings, extractions and crowns, costs 0% in-network and out-of-network: a `dental.comprehensive` "
                   "coinsurance 0% fact for each network.",
    "H1372-003-0": "The Summary of Benefits row for preventive and comprehensive dental services gives `$0 copay for:`, "
                   "and page 57 of the Evidence of Coverage says there is no coinsurance or copayment for supplemental "
                   "dental benefits, including the comprehensive services on page 58. So the Summary's row also gives a "
                   "`dental.comprehensive` copay $0 fact."}},
    recheck_plan_after={"dental": VERSIONS[29]["recheck_plan_after"]["dental"] | {"H5216-455-0": 3}},
    plan_notes={"tests": {"H6815-038-0": WELLCARE_EKG + " " + SPIROMETRY, "H5439-019-0": SPIROMETRY,
                          "H5439-010-0": SPIROMETRY}},
    targets={"dental": ("H5216-455-0", "H1372-003-0"), "tests": ("H6815-038-0", "H5439-019-0", "H5439-010-0")})
# Version 31 adds the in-network price for other tests that one Wellcare reader missed in version 30.
# It keeps version 30's targets, since version 30 is not pinned.
VERSIONS[31] = dict(VERSIONS[30], plan_notes={"tests": VERSIONS[30]["plan_notes"]["tests"] | {
    "H5439-019-0": SPIROMETRY + " Page 92's in-network column also gives `20% coinsurance for all other Medicare-covered "
                   "services`: a `tests.diagnostic` coinsurance 20% fact with no `condition`."}})
