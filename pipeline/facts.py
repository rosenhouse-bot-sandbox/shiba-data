"""Benefit facts: one cost or coverage term that a document or a CMS file states for one plan.

A row is identified by fact_id, source, doc_sha and page.
"""
import csv, hashlib, json, os, re

COLUMNS = ("fact_id", "plan_id", "benefit", "setting", "network", "provider_tier", "condition", "package", "pool",
           "covered_by", "cost_kind", "amount", "unit", "limit", "source", "doc_sha", "page", "quotes", "note")
KEY = COLUMNS[1:11]
IDENTITY = ("fact_id", "source", "doc_sha", "page")

BENEFITS = {
    "imaging": "Outpatient X-rays and diagnostic radiology, priced together",
    "imaging.xray": "Outpatient X-rays",
    "imaging.diagnostic": "Diagnostic radiology services other than X-rays, priced together",
    "imaging.diagnostic.advanced": "CT, MRI and PET scans, priced together",
    "imaging.diagnostic.advanced.ct": "CT (CAT) scans",
    "imaging.diagnostic.advanced.mri": "MRI and MRA",
    "imaging.diagnostic.advanced.pet": "PET scans",
    "imaging.diagnostic.advanced.other": "Advanced imaging the document does not name, such as \"all other advanced imaging\"",
    "imaging.diagnostic.nuclear": "Nuclear medicine",
    "imaging.diagnostic.ultrasound": "Ultrasounds",
    "imaging.diagnostic.mammogram": "Diagnostic mammograms, not screening mammograms",
    "radiation_therapy": "Therapeutic radiology (radiation therapy)",
    "ambulance": "Ambulance services, ground and air, priced together",
    "ambulance.ground": "Ground ambulance",
    "ambulance.air": "Air ambulance, by airplane or helicopter",
    "surgery": "Outpatient surgery and procedures, priced together",
    "surgery.colonoscopy": "Diagnostic colonoscopies, not screening colonoscopies",
    "surgery.skin_biopsy": "Skin biopsies",
    "tests": "Outpatient diagnostic tests and lab services, priced together",
    "tests.diagnostic": "Non-radiological diagnostic tests and procedures, such as EKGs and stress tests",
    "tests.diagnostic.sleep_study": "Sleep studies, in a facility or at home",
    "tests.lab": "Outpatient lab services and lab tests, such as HbA1c tests",
    "tests.genetic": "Genetic and molecular diagnostic testing",
    "visits": "Office visits to a primary care provider or specialist (physician/practitioner services). Not preventive "
              "or wellness visits, hearing exams, remote patient monitoring, mental health, podiatry, chiropractic, "
              "vision, or other health care professionals. A visit in a nursing home or at home has that `condition`",
    "rehab": "Outpatient physical, occupational and speech therapy, priced together. Not cardiac or pulmonary rehabilitation",
    "rehab.physical": "Physical therapy",
    "rehab.occupational": "Occupational therapy",
    "rehab.speech": "Speech-language therapy",
    "rehab.reevaluation": "Therapy re-evaluations, priced apart from visits",
    "inpatient": "Inpatient hospital stays of every kind, priced together",
    "inpatient.acute": "Inpatient hospital care, which may include rehabilitation and long-term care hospitals. "
                       "A cost for some days of a stay has `unit` `per day` and the days in both `limit` and `condition`, "
                       "as `days 1-5`, or `days 6+` from day 6 on. A cost for a whole stay has `unit` `per stay`",
    "inpatient.psychiatric": "Inpatient psychiatric hospital stays",
    "giveback": "The plan's monthly reduction of the member's Part B premium (Part B giveback or buydown). "
                "Use `cost_kind` `part_b_reduction`, the amount without \"up to\", and `unit` `per month`. Leave "
                "`condition` blank even for limits such as \"if Medicaid pays your Part B premium\" or \"no more than "
                "your Part B premium\"",
    "part_b_drugs": "Medicare Part B drugs, priced together. Not Part D drugs, home infusion therapy or dialysis services",
    "part_b_drugs.chemotherapy": "Chemotherapy and other cancer drugs, with their administration",
    "part_b_drugs.insulin": "Part B insulin, such as insulin used in a pump",
    "part_b_drugs.allergy": "Allergy antigens, allergy serum and allergy shots",
    "part_b_drugs.vaccine": "Part B vaccines, such as flu, pneumonia, Hepatitis B and COVID-19 shots. "
                            "\"No coinsurance, copayment, or deductible\" is a `$0` copay",
    "medical_deductible": "The plan's yearly medical deductible for Medicare-covered services, which applies to all of them. "
                          "Not a Part D, dental or hearing aid deductible. A plan with none has `cost_kind` `deductible` "
                          "and amount `$0`. `network` is where it applies: a combined deductible that excludes all "
                          "in-network services is `out`. Quote the amount and, if it is on the same page, the line that "
                          "says which services it applies to",
    "medical_deductible.some": "A yearly medical deductible that applies to some Medicare-covered services only, as when "
                               "the document lists the services it applies to or excludes, or says \"select\", "
                               "\"certain\" or \"most\" services",
    "medical_deductible.part_b": "The document says the deductible is Original Medicare's Part B deductible. This fact "
                                 "has `cost_kind` `covered`, and the amount is a separate `deductible` fact",
    "dental": "Dental services, priced together. Medicare-covered dental is `covered_by` `medicare`. Routine, "
              "\"non-Medicare covered\" and mandatory supplemental dental is `supplemental`, and \"not covered\" is "
              "`supplemental` `not_covered`. Dental only in an optional package has `package` set to its name, and the "
              "package premium is a `dental` `premium` fact with that `package`. A shared allowance or card that names "
              "dental is an `allowance` fact with `pool` set to its name, or `covered` with that `pool` if the page "
              "gives no amount",
    "dental.preventive": "Preventive dental care, such as oral exams, cleanings and dental X-rays",
    "dental.comprehensive": "Comprehensive dental care, such as fillings, extractions, crowns and dentures",
    "extras": "Acupuncture, chiropractic, massage, naturopathy and non-emergency transportation, priced together. "
              "A Medicare-covered version is `covered_by` `medicare`; an exclusions-chart row such as \"Acupuncture | "
              "Available for people with chronic low back pain\" is `medicare` `covered` with that `condition`. "
              "Routine and \"non-Medicare covered\" benefits are `supplemental`, and \"not covered\" is "
              "`supplemental` `not_covered`. A benefit only in an optional package has `package` set to its name. "
              "A shared allowance, card or wellness fund (such as Wellness Bucks or a Flex Card) gives one fact per "
              "benefit it names, with `pool` set to its name: an `allowance`, or `covered` if the page gives no amount. "
              "`condition` says who qualifies or when the benefit applies",
    "extras.acupuncture": "Acupuncture. Medicare covers it only for chronic low back pain",
    "extras.chiropractic": "Chiropractic care. Medicare covers only manual manipulation of the spine to correct a subluxation",
    "extras.massage": "Therapeutic massage",
    "extras.naturopathy": "Naturopathic services",
    "extras.transportation": "Non-emergency rides to medical appointments or pharmacies, not ambulance. "
                             "A ride only after a hospital stay or emergency visit has that `condition`",
}
ROUTINE = ("Routine and \"non-Medicare covered\" benefits are `supplemental`, and \"not covered\" is `supplemental` "
           "`not_covered`. A benefit only in an optional package has `package` set to its name. A shared allowance, "
           "card or wellness fund that names the benefit is an `allowance` fact with `pool` set to its name, or "
           "`covered` with that `pool` if the page gives no amount. `condition` names who qualifies when only some "
           "members do, such as members with certain chronic conditions (SSBCI). Frequency goes in `limit`. Leave "
           "`condition` blank for notes such as \"prior authorization may be required\" or \"you must use TruHearing\"")
