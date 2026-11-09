"""Generates the main MA chart (columns C..AB) from the CMS Landscape and PBP Benefits files.

Usage: python3 -I main_chart.py <plans.csv> <pbp_dir> <out.csv> <reads.csv>
reads.csv lists the plans.csv and PBP fields behind each cell.
Each cell is in-network unless noted. Column rules are in fields.py.
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cms_sources  # noqa: E402
import fields  # noqa: E402
import pbp  # noqa: E402
from reads import ROWS, logged  # noqa: E402


def num(v):
    return float(v) if v not in (None, "") else None


def money(x):
    return f"${x:,.2f}".replace(".00", "")


def span(lo, hi, fmt):
    lo, hi = num(lo), num(hi)
    if lo is None and hi is None:
        return ""
    lo = hi if lo is None else lo
    hi = lo if hi is None else hi
    return fmt(lo) if lo == hi else f"{fmt(lo)}-{fmt(hi)}"


def pct(x):
    return f"{x:g}%"


def join_costs(*parts):
    return " or ".join(p for p in parts if p)


def first(plan, stem):
    rows = plan.get(stem) or [{}]
    return rows[0]


def flag(row, field, index):
    """True when the 1-based position `index` of a CMS '1 in N' bit string is set."""
    v = row.get(field, "")
    return len(v) >= index and v[index - 1] == "1"


def copay_or_coins(row, copay_lo, copay_hi, coins_lo, coins_hi):
    """A service with no copay or coinsurance fields in the PBP has no cost sharing."""
    return join_costs(span(row.get(copay_lo), row.get(copay_hi), money),
                      span(row.get(coins_lo), row.get(coins_hi), pct)) or "$0"


def out_of_network(plan, category):
    for g in plan.get("pbp_Section_C_OON", []):
        if category in g.get("pbp_c_oon_out_mc_bendesc_cats", "").split(";"):
            return copay_or_coins(g, "pbp_c_oon_outpt_copay_min_amt", "pbp_c_oon_outpt_copay_max_amt",
                                  "pbp_c_oon_outpt_coins_min_pct", "pbp_c_oon_outpt_coins_max_pct")
    return ""


def in_out(plan, in_network, category):
    oon = out_of_network(plan, category)
    return f"{in_network} | {oon}" if oon else in_network


def moop(plan):
    d = first(plan, "pbp_Section_D")
    inn = num(d.get("pbp_d_out_pocket_amt"))
    comb = num(d.get("pbp_d_comb_max_enr_amt"))
    cell = money(inn) if inn is not None else ""
    return f"{cell} | {money(comb)}" if comb is not None else cell


def inpatient(plan):
    r = first(plan, "pbp_b1a_inpat_hosp")
    if r.get("pbp_b1a_cost_vary_tiers_yn") == "1":
        raise ValueError("inpatient cost sharing varies by provider tier; only tier 1 is handled")
    n = int(r.get("pbp_b1a_copay_mcs_int_num_t1", "0") or 0) - 1
    days = []
    for i in range(1, n + 1):
        amt = num(r.get(f"pbp_b1a_copay_mcs_amt_int{i}_t1"))
        if amt:
            days.append(f"{money(amt)} | {r[f'pbp_b1a_copay_mcs_bgnd_int{i}_t1']}-{r[f'pbp_b1a_copay_mcs_endd_int{i}_t1']}")
    if days:
        return "; ".join(days)
    stay = num(r.get("pbp_b1a_copay_mcs_amt_t1"))
    if stay:
        return f"{money(stay)} per admission"
    coins = r.get("pbp_b1a_coins_mcs_pct_t1")
    if coins:
        return pct(float(coins))
    return "$0" if r.get("pbp_b1a_copay_yn") == "1" else ""


def cost_range(row, copays, coinsurances):
    """Spans the copay fields, then the coinsurance fields, as "$a-$b or c%"; "$0" if none is set."""
    def joined(names, fmt):
        amounts = [num(row[n]) for n in names if row.get(n)]
        return span(min(amounts), max(amounts), fmt) if amounts else ""
    return join_costs(joined(copays, money), joined(coinsurances, pct)) or "$0"


WORLDWIDE_EMERGENCY_TRANSPORTATION = 1  # position in pbp_b4c_bendesc_ehc


def ambulance(plan):
    b10 = first(plan, "pbp_b10_amb_trans")
    domestic = cost_range(b10, [f"pbp_b10a_copay_{k}_amt_{m}" for k in ("gas", "aas") for m in ("min", "max")],
                          [f"pbp_b10a_coins_{k}_pct_{m}" for k in ("gas", "aas") for m in ("min", "max")]) if b10 else ""
    b4 = first(plan, "pbp_b4_emerg_urgent")
    worldwide = "not covered"
    if flag(b4, "pbp_b4c_bendesc_ehc", WORLDWIDE_EMERGENCY_TRANSPORTATION):
        worldwide = cost_range(b4, ["pbp_b4c_copay_amt_wet_min", "pbp_b4c_copay_amt_wet_max"],
                               ["pbp_b4c_coins_pct_wet_min", "pbp_b4c_coins_pct_wet_max"])
    return f"{domestic} | {worldwide}"


def outpatient_surgery(plan):
    r = first(plan, "pbp_b9_outpat_hosp")
    hosp = copay_or_coins(r, "pbp_b9a_copay_ohs_amt_min", "pbp_b9a_copay_ohs_amt_max",
                          "pbp_b9a_coins_ohs_pct_min", "pbp_b9a_coins_ohs_pct_max")
    asc = copay_or_coins(r, "pbp_b9b_copay_mc_amt", "pbp_b9b_copay_mc_amt_max",
                         "pbp_b9b_coins_pct_mc", "pbp_b9b_coins_pct_mcmax")
    return f"{hosp} | {asc}"


def rehab(plan):
    r = first(plan, "pbp_b7_health_prof")
    lows = [num(r.get(k)) for k in ("pbp_b7c_copay_mc_amt_min", "pbp_b7i_copay_mc_amt_min") if r.get(k)]
    highs = [num(r.get(k)) for k in ("pbp_b7c_copay_mc_amt_max", "pbp_b7i_copay_mc_amt_max") if r.get(k)]
    copay = span(min(lows), max(highs), money) if lows else ""
    clow = [num(r.get(k)) for k in ("pbp_b7c_coins_pct_mc_min", "pbp_b7i_coins_pct_mc_min") if r.get(k)]
    chigh = [num(r.get(k)) for k in ("pbp_b7c_coins_pct_mc_max", "pbp_b7i_coins_pct_mc_max") if r.get(k)]
    coins = span(min(clow), max(chigh), pct) if clow else ""
    return join_costs(copay, coins) or "$0"


def tests_labs(plan):
    r = first(plan, "pbp_b8_clin_diag_ther")
    tests = copay_or_coins(r, "pbp_b8a_copay_min_dmc_amt", "pbp_b8a_copay_max_dmc_amt",
                           "pbp_b8a_coins_pct_dmc", "pbp_b8a_coins_pct_dmc_max")
    labs = copay_or_coins(r, "pbp_b8a_lab_copay_amt", "pbp_b8a_lab_copay_amt_max",
                          "pbp_b8a_coins_pct_lab", "pbp_b8a_coins_pct_lab_max")
    return f"{tests}/{labs}"


def imaging(plan):
    r = first(plan, "pbp_b8_clin_diag_ther")
    xray = copay_or_coins(r, "pbp_b8b_copay_mc_amt", "pbp_b8b_copay_mc_amt_max",
                          "pbp_b8b_coins_pct_cmc", "pbp_b8b_coins_pct_cmc_max")
    radiology = copay_or_coins(r, "pbp_b8b_copay_amt_drs", "pbp_b8b_copay_amt_drs_max",
                               "pbp_b8b_coins_pct_drs", "pbp_b8b_coins_pct_drs_max")
    return f"{xray} | {radiology}"


def part_b_drugs(plan):
    r = first(plan, "pbp_b15_partb_rx_drugs")
    return join_costs(span(r.get("mrx_b_chemo_coins_min_pct"), r.get("mrx_b_chemo_coins_max_pct"), pct),
                      span(r.get("mrx_b_chemo_copay_amt_min"), r.get("mrx_b_chemo_copay_amt_max"), money))


TIER_POSITIONS = {2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6, 1: 7}


def pharmacy_deductible(plan, landscape):
    if landscape["part_d_deductible"] == "n/a":
        return "n/a"
    ded = landscape["part_d_deductible"]
    if ded == "$0":
        return "$0"
    r = first(plan, "pbp_mrx")
    tiers = sorted(TIER_POSITIONS[i] for i in range(1, 8) if flag(r, "mrx_alt_no_ded_tier", i))
    return f"{ded} not tiers {','.join(map(str, tiers))}" if tiers else ded


def medical_deductible(plan):
    d = first(plan, "pbp_Section_D")
    if d.get("pbp_d_inn_deduct_yn") == "1":
        amt = "Part B deductible" if d.get("pbp_d_inn_deduct_partb_yn") == "1" else money(
            num(d["pbp_d_inn_deduct_amt"]))
        return amt if d.get("pbp_d_inn_deduct_m_yn") == "1" else f"{amt} some"
    if d.get("pbp_d_ann_deduct_yn") == "1":
        if d.get("pbp_d_ann_deduct_amt_type") == "2":
            amt = "Part B deductible"
        else:
            amt = money(num(d["pbp_d_ann_deduct_amt"]))
        if not flag(d, "pbp_d_ann_deduct_bens", 2) and d.get("pbp_d_ann_deduct_inn_mc_yn") != "1":
            return f"{amt} out-of-network only"
        return amt if d.get("pbp_d_ann_deduct_inn_mc_yn") == "1" else f"{amt} some"
    return "$0"


def mandatory(row, prefix):
    """True when any benefit-description AMO field under prefix is Mandatory (2) or Both (4)."""
    return any(row.get(k) in ("2", "4") for k in list(row) if k.startswith(prefix) and "_amo" in k)


def part_b_reduction(plan):
    d = first(plan, "pbp_Section_D")
    if d.get("pbp_d_mco_pay_reduct_yn") != "1":
        return ""
    return money(num(d["pbp_d_mco_pay_reduct_amt"])) if d.get("pbp_d_mco_pay_reduct_amt") else "●"


def b14c(plan):
    return first(plan, "pbp_b14_preventive").get("pbp_b14c_bendesc_ehc", "").split(";")


def dot(present):
    return "●" if present is True else present or ""


# Each column of the main chart, from the plan's plans.csv row and its PBP files.
COLUMNS = {
    "C_premium": lambda landscape, plan: landscape["premium"],
    "D_premium_full_extra_help": lambda landscape, plan: landscape["premium_full_extra_help"],
    "E_moop": lambda landscape, plan: moop(plan),
    "F_primary_care": lambda landscape, plan: in_out(plan, copay_or_coins(
        first(plan, "pbp_b7_health_prof"), "pbp_b7a_copay_amt_mc_min", "pbp_b7a_copay_amt_mc_max",
        "pbp_b7a_coins_pct_mc_min", "pbp_b7a_coins_pct_mc_max"), "7a"),
    "G_specialist": lambda landscape, plan: in_out(plan, copay_or_coins(
        first(plan, "pbp_b7_health_prof"), "pbp_b7d_copay_amt_mc_min", "pbp_b7d_copay_amt_mc_max",
        "pbp_b7d_coins_pct_mc_min", "pbp_b7d_coins_pct_mc_max"), "7d"),
    "H_inpatient": lambda landscape, plan: inpatient(plan),
    "I_outpatient_surgery": lambda landscape, plan: outpatient_surgery(plan),
    "J_outpatient_rehab": lambda landscape, plan: rehab(plan),
    "K_tests_labs": lambda landscape, plan: tests_labs(plan),
    "L_xray_imaging": lambda landscape, plan: imaging(plan),
    "M_part_b_drugs": lambda landscape, plan: part_b_drugs(plan),
    "N_pharmacy_deductible": lambda landscape, plan: pharmacy_deductible(plan, landscape),
    "O_medical_deductible": lambda landscape, plan: medical_deductible(plan),
    "P_vision": lambda landscape, plan: dot(mandatory(first(plan, "pbp_b17_eye_exams_wear"), "pbp_b17")),
    "Q_hearing": lambda landscape, plan: dot(mandatory(first(plan, "pbp_b18_hearing_exams_aids"), "pbp_b18")),
    "R_dental": lambda landscape, plan: dot(mandatory(first(plan, "pbp_b16_dental"), "pbp_b16b")
                                            or mandatory(first(plan, "pbp_b16_dental"), "pbp_b16c")),
    "S_acupuncture": lambda landscape, plan: dot(first(plan, "pbp_b13_other_services").get("pbp_b13a_bendesc_yn") == "1"
                                                 and mandatory(first(plan, "pbp_b13_other_services"), "pbp_b13a")),
    "T_chiropractic": lambda landscape, plan: dot(flag(first(plan, "pbp_b7_health_prof"), "pbp_b7b_bendesc_ehc", 2)
                                                  and first(plan, "pbp_b7_health_prof").get("pbp_b7b_bendesc_amo_rc")
                                                  in ("2", "4")),
    "U_naturopath": lambda landscape, plan: "",
    "V_massage": lambda landscape, plan: dot("14c18" in b14c(plan)),
    "W_fitness": lambda landscape, plan: dot("14c4" in b14c(plan)),
    "X_transportation": lambda landscape, plan: dot(first(plan, "pbp_b10_amb_trans").get("pbp_b10b_bendesc_yn") == "1"),
    "Y_otc": lambda landscape, plan: dot(first(plan, "pbp_b13_other_services").get("pbp_b13b_bendesc_otc") == "1"),
    "Z_part_b_reduction": lambda landscape, plan: dot(part_b_reduction(plan)),
    "AA_opt_packages": lambda landscape, plan: dot(bool(plan.get("pbp_Section_D_opt"))),
    "AB_ambulance": lambda landscape, plan: ambulance(plan),
}
PLANS = "plans.csv"
READS = ["plan_id", "column", "file", "field", "value", "title", "meaning"]


def chart_row(landscape, plan):
    return {"section": landscape["section"], "plan_id": landscape["plan_id"], "plan_name": landscape["plan_name"]} | {
        column: compute(landscape, plan) for column, compute in COLUMNS.items()}


def reads(landscape, plan, dictionary):
    """The plans.csv and PBP fields each column read, with each PBP field's title and decoded value."""
    return [dict(plan_id=landscape["plan_id"], column=column, file=file, field=field, value=value,
                 title=dictionary.get((file, field), {}).get("title", "") if field != ROWS else "",
                 meaning=cms_sources.meaning(dictionary, file, field, value) if field != ROWS else "")
            for column, compute in COLUMNS.items()
            for file, field, value in logged(compute, (PLANS, landscape), ("plan", plan))[1]]


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def sheet(plans, data, make_row, dvha=False):
    """Builds a row per plan. Each row must have the columns of fields.py, in its order."""
    columns = ["section", "plan_id", "plan_name"] + list(fields.labels("dvha" if dvha else "main"))
    rows = [make_row(p, data[p["plan_id"]]) for p in plans]
    for p, row in zip(plans, rows):
        if list(row) != columns:
            raise ValueError(f"{p['plan_id']}: columns differ from pipeline/fields.py: {list(row)}")
    return rows


def main(plans_csv, pbp_dir, out_csv, reads_csv):
    plans = list(csv.DictReader(open(plans_csv)))
    data = pbp.load(pbp_dir, [p["plan_id"] for p in plans])
    write_csv(out_csv, sheet(plans, data, chart_row))
    dictionary = pbp.load_dictionary(pbp_dir)
    with open(reads_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=READS)
        w.writeheader()
        w.writerows(r for p in plans for r in reads(p, data[p["plan_id"]], dictionary))


if __name__ == "__main__":
    main(*sys.argv[1:])
