"""Lists the CMS fields behind the cells that plan documents rarely quote, such as a $0 deductible.

Usage: python3 -I cms_sources.py <Landscape.csv> <plans.csv> <pbp_dir> <out.csv> <state>
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pbp  # noqa: E402
import universe  # noqa: E402

LANDSCAPE = "Landscape"
PART_D = "Part D Coverage Indicator"

# The PBP file and fields that main_chart.py reads for each column.
PBP_FIELDS = {
    "K_tests_labs": ("pbp_b8_clin_diag_ther", (
        "pbp_b8a_copay_min_dmc_amt", "pbp_b8a_copay_max_dmc_amt", "pbp_b8a_coins_pct_dmc", "pbp_b8a_coins_pct_dmc_max",
        "pbp_b8a_lab_copay_amt", "pbp_b8a_lab_copay_amt_max", "pbp_b8a_coins_pct_lab", "pbp_b8a_coins_pct_lab_max")),
    "M_part_b_drugs": ("pbp_b15_partb_rx_drugs", (
        "mrx_b_chemo_coins_min_pct", "mrx_b_chemo_coins_max_pct", "mrx_b_chemo_copay_amt_min", "mrx_b_chemo_copay_amt_max")),
    "N_pharmacy_deductible": ("pbp_mrx", ("mrx_alt_no_ded_tier",)),
    "O_medical_deductible": ("pbp_Section_D", (
        "pbp_d_inn_deduct_yn", "pbp_d_inn_deduct_amt", "pbp_d_inn_deduct_partb_yn", "pbp_d_inn_deduct_m_yn",
        "pbp_d_ann_deduct_yn", "pbp_d_ann_deduct_amt", "pbp_d_ann_deduct_amt_type", "pbp_d_ann_deduct_bens",
        "pbp_d_ann_deduct_inn_mc_yn")),
}

# The Landscape columns that universe.py reads for each column of a plan with Part D.
LANDSCAPE_FIELDS = {
    "D_premium_full_extra_help": (PART_D, "Part C Premium", "Part D Low Income Beneficiary Premium Amount"),
    "N_pharmacy_deductible": (PART_D, "Annual Part D Deductible Amount"),
}

# What Medicare.gov's plan page probably calls each column. Nobody has checked these by hand.
MEDICARE_GOV = {
    "K_tests_labs": "Diagnostic tests and procedures, and Lab services",
    "M_part_b_drugs": "Chemotherapy drugs and Other Part B drugs",
    "N_pharmacy_deductible": "Drug deductible",
    "O_medical_deductible": "Health deductible",
}

COLUMNS = ["plan_id", "column", "file", "field", "title", "value", "meaning"]


def meaning(dictionary, stem, field, value):
    codes = dictionary.get((stem, field), {}).get("codes", {})
    if value in codes:
        return codes[value]
    if any(k.startswith("1 in ") for k in codes):
        return "; ".join(codes[f"1 in {i}"] for i, bit in enumerate(value, 1) if bit == "1" and f"1 in {i}" in codes)
    return ""


def landscape_rows(plan_id, landscape):
    out = []
    for column, fields in LANDSCAPE_FIELDS.items():
        if landscape[PART_D] != "Yes":
            fields = (PART_D,)
        out += [{"plan_id": plan_id, "column": column, "file": LANDSCAPE, "field": f, "title": "",
                 "value": landscape[f].strip(), "meaning": ""} for f in fields]
    return out


def pbp_rows(plan_id, plan, dictionary, has_part_d):
    out = []
    for column, (stem, fields) in PBP_FIELDS.items():
        if column in LANDSCAPE_FIELDS and not has_part_d:
            continue
        for r in plan.get(stem, [])[:1]:
            out += [{"plan_id": plan_id, "column": column, "file": stem, "field": f,
                     "title": dictionary.get((stem, f), {}).get("title", ""), "value": r[f],
                     "meaning": meaning(dictionary, stem, f, r[f])} for f in fields if f in r]
    return out


def rows(plans, data, dictionary, landscape):
    out = []
    for p in plans:
        land = landscape[p["plan_id"]]
        out += landscape_rows(p["plan_id"], land) + pbp_rows(p["plan_id"], data[p["plan_id"]], dictionary, land[PART_D] == "Yes")
    return out


def main(landscape_csv, plans_csv, pbp_dir, out_csv, state):
    plans = list(csv.DictReader(open(plans_csv)))
    wanted = {p["plan_id"] for p in plans}
    landscape = {}
    with open(landscape_csv, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["State Territory Abbreviation"] == state and universe.plan_id(r) in wanted:
                landscape.setdefault(universe.plan_id(r), r)
    data = pbp.load(pbp_dir, list(wanted))
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows(plans, data, pbp.load_dictionary(pbp_dir), landscape))


if __name__ == "__main__":
    main(*sys.argv[1:])