NOT_MEDICARE = "Medicare does not cover these, so they are `supplemental`"
BENEFITS.update({
    "vision": f"Vision care, priced together. {ROUTINE}. Medicare covers only exams to diagnose and treat eye disease, "
              "glaucoma screening, diabetic retinopathy exams, and eyewear after cataract surgery; these are "
              "`covered_by` `medicare`. Other eye exams and eyewear are `supplemental`",
    "vision.exam": "Eye exams, such as a routine eye exam or refraction",
    "vision.eyewear": "Eyeglasses, lenses, frames and contact lenses",
    "hearing": f"Hearing care, priced together. {ROUTINE}. Medicare covers only diagnostic hearing and balance exams; "
               "these are `covered_by` `medicare`. Routine hearing exams, hearing aid fittings and hearing aids are "
               "`supplemental`",
    "hearing.exam": "Hearing exams, such as a routine hearing exam or hearing aid fitting evaluation",
    "hearing.aids": "Hearing aids. Prices for aid levels, such as \"$599 copay per ear for Advanced\" and \"$899 copay "
                    "per ear for Premium\", are one fact with amount `$599 or $899`. A vendor such as TruHearing or "
                    "NationsHearing is not a `provider_tier`",
    "fitness": f"Fitness benefits, such as a gym membership, SilverSneakers, Renew Active, One Pass, Silver&Fit or a "
               f"home fitness kit. {NOT_MEDICARE}. {ROUTINE}",
    "otc": f"An allowance for over-the-counter (OTC) health and wellness items. A rewards program is not an OTC "
           f"allowance. A credit for OTC items that also pays for healthy food for qualifying members is an OTC "
           f"allowance for every member. {NOT_MEDICARE}. {ROUTINE}",
    "packages": "An optional supplemental benefit package that a member may buy. Give its monthly premium as a "
                "`packages` `supplemental` `premium` fact with `package` set to its name. A document that says the "
                "plan offers no optional supplemental benefits gives `packages` `supplemental` `not_covered`",
})
# Regexes that find the pages about each benefit group
FIND = {"imaging": [r"x.ray", r"radiolog", r"\bMRI\b", r"\bCT\b", r"\bPET\b", r"ultrasound", r"mammogra",
                    r"nuclear medicine", r"imaging"],
        "ambulance": [r"ambulance", r"outside (?:of )?the United States", r"worldwide", r"anywhere in the world"],
        "surgery": [r"outpatient surg", r"ambulatory surg", r"surgical cent", r"surgery cent", r"diagnostic colonoscop",
                    r"skin biops"],
        "tests": [r"diagnostic (?:test|procedure)", r"\bEKG", r"lab(?:oratory)? (?:services|tests)", r"non.?radiolog",
                  r"sleep stud"],
        "visits": [r"physician/practitioner services, including",
                   r"(?:primary care|\bPCP|specialist|specialty care)[^\n]{0,60}(?:\$\d|\d%)",
                   r"(?:\$\d|\d%)[^\n]{0,60}(?:primary care|\bPCP|specialist)",
                   r"(?:primary care|primary care physician|specialist|specialty care) (?:office )?visit", r"provider and professional services",
                   r"by a specialist", r"doctor visits"],
        "rehab": [r"outpatient rehab", r"physical therap", r"occupational therap", r"speech.language"],
        "inpatient": [r"inpatient hospital", r"inpatient (?:psychiatric|mental)"],
        "giveback": [r"part\s*b\s+premium\s+reduction", r"reduc\w*\s+(?:\w+\s+){0,4}(?:medicare\s+)?part\s*b\s+premium",
                     r"part\s*b\s+premium\s+is\s+reduced", r"part\s*b\s+(?:buydown|give ?back)"],
        "part_b_drugs": [r"part\s*b\s+(?:prescription\s+)?drugs?[\s\S]{0,400}?(?:\$\d|\d%)",
                         r"(?:\$\d|\d%)[\s\S]{0,200}?part\s*b\s+(?:prescription\s+)?drugs?",
                         r"chemotherap[\s\S]{0,300}?(?:\$\d|\d%)", r"immunizations[\s\S]{0,600}?(?:\bno\b|\$0|\b0%)"],
        "medical_deductible": [r"(?:medical|combined|in.network) deductible", r"our plan deductible",
                               r"does not have a (?:medical )?deductible", r"no deductible for medical",
                               r"your (?:medical )?deductible is", r"deductible for (?:select|certain)",
                               r"(?<!drug coverage )(?<!part d )\bdeductible\s+\$\d",
                               r"deductible (?:applies|doesn.t apply|does not apply) to (?:some|the following)",
                               r"excluded from the (?:combined |in.network )*deductible"],
        "dental": [r"dental (?:services|benefit|exam)", r"(?:preventive|comprehensive|routine) dental",
                   r"dental (?:&|and) alternative", r"cleanings", r"optional supplemental", r"spendables"],
        "extras": [r"acupunct", r"chiropract", r"massage", r"naturopath", r"transportation", r"one.way trips?",
                   r"wellness bucks", r"flex ?card"],
        "vision": [r"routine eye exam", r"eye ?wear", r"eyeglass", r"contact lens", r"vision (?:services|care|benefit|exam)",
                   r"spendables"],
        "hearing": [r"hearing aid", r"routine hearing", r"hearing exam", r"spendables"],
        "fitness": [r"fitness", r"silver ?sneakers", r"renew active", r"\bgym\b", r"one pass"],
        "otc": [r"over.the.counter", r"\bOTC\b"],
        "packages": [r"optional supplemental", r"advantage plus", r"optional (?:dental|vision|hearing|benefits?)\b",
                     r"(?:dental|vision|hearing) rider"]}
