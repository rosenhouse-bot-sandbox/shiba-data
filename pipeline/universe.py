"""Lists the MA plans offered in every given county of a state, from the CMS Landscape CSV.

Usage: python3 -I universe.py <Landscape.csv> <out.csv> <state> <county>...
"""
import csv
import sys

EXCLUDED_SNP_TYPES = ("Dual-Eligible", "Institutional")


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


def to_record(row):
    has_d = row["Part D Coverage Indicator"] == "Yes"
    return {
        "section": section(row),
        "plan_id": plan_id(row),
        "plan_name": row["Plan Name"],
        "plan_type": row["Plan Type"],
        "organization": row["Organization Marketing Name"],
        "premium": money(row["Monthly Consolidated Premium (Part C + D)"] if has_d else row["Part C Premium"]),
        "premium_full_extra_help": full_extra_help_premium(row),
        "moop_in_network": money(row["In-Network Maximum Out-of-Pocket (MOOP) Amount"]),
        "part_d_deductible": money(row["Annual Part D Deductible Amount"]) if has_d else "n/a",
        "tier_without_part_d_deductible": row["Offers Drug Tier with No Part D Deductible"] if has_d else "n/a",
        "c_snp_conditions": row["Chronic or Disabling Condition SNP (C-SNP) Condition Type"],
        "overall_star_rating": row["Overall Star Rating"],
    }


def main(src, out, state, *counties):
    with open(src, encoding="utf-8-sig") as f:
        records = [to_record(r) for r in select_plans(csv.DictReader(f), state, counties)]
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(records[0]))
        w.writeheader()
        w.writerows(records)
    print(f"{len(records)} plans -> {out}")


if __name__ == "__main__":
    main(*sys.argv[1:])
