"""Turns each plan's PBP section 8b fields into facts with source PBP.

Usage: python3 -I pbp_facts.py <plans.csv> <pbp_dir> <out.csv>
Section 8b prices the plan's network. Section C's out-of-network and point-of-service groups price the rest.
"""
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import facts  # noqa: E402
import pbp  # noqa: E402

B8 = "pbp_b8_clin_diag_ther"
# Each benefit maps to its position in the 8b service bits, its copay and coinsurance fields, and its Section C category.
SERVICES = {
    "imaging.xray": (1, ("pbp_b8b_copay_mc_amt", "pbp_b8b_copay_mc_amt_max"),
                     ("pbp_b8b_coins_pct_cmc", "pbp_b8b_coins_pct_cmc_max"), "8b3"),
    "imaging.diagnostic": (2, ("pbp_b8b_copay_amt_drs", "pbp_b8b_copay_amt_drs_max"),
                           ("pbp_b8b_coins_pct_drs", "pbp_b8b_coins_pct_drs_max"), "8b1"),
    "radiation_therapy": (3, ("pbp_b8b_copay_amt_tmc", "pbp_b8b_copay_amt_tmc_max"),
                          ("pbp_b8b_coins_pct_tmc", "pbp_b8b_coins_pct_tmc_max"), "8b2"),
}
# Each Section C file maps to its categories field, copay fields, coinsurance fields and the yes-no fields for them.
GROUPS = {
    "pbp_Section_C_OON": ("pbp_c_oon_out_mc_bendesc_cats",
                          ("pbp_c_oon_outpt_copay_min_amt", "pbp_c_oon_outpt_copay_max_amt"),
                          ("pbp_c_oon_outpt_coins_min_pct", "pbp_c_oon_outpt_coins_max_pct"),
                          ("pbp_c_oon_outpt_copay_yn", "pbp_c_oon_outpt_coins_yn")),
    "pbp_Section_C_POS": ("pbp_c_pos_outpt_mc_bencats",
                          ("pbp_c_pos_outpt_copay_min_amt", "pbp_c_pos_outpt_copay_max_amt"),
                          ("pbp_c_pos_outpt_coins_min_pct", "pbp_c_pos_outpt_coins_max_pct"),
                          ("pbp_c_pos_outpt_copay_yn", "pbp_c_pos_outpt_coins_yn")),
}
UNMODELED = ("pbp_b8b_ded_yn", "pbp_b8b_maxenr_yn", "pbp_c_oon_outpt_ded_yn", "pbp_c_oon_outpt_maxplan_yn",
             "pbp_c_pos_outpt_deduct_yn", "pbp_c_pos_outpt_maxplan_yn")


def money(x):
    return f"${x:,.2f}".replace(".00", "")


def percent(x):
    return f"{x:g}%"


def amount(row, names, fmt):
    """Returns one amount, a range of the min and max fields, or "" if neither is set."""
    values = sorted({float(row[n]) for n in names if row.get(n)})
    if not values:
        return ""
    return fmt(values[0]) if len(values) == 1 else f"{fmt(values[0])}-{fmt(values[-1])}"


def fact(plan_id, benefit, network, cost_kind, value, fields):
    row = dict(plan_id=plan_id, benefit=benefit, setting="any", network=network, provider_tier="", condition="",
               package="", pool="", covered_by="medicare", cost_kind=cost_kind, amount=value, unit="", limit="",
               source="PBP", doc_sha="", page="", quotes=json.dumps(list(fields)), note="")
    return dict(row, fact_id=facts.fact_id(row))


def cost_sharing(plan_id, benefit, network, row, copay, coins, free):
    """Returns copay and coinsurance facts. A row with neither gets a $0 copay that quotes the free fields."""
    found = [fact(plan_id, benefit, network, kind, value, [n for n in names if row.get(n)])
             for kind, names, value in (("copay", copay, amount(row, copay, money)),
                                        ("coinsurance", coins, amount(row, coins, percent))) if value]
    return found or [fact(plan_id, benefit, network, "copay", "$0", [n for n in free if row.get(n)])]


def refuse_unmodeled(plan_id, row):
    for name in UNMODELED:
        if row.get(name) == "1":
            raise ValueError(f"{plan_id}: {name} is 1, which pbp_facts.py does not turn into facts")


def in_network(plan_id, row):
    found = []
    for benefit, (bit, copay, coins, _) in SERVICES.items():
        for names, bits in ((copay, "pbp_b8b_copay_ehc"), (coins, "pbp_b8b_coins_ehc")):
            if any(row.get(n) for n in names) != (row.get(bits, "")[bit - 1:bit] == "1"):
                raise ValueError(f"{plan_id}: {bits} disagrees with {names} for {benefit}")
        free = ("pbp_b8b_copay_yn", "pbp_b8b_copay_ehc", "pbp_b8b_coins_yn", "pbp_b8b_coins_ehc")
        found += cost_sharing(plan_id, benefit, "in", row, copay, coins, free)
    return found


def out_of_network(plan_id, plan):
    found = []
    for stem, (cats, copay, coins, free) in GROUPS.items():
        for group in plan.get(stem, []):
            categories = group.get(cats, "").split(";")
            for benefit, (*_, category) in SERVICES.items():
                if category in categories:
                    refuse_unmodeled(plan_id, group)
                    found += cost_sharing(plan_id, benefit, "out", group, copay, coins, free)
    if first(plan, "pbp_Section_C").get("pbp_c_oon_yn") == "1":
        missing = set(SERVICES) - {r["benefit"] for r in found}
        if missing:
            raise ValueError(f"{plan_id}: pbp_c_oon_yn is 1, but no out-of-network group prices {sorted(missing)}")
    return found


def first(plan, stem):
    return (plan.get(stem) or [{}])[0]


def facts_for(plan_id, plan):
    rows = plan.get(B8, [])
    if len(rows) != 1:
        raise ValueError(f"{plan_id}: {len(rows)} rows in {B8}, not 1")
    refuse_unmodeled(plan_id, rows[0])
    return in_network(plan_id, rows[0]) + out_of_network(plan_id, plan)


def main(plans_csv, pbp_dir, out_csv):
    with open(plans_csv, newline="") as f:
        plan_ids = [p["plan_id"] for p in csv.DictReader(f)]
    data = pbp.load(pbp_dir, plan_ids)
    facts.write(out_csv, [row for p in plan_ids for row in facts_for(p, data[p])])


if __name__ == "__main__":
    main(*sys.argv[1:])