SETTINGS = {
    "any": "The document names no setting, or one cost covers every setting",
    "office": "A physician's office, of any kind",
    "office.pcp": "A primary care physician's office",
    "office.specialist": "A specialist's office",
    "freestanding": "A freestanding facility, such as a radiology center",
    "outpatient_hospital": "An outpatient hospital",
    "urgent_care": "An urgent care center",
    "asc": "An ambulatory surgical center (ASC)",
    "telehealth": "Virtual visits by phone or video (telehealth)",
    "outside_us": "Outside the United States and its territories, as in a worldwide emergency benefit, "
                  "or an exclusion of all care outside the U.S.",
    "pharmacy": "A retail or mail-order pharmacy",
}
# The settings a group's readers may use
GROUP_SETTINGS = {
    "imaging": ("any", "office", "office.pcp", "office.specialist", "freestanding", "outpatient_hospital", "urgent_care"),
    "ambulance": ("any", "outside_us"),
    "surgery": ("any", "outpatient_hospital", "asc"),
    "tests": ("any", "office", "office.pcp", "office.specialist", "freestanding", "outpatient_hospital", "urgent_care", "asc"),
    "visits": ("any", "office", "office.pcp", "office.specialist", "telehealth"),
    "rehab": ("any", "office", "office.specialist", "freestanding", "outpatient_hospital"),
    "inpatient": ("any",),
    "giveback": ("any",),
    "part_b_drugs": ("any", "office", "office.pcp", "office.specialist", "outpatient_hospital", "asc", "pharmacy"),
    "medical_deductible": ("any",),
    "dental": ("any",),
    "extras": ("any", "office", "office.pcp", "office.specialist"),
    "vision": ("any",),
    "hearing": ("any",),
    "fitness": ("any",),
    "otc": ("any",),
    "packages": ("any",),
}
NETWORKS = {"any": "In and out of network, as the document says", "in": "In network", "out": "Out of network"}
COVERED_BY = {"medicare": "A Medicare-covered benefit", "supplemental": "A routine (supplemental) benefit"}
COST_KINDS = {
    "copay": "Dollar copayment",
    "coinsurance": "Percent coinsurance",
    "allowance": "Dollar amount the plan pays",
    "max": "Dollar most the plan pays",
    "visit_limit": "Number of visits or items",
    "deductible": "Dollar deductible",
    "premium": "Dollar monthly premium",
    "part_b_reduction": "Dollar monthly Part B premium reduction",
    "covered": "Covered, with no amount stated",
    "not_covered": "Not covered",
}
VOCABULARIES = {"benefit": BENEFITS, "setting": SETTINGS, "network": NETWORKS, "covered_by": COVERED_BY,
                "cost_kind": COST_KINDS}
