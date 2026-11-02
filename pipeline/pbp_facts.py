"""Turns each plan's PBP section 8b fields into facts with source PBP.

Usage: python3 -I pbp_facts.py <plans.csv> <pbp_dir> <out.csv>
Section 8b prices the plan's network. Section C's out-of-network groups price the rest.
"""
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import facts  # noqa: E402
import pbp  # noqa: E402

B8 = "pbp_b8_clin_diag_ther"
OON = "pbp_Section_C_OON"
# benefit: (position in the 8b service bits, copay fields, coinsurance fields, out-of-network category)
SERVICES = {
    "imaging.xray": (1, ("pbp_b8b_copay_mc_amt", "pbp_b8b_copay_mc_amt_max"),
                     ("pbp_b8b_coins_pct_cmc", "pbp_b8b_coins_pct_cmc_max"), "8b3"),
    "imaging.diagnostic": (2, ("pbp_b8b_copay_amt_drs", "pbp_b8b_copay_amt_drs_max"),
                           ("pbp_b8b_coins_pct_drs", "pbp_b8b_coins_pct_drs_max"), "8b1"),
    "radiation_therapy": (3, ("pbp_b8b_copay_amt_tmc", "pbp_b8b_copay_amt_tmc_max"),
                          ("pbp_b8b_coins_pct_tmc", "pbp_b8b_coins_pct_tmc_max"), "8b2"),
}
OON_COPAY = ("pbp_c_oon_outpt_copay_min_amt", "pbp_c_oon_outpt_copay_max_amt")
OON_COINS = ("pbp_c_oon_outpt_coins_min_pct", "pbp_c_oon_outpt_coins_max_pct")
UNMODELED = ("pbp_b8b_ded_yn", "pbp_b8b_maxenr_yn", "pbp_c_oon_outpt_ded_yn", "pbp_c_oon_outpt_maxplan_yn")


def money(x):
    return f"${x:,.2f}".replace(".00", "")


def percent(x):
    return f"{x:g}%"


def amount(row, names, fmt):
    """The min and max fields as one amount or a range, or "" if neither is set."""
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
    """Copay and coinsurance facts, or a $0 copay quoting the free fields when the row sets neither."""
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


def out_of_network(plan_id, groups):
    found = []
    for group in groups:
        categories = group.get("pbp_c_oon_out_mc_bendesc_cats", "").split(";")
        for benefit, (*_, category) in SERVICES.items():
            if category in categories:
                refuse_unmodeled(plan_id, group)
                free = ("pbp_c_oon_outpt_copay_yn", "pbp_c_oon_outpt_coins_yn")
                found += cost_sharing(plan_id, benefit, "out", group, OON_COPAY, OON_COINS, free)
    return found


def facts_for(plan_id, plan):
    rows = plan.get(B8, [])
    if len(rows) != 1:
        raise ValueError(f"{plan_id}: {len(rows)} rows in {B8}, not 1")
    refuse_unmodeled(plan_id, rows[0])
    return in_network(plan_id, rows[0]) + out_of_network(plan_id, plan.get(OON, []))


def main(plans_csv, pbp_dir, out_csv):
    with open(plans_csv, newline="") as f:
        plan_ids = [p["plan_id"] for p in csv.DictReader(f)]
    data = pbp.load(pbp_dir, plan_ids)
    facts.write(out_csv, [row for p in plan_ids for row in facts_for(p, data[p])])


if __name__ == "__main__":
    main(*sys.argv[1:])
