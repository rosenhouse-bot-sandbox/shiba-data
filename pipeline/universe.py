"""Lists the MA plans offered in every given county of a state, from the CMS Landscape CSV.

Usage: python3 -I universe.py <Landscape.csv> <out.csv> <reads.csv> <state> <county>...
reads.csv lists the Landscape fields behind each plan's columns.
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reads import logged  # noqa: E402

EXCLUDED_SNP_TYPES = ("Dual-Eligible", "Institutional")
LANDSCAPE = "Landscape"


def section(row):
    if row["SNP Type"] == "Chronic or Disabling Condition":
        return "C-SNP"
    return "MA-PD" if row["Part D Coverage Indicator"] == "Yes" else "NO-PART-D"


def plan_id(row):
    return f'{row["Contract ID"]}-{row["Plan ID"]}-{row["Segment ID"]}'


def select_plans(rows, state, counties):
    by_plan = {}
    for r in rows:
        if r["State Territory Abbreviation"] == state and r["County Name"] in counties:
            by_plan.setdefault(plan_id(r), {})[r["County Name"]] = r
    plans = []
    for found in by_plan.values():
        if len(found) != len(counties):
            continue
        r = found[counties[0]]
        if r["Contract Category Type"].startswith("PDP") or r["SNP Type"] in EXCLUDED_SNP_TYPES:
            continue
        plans.append(r)
    order = {"MA-PD": 0, "C-SNP": 1, "NO-PART-D": 2}
    return sorted(plans, key=lambda r: (order[section(r)], r["Plan Name"].lower()))


def money(s):
    s = s.strip()
    return "" if s in ("", "Not Applicable") else s.replace(".00", "")


def full_extra_help_premium(row):
    if row["Part D Coverage Indicator"] != "Yes":
        return "n/a"
    total = float(row["Part C Premium"].strip("$ ").replace(",", "")) + float(
        row["Part D Low Income Beneficiary Premium Amount"].strip("$ ").replace(",", ""))
    return f"${total:,.2f}".replace(".00", "")


def has_d(row):
    return row["Part D Coverage Indicator"] == "Yes"


# Each plans.csv column, computed from the plan's Landscape row.
FIELDS = {
    "section": section,
    "plan_id": plan_id,
    "plan_name": lambda row: row["Plan Name"],
    "plan_type": lambda row: row["Plan Type"],
    "organization": lambda row: row["Organization Marketing Name"],
    "premium": lambda row: money(row["Monthly Consolidated Premium (Part C + D)"] if has_d(row) else row["Part C Premium"]),
    "premium_full_extra_help": full_extra_help_premium,
    "moop_in_network": lambda row: money(row["In-Network Maximum Out-of-Pocket (MOOP) Amount"]),
    "part_d_deductible": lambda row: money(row["Annual Part D Deductible Amount"]) if has_d(row) else "n/a",
    "tier_without_part_d_deductible": lambda row: row["Offers Drug Tier with No Part D Deductible"] if has_d(row) else "n/a",
    "c_snp_conditions": lambda row: row["Chronic or Disabling Condition SNP (C-SNP) Condition Type"],
    "overall_star_rating": lambda row: row["Overall Star Rating"],
}
READS = ["plan_id", "plan_field", "field", "value"]


def to_record(row):
    return {k: f(row) for k, f in FIELDS.items()}


def reads(row):
    """The Landscape fields each plans.csv column read: {plan_id, plan_field, field, value} rows."""
    return [dict(plan_id=plan_id(row), plan_field=k, field=field, value=value)
            for k, f in FIELDS.items() for _, field, value in logged(f, (LANDSCAPE, row))[1]]


def write(path, columns, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


def main(src, out, reads_out, state, *counties):
    with open(src, encoding="utf-8-sig") as f:
        selected = select_plans(csv.DictReader(f), state, counties)
    records = [to_record(r) for r in selected]
    write(out, list(records[0]), records)
    write(reads_out, READS, [r for row in selected for r in reads(row)])
    print(f"{len(records)} plans -> {out}")


if __name__ == "__main__":
    main(*sys.argv[1:])