SOURCES_BEST_FIRST = ("EOC", "RIDER", "SB", "PBP", "Landscape")
DOCUMENTS = ("EOC", "RIDER", "SB")
PLAN_ID = r"[HRS]\d{4}-\d{3}-\d"

DOLLARS = r"\$(?:0|[1-9]\d{0,2}(?:,\d{3})*)(?:\.\d\d)?"
PERCENT = r"(?:100|[1-9]?\d)(?:\.\d+)?%"
COUNT = r"[1-9]\d*"
AMOUNTS = {"coinsurance": PERCENT, "visit_limit": COUNT, "covered": None, "not_covered": None}
AMOUNT_RULES = """Amounts:
- Dollars as `$1,250` or `$12.50`, with commas and no other text.
- Coinsurance as `20%`. Visit limits as a count, such as `24`.
- A range as `$0-$300`, low end first. Alternatives as `$100 or $200`, which may be ranges.
- No amount for `covered` and `not_covered`.
- A copay or coinsurance depending on who you are is two facts, each with its `condition`.
- Put the time or count in `limit`, such as `per year`, and the unit in `unit`, such as `per visit`.
- `provider_tier`, `condition`, `package` and `pool` are blank unless the document states one. Copy its words."""


def number(amount):
    return float(re.sub(r"[$,%]", "", amount))


