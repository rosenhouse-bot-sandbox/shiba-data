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
}
# Regexes that find the pages about each benefit group
FIND = {"imaging": [r"x.ray", r"radiolog", r"\bMRI\b", r"\bCT\b", r"\bPET\b", r"ultrasound", r"mammogra",
                    r"nuclear medicine", r"imaging"]}
SETTINGS = {
    "any": "The document names no setting, or one cost covers every setting",
    "office": "A physician's office, of any kind",
    "office.pcp": "A primary care physician's office",
    "office.specialist": "A specialist's office",
    "freestanding": "A freestanding facility, such as a radiology center",
    "outpatient_hospital": "An outpatient hospital",
    "urgent_care": "An urgent care center",
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

    vocabularies = dict(VOCABULARIES, benefit={k: v for k, v in BENEFITS.items() if covers(group, k)})
    return "\n\n".join([f"{column}:\n{table(words)}" for column, words in vocabularies.items()] + [AMOUNT_RULES])
