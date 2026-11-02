"""Benefit facts: one cost or coverage term that a document or a CMS file states for one plan.

Extraction reads the vocabulary here. Column rules do not live here.
A row is identified by its fact_id, source and doc_sha: two sources may state the same fact.
"""
import csv, hashlib, json, os, re

COLUMNS = ("fact_id", "plan_id", "benefit", "setting", "network", "provider_tier", "condition", "package", "pool",
           "cost_kind", "amount", "unit", "limit", "covered_by", "source", "doc_sha", "page", "quotes", "note")
KEY = COLUMNS[1:10]

BENEFITS = {
    "imaging": "Outpatient X-rays and diagnostic radiology, when one cost covers both",
    "imaging.xray": "Outpatient X-rays",
    "imaging.advanced": "Diagnostic radiology services priced together, such as \"CT, MRI and PET\"",
    "imaging.advanced.ct": "CT (CAT) scans",
    "imaging.advanced.mri": "MRI and MRA",
    "imaging.advanced.pet": "PET scans",
    "imaging.advanced.nuclear": "Nuclear medicine",
    "imaging.ultrasound": "Ultrasounds",
    "imaging.mammogram": "Diagnostic mammograms, not screening mammograms",
    "imaging.radiation": "Therapeutic radiology (radiation therapy)",
}
SETTINGS = {
    "any": "The document names no setting, or one cost covers every setting",
    "office": "A physician's office, of any kind",
    "pcp_office": "A primary care physician's office",
    "specialist_office": "A specialist's office",
    "freestanding": "A freestanding facility, such as a radiology center",
    "outpatient_hospital": "An outpatient hospital",
}
NETWORKS = {"in": "In network", "out": "Out of network", "any": "Both, or the plan has no network"}
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
COVERED_BY = {"medicare": "A Medicare-covered benefit", "supplemental": "A routine (supplemental) benefit"}
SOURCES = ("EOC", "SB", "RIDER", "PBP", "Landscape")
DOCUMENTS = SOURCES[:3]

DOLLARS = r"\$\d{1,3}(?:,\d{3})*(?:\.\d\d)?"
AMOUNTS = {"coinsurance": r"\d+(?:\.\d+)?%", "visit_limit": r"\d+", "covered": None, "not_covered": None}


def amount_ok(kind, amount):
    one = AMOUNTS.get(kind, DOLLARS)
    if one is None:
        return amount == ""
    return re.fullmatch(f"{one}(?:-{one})?(?: or {one})*", amount) is not None


def fact_id(row):
    return hashlib.sha256("\x1f".join(row[k] for k in KEY).encode()).hexdigest()[:16]


def covers(benefit, leaf):
    """Whether a fact about benefit applies to leaf."""
    return leaf == benefit or leaf.startswith(benefit + ".")


def quotes(row):
    """The row's quotes, or None if they are not a non-empty JSON list of strings."""
    try:
        found = json.loads(row["quotes"])
    except json.JSONDecodeError:
        return None
    return found if isinstance(found, list) and found and all(isinstance(q, str) and q for q in found) else None


def check(row):
    """Why the row is not a well-formed fact."""
    if set(row) != set(COLUMNS):
        return [f"columns: {sorted(set(row) ^ set(COLUMNS))}"]
    problems = [f"{column}: {row[column]!r}" for column, words in
                [("benefit", BENEFITS), ("setting", SETTINGS), ("network", NETWORKS), ("cost_kind", COST_KINDS),
                 ("covered_by", COVERED_BY), ("source", SOURCES)] if row[column] not in words]
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


def write(path, rows):
    """Writes the facts sorted, without exact duplicates. Raises ValueError, writing nothing, if any row is bad."""
    problems = [f"{row.get('plan_id')} {row.get('benefit')}: {p}" for row in rows for p in check(row)]
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
    def table(words):
        return "\n".join(f"- `{k}`: {v}" for k, v in words.items())

    benefits = {k: v for k, v in BENEFITS.items() if covers(group, k)}
    return "\n\n".join([f"Benefits:\n{table(benefits)}", f"Settings:\n{table(SETTINGS)}",
                        f"Networks:\n{table(NETWORKS)}", f"Cost kinds:\n{table(COST_KINDS)}",
                        f"Covered by:\n{table(COVERED_BY)}"])
