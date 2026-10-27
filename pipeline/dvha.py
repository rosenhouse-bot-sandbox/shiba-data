"""Generates the DVHA sheet (dental, vision, hearing, alternative care) from the CMS PBP Benefits files.

Usage: python3 -I dvha.py <plans.csv> <pbp_dir> <out.csv>
Cells summarize in-network supplemental benefits. Column rules are in fields.py.
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pbp  # noqa: E402
import main_chart  # noqa: E402
from main_chart import first, flag, money, num, pct, span, write_csv  # noqa: E402

DICTIONARY = {}
COMPREHENSIVE = {"rs": "restorative", "end": "endodontics", "peri": "periodontics", "prm": "removable prosthodontics",
                 "prf": "fixed prosthodontics", "impl": "implants", "omsg": "oral surgery", "orth": "orthodontics",
                 "ags": "adjunctive general services", "mxpr": "maxillofacial prosthetics"}


def decode(stem, field, value):
    codes = DICTIONARY.get((stem, field), {}).get("codes", {})
    return (codes.get(value) or value or "").lower().replace("every ", "")


def per(stem, row, field):
    return "/" + decode(stem, field, row.get(field)) if row.get(field) else ""


def costs(row, fields):
    """Min-max over copay fields ($) and coinsurance fields (%) present in row."""
    dollars = [num(row[f]) for f in fields if f in row and "copay" in f]
    pcts = [num(row[f]) for f in fields if f in row and "coins" in f]
    if not any(dollars + pcts):
        return "$0"
    out = []
    if dollars:
        out.append(span(min(dollars), max(dollars), money))
    if pcts:
        out.append(span(min(pcts), max(pcts), pct))
    return " or ".join(out)


def mandatory(row, field):
    return row.get(field) in ("2", "4")


def dental(plan):
    s = "pbp_b16_dental"
    r = first(plan, s)
    prev_fields = [k for k in r if k.startswith(("pbp_b16b_copay_", "pbp_b16b_coins_")) and not k.endswith("_yn")]
    has_prev = any(mandatory(r, k) for k in r if k.startswith("pbp_b16b_bendesc") and k.endswith("_amo"))
    comp = [code for code in COMPREHENSIVE if mandatory(r, f"pbp_b16c_bendesc_{code}_amo")]
    parts = []
    if has_prev:
        parts.append(f"PREV {costs(r, prev_fields)}")
    if comp:
        comp_fields = [k for k in r if k.startswith(("pbp_b16c_copay_", "pbp_b16c_coins_"))
                       and any(f"_{c}_" in k for c in comp) and not k.endswith("_yn")]
        scope = "" if len(comp) > 2 else f" ({', '.join(COMPREHENSIVE[c] for c in comp)} only)"
        parts.append(f"COMP {costs(r, comp_fields)}{scope}")
    if r.get("pbp_b16b_maxplan_pv_amt"):
        shared = " PREV+COMP" if r.get("pbp_b16c_maxplan_cmp_type") == "1" and comp else ""
        parts.append(f"max {money(num(r['pbp_b16b_maxplan_pv_amt']))}{per(s, r, 'pbp_b16b_maxplan_pv_per')}{shared}")
    if r.get("pbp_b16c_maxplan_cmp_amt"):
        parts.append(f"COMP max {money(num(r['pbp_b16c_maxplan_cmp_amt']))}{per(s, r, 'pbp_b16c_maxplan_cmp_per')}")
    if parts and not r.get("pbp_b16b_maxplan_pv_amt") and not r.get("pbp_b16c_maxplan_cmp_amt"):
        parts.append("no annual max")
    return "; ".join(parts)


def vision(plan):
    s = "pbp_b17_eye_exams_wear"
    r = first(plan, s)
    parts = []
    if mandatory(r, "pbp_b17a_bendesc_amo_rex"):
        parts.append(f"exam {span(r.get('pbp_b17a_copay_amt_rex_min'), r.get('pbp_b17a_copay_amt_rex_max'), money) or '$0'}"
                     f"{per(s, r, 'pbp_b17a_bendesc_per_rex')}")
    if r.get("pbp_b17b_comb_maxplan_amt"):
        parts.append(f"eyewear {money(num(r['pbp_b17b_comb_maxplan_amt']))}{per(s, r, 'pbp_b17b_comb_maxplan_per')}")
    elif r.get("pbp_b17b_indv_maxplan_amt_egf") or r.get("pbp_b17b_indv_maxplan_amt_cl"):
        amt = r.get("pbp_b17b_indv_maxplan_amt_egf") or r["pbp_b17b_indv_maxplan_amt_cl"]
        field = "pbp_b17b_indv_maxplan_per_egf" if r.get("pbp_b17b_indv_maxplan_amt_egf") else "pbp_b17b_indv_maxplan_per_cl"
        parts.append(f"eyewear {money(num(amt))}{per(s, r, field)} per item type")
    elif any(mandatory(r, k) for k in r if k.startswith("pbp_b17b_bendesc_amo")):
        eyewear = [k for k in r if k.startswith("pbp_b17b_copay_amt_") and not k.startswith("pbp_b17b_copay_amt_mc")]
        parts.append(f"eyewear {costs(r, eyewear)}")
    return "; ".join(parts)


def hearing(plan):
    s = "pbp_b18_hearing_exams_aids"
    r = first(plan, s)
    parts = []
    if mandatory(r, "pbp_b18a_bendesc_amo_rht"):
        parts.append(f"exam {span(r.get('pbp_b18a_copay_amt_rht'), r.get('pbp_b18a_copay_amt_max_rht'), money) or '$0'}")
    if mandatory(r, "pbp_b18b_bendesc_amo_at"):
        aids = span(r.get("pbp_b18b_copay_at_min_amt"), r.get("pbp_b18b_copay_at_max_amt"), money) or "$0"
        if r.get("pbp_b18b_maxplan_amt"):
            ear = " per ear" if r.get("pbp_b18b_maxplan_perear") == "1" else ""
            aids = f"allowance {money(num(r['pbp_b18b_maxplan_amt']))}{ear}{per(s, r, 'pbp_b18b_maxplan_per')}"
        count = f"; {r['pbp_b18b_bendesc_numv_at']} aids{per(s, r, 'pbp_b18b_bendesc_per_at')}" \
            if r.get("pbp_b18b_bendesc_numv_at") else ""
        parts.append(f"aids {aids}{count}")
    return "; ".join(parts)


def visits(stem, row, num_field, per_field):
    return f" {row[num_field]} visits{per(stem, row, per_field)}" if row.get(num_field) else ""


def alt_care(plan):
    b13, b7, b14 = (first(plan, s) for s in ("pbp_b13_other_services", "pbp_b7_health_prof", "pbp_b14_preventive"))
    b4 = first(plan, "pbp_b4_emerg_urgent")
    parts = []
    if b13.get("pbp_b13a_bendesc_yn") == "1" and mandatory(b13, "pbp_b13a_bendesc_amo"):
        parts.append(f"Acup {span(b13.get('pbp_b13a_copay_amt_min'), b13.get('pbp_b13a_copay_amt_max'), money) or '$0'}"
                     f"{visits('pbp_b13_other_services', b13, 'pbp_b13a_bendesc_numv', 'pbp_b13a_bendesc_per')}")
    if flag(b7, "pbp_b7b_bendesc_ehc", 2) and mandatory(b7, "pbp_b7b_bendesc_amo_rc"):
        parts.append(f"Chiro {span(b7.get('pbp_b7b_copay_rc_amt_min'), b7.get('pbp_b7b_copay_rc_amt_max'), money) or '$0'}"
                     f"{visits('pbp_b7_health_prof', b7, 'pbp_b7b_bendesc_num_rc', 'pbp_b7b_bendesc_per_rc')}")
    if "14c18" in b14.get("pbp_b14c_bendesc_ehc", ""):
        parts.append("Massage")
    if b13.get("pbp_b13b_bendesc_otc") == "1":
        amt = money(num(b13["pbp_b13b_maxplan_amt"])) if b13.get("pbp_b13b_maxplan_amt") else "covered"
        parts.append(f"OTC {amt}{per('pbp_b13_other_services', b13, 'pbp_b13b_otc_maxplan_per')}")
    if b4.get("pbp_b4c_bendesc_yn") == "1":
        er = span(b4.get("pbp_b4c_copay_amt_wec_min"), b4.get("pbp_b4c_copay_amt_wec_max"), money) or "$0"
        cap = f", {money(num(b4['pbp_b4c_wwc_maxplan_amt']))} max" if b4.get("pbp_b4c_wwc_maxplan_amt") else ""
        parts.append(f"Worldwide ER {er}{cap}")
    return "; ".join(parts)


def extras(plan):
    b14, b10 = (first(plan, s) for s in ("pbp_b14_preventive", "pbp_b10_amb_trans"))
    b13 = first(plan, "pbp_b13_other_services")
    parts = []
    if "14c4" in b14.get("pbp_b14c_bendesc_ehc", ""):
        parts.append("Fitness")
    if b10.get("pbp_b10b_bendesc_yn") == "1":
        trips = f" {b10['pbp_b10b_bendesc_amt_al']} trips{per('pbp_b10_amb_trans', b10, 'pbp_b10b_bendesc_per_al')}" \
            if b10.get("pbp_b10b_bendesc_amt_al") else ""
        parts.append(f"Transportation{trips}")
    if mandatory(b13, "pbp_b13c_bendesc_amo"):
        parts.append("Meals")
    for stem, label in (("pbp_b7_health_prof", ""), ("pbp_b7_b19b_health_prof_vbid_uf", " (targeted)")):
        foot = first(plan, stem)
        if mandatory(foot, "pbp_b7f_bendesc_amo_rf"):
            n = f" {foot['pbp_b7f_bendesc_amt_rf']}{per(stem, foot, 'pbp_b7f_bendesc_per_rf')}" \
                if foot.get("pbp_b7f_bendesc_amt_rf") else ""
            cost = span(foot.get("pbp_b7f_copay_rf_amt_min"), foot.get("pbp_b7f_copay_rf_amt_max"), money) or "$0"
            parts.append(f"Routine foot care {cost}{n}{label}")
    if plan.get("pbp_b13i_b19b_services_vbid_ssbci") or plan.get("pbp_b13i_b19b_other_services_vbid_ssbci"):
        parts.append("SSBCI benefits for qualifying chronic conditions")
    for package in plan.get("pbp_b19b_model_test_vbid_uf", []):
        if package.get("pbp_b19b_package_name"):
            parts.append(f"For qualifying members: {package['pbp_b19b_package_name']}")
    return "; ".join(parts)


def optional_packages(plan):
    out = []
    for o in plan.get("pbp_Section_D_opt", []):
        cap = f", max {money(num(o['pbp_d_opt_maxplan_ben_cov_amt']))}" if o.get("pbp_d_opt_maxplan_ben_cov_amt") else ""
        out.append(f"{o.get('pbp_d_opt_name', 'Package')} {money(num(o['pbp_d_amt_opt_premium']))}/mo{cap}")
    return "; ".join(out)


def dvha_row(landscape, plan):
    return {
        "section": landscape["section"], "plan_id": landscape["plan_id"], "plan_name": landscape["plan_name"],
        "C_premium": landscape["premium"], "D_premium_full_extra_help": landscape["premium_full_extra_help"],
        "E_optional_packages": optional_packages(plan), "F_dental": dental(plan), "G_vision": vision(plan),
        "H_hearing": hearing(plan), "I_alt_care_otc_travel": alt_care(plan), "J_extra_benefits": extras(plan),
    }


def sheet(plans, data):
    return main_chart.sheet(plans, data, dvha_row, dvha=True)


def main(plans_csv, pbp_dir, out_csv):
    global DICTIONARY
    DICTIONARY = pbp.load_dictionary(pbp_dir)
    plans = list(csv.DictReader(open(plans_csv)))
    data = pbp.load(pbp_dir, [p["plan_id"] for p in plans])
    write_csv(out_csv, sheet(plans, data))


if __name__ == "__main__":
    main(*sys.argv[1:])