def amount_ok(kind, amount):
    one = AMOUNTS.get(kind, DOLLARS)
    if one is None:
        return amount == ""
    if not re.fullmatch(f"{one}(?:-{one})?(?: or {one}(?:-{one})?)*", amount):
        return False
    ranges = [r.split("-") for r in amount.split(" or ")]
    return all(number(r[0]) < number(r[-1]) for r in ranges if len(r) == 2)


def fact_id(row):
    return hashlib.sha256("\x1f".join(row[k] for k in KEY).encode()).hexdigest()[:16]


def covers(word, leaf):
    """Whether a fact's benefit or setting word applies to leaf. The setting `any` applies to every setting."""
    return word == "any" or leaf == word or leaf.startswith(word + ".")


def quotes(row):
    """The row's quotes, or None if they are not a non-empty JSON list of strings."""
    try:
        found = json.loads(row["quotes"])
    except (TypeError, json.JSONDecodeError):
        return None
    return found if isinstance(found, list) and found and all(isinstance(q, str) and q for q in found) else None


def check(row):
    """Why the row is not a well-formed fact."""
    if set(row) != set(COLUMNS):
        return [f"columns: {sorted(set(row) ^ set(COLUMNS))}"]
    problems = [f"{column}: {row[column]!r}" for column, words in VOCABULARIES.items() if row[column] not in words]
    if row["source"] not in SOURCES_BEST_FIRST:
        problems.append(f"source: {row['source']!r}")
    if not re.fullmatch(PLAN_ID, row["plan_id"]):
        problems.append(f"plan_id: {row['plan_id']!r}")
    if row["cost_kind"] in COST_KINDS and not amount_ok(row["cost_kind"], row["amount"]):
        problems.append(f"amount: {row['amount']!r} is not a {row['cost_kind']}")
    if row["fact_id"] != fact_id(row):
        problems.append(f"fact_id: {row['fact_id']!r} is not {fact_id(row)!r}")
    document = row["source"] in DOCUMENTS
    if document != bool(re.fullmatch(r"[0-9a-f]{64}", row["doc_sha"])):
        problems.append(f"doc_sha: {row['doc_sha']!r} for source {row['source']}")
    if document != bool(re.fullmatch(r"[1-9]\d*", row["page"])):
        problems.append(f"page: {row['page']!r} for source {row['source']}")
    if quotes(row) is None:
        problems.append(f"quotes: {row['quotes']!r} is not a list of quotes or field names")
    return problems


def conflicts(rows):
    """Rows that share an identity but differ."""
    seen = {}
    for row in rows:
        seen.setdefault(tuple(row[c] for c in IDENTITY), set()).add(tuple(row[c] for c in COLUMNS))
    return [identity for identity, versions in seen.items() if len(versions) > 1]


def write(path, rows):
    """Writes the facts sorted, without exact duplicates. Raises ValueError, writing nothing, if any row is bad."""
    problems = [f"{row.get('plan_id')} {row.get('benefit')}: {p}" for row in rows for p in check(row)]
    problems += [f"{identity}: two different rows" for identity in conflicts(rows)]
    if problems:
        raise ValueError("\n".join(problems))
    unique = sorted({tuple(row[c] for c in COLUMNS[1:]) + (row["fact_id"],) for row in rows})
    with open(path + ".tmp", "w", newline="") as f:
        out = csv.writer(f, lineterminator="\n")
        out.writerow(COLUMNS)
        out.writerows((r[-1], *r[:-1]) for r in unique)
    os.replace(path + ".tmp", path)


def read(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def describe(group):
    """The vocabulary for one benefit group, as Markdown for a reader's task."""
    if group not in BENEFITS:
        raise KeyError(group)

    def table(words):
        return "\n".join(f"- `{k}`: {v}" for k, v in words.items())

    vocabularies = dict(VOCABULARIES, benefit={k: v for k, v in BENEFITS.items() if covers(group, k)},
                        setting={k: v for k, v in SETTINGS.items() if k in GROUP_SETTINGS[group]})
    return "\n\n".join([f"{column}:\n{table(words)}" for column, words in vocabularies.items()] + [AMOUNT_RULES])
