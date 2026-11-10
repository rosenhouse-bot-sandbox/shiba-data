"""Turns each plan's CMS fields into facts with source PBP or Landscape.

Usage: python3 -I pbp_facts.py <plans.csv> <landscape_reads.csv> <pbp_dir> <out.csv>
Section 8b prices the plan's network. Section C's out-of-network and point-of-service groups price the rest.
plans.csv gives the premiums and drug deductible, and landscape_reads.csv names the Landscape fields behind them.
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


def fact(plan_id, benefit, network, cost_kind, value, fields, source="PBP", condition="", **more):
    row = dict(plan_id=plan_id, benefit=benefit, setting="any", network=network, provider_tier="", condition=condition,
               package="", pool="", covered_by="medicare", cost_kind=cost_kind, amount=value, unit="", limit="",
               source=source, doc_sha="", page="", quotes=json.dumps(list(fields)), note="") | more
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


# The drug tier in each position of mrx_alt_no_ded_tier
TIER_POSITIONS = {2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6, 1: 7}


def plan_facts(landscape, reads, plan):
    """reads are landscape_reads.csv rows."""
    plan_id = landscape["plan_id"]

    def fields(column):
        return [r["field"] for r in reads if r["plan_id"] == plan_id and r["plan_field"] == column]

    def landscape_fact(benefit, cost_kind, value, column, condition="", more=()):
        return fact(plan_id, benefit, "any", cost_kind, value, fields(column) + list(more), "Landscape", condition)

    found = [landscape_fact("plan_premium", "premium", landscape["premium"], "premium")]
    if landscape["premium_full_extra_help"] != "n/a":
        found.append(landscape_fact("plan_premium", "premium", landscape["premium_full_extra_help"],
                                    "premium_full_extra_help", "full Extra Help"))
    if landscape["part_d_deductible"] == "n/a":
        found.append(landscape_fact("part_d_deductible", "not_covered", "", "part_d_deductible"))
    else:
        bits = first(plan, "pbp_mrx").get("mrx_alt_no_ded_tier", "")
        tiers = sorted(TIER_POSITIONS[i] for i, bit in enumerate(bits[:7], 1) if bit == "1")
        skips = tiers and landscape["part_d_deductible"] != "$0"
        found.append(landscape_fact("part_d_deductible", "deductible", landscape["part_d_deductible"],
                                    "part_d_deductible", f"not tiers {','.join(map(str, tiers))}" if skips else "",
                                    ["mrx_alt_no_ded_tier"] if skips else []))
    d = first(plan, "pbp_Section_D")
    for network, name in (("in", "pbp_d_out_pocket_amt"), ("any", "pbp_d_comb_max_enr_amt")):
        if d.get(name):
            found.append(fact(plan_id, "moop", network, "out_of_pocket_max", money(float(d[name])), [name]))
    return found


def deductible_facts(plan_id, plan):
    d = first(plan, "pbp_Section_D")
    if d.get("pbp_d_inn_deduct_yn") == "1":
        network, is_part_b, every = "in", d.get("pbp_d_inn_deduct_partb_yn") == "1", "pbp_d_inn_deduct_m_yn"
        fields = ["pbp_d_inn_deduct_partb_yn" if is_part_b else "pbp_d_inn_deduct_amt", every]
        amount = "" if is_part_b else money(float(d["pbp_d_inn_deduct_amt"]))
        part_b_fields = ["pbp_d_inn_deduct_partb_yn"]
    elif d.get("pbp_d_ann_deduct_yn") == "1":
        in_network = d.get("pbp_d_ann_deduct_bens", "")[1:2] == "1" or d.get("pbp_d_ann_deduct_inn_mc_yn") == "1"
        network, is_part_b, every = "any" if in_network else "out", d.get("pbp_d_ann_deduct_amt_type") == "2", \
            "pbp_d_ann_deduct_inn_mc_yn"
        fields = ["pbp_d_ann_deduct_amt_type" if is_part_b else "pbp_d_ann_deduct_amt"]
        fields += [n for n in ("pbp_d_ann_deduct_bens", every) if d.get(n)]
        amount = "" if is_part_b else money(float(d["pbp_d_ann_deduct_amt"]))
        part_b_fields = ["pbp_d_ann_deduct_amt_type"]
    else:
        zero = [n for n in ("pbp_d_inn_deduct_yn", "pbp_d_ann_deduct_yn") if d.get(n) == "2"]
        return [fact(plan_id, "medical_deductible", "in", "deductible", "$0", zero)] if zero else []
    some = network != "out" and d.get(every) != "1"
    # The PBP does not give the Part B deductible's amount.
    found = [fact(plan_id, "medical_deductible.some" if some else "medical_deductible", network,
                  "covered" if is_part_b else "deductible", amount, fields)]
    return found + ([fact(plan_id, "medical_deductible.part_b", network, "covered", "", part_b_fields)] if is_part_b else [])


# The PBP period codes whose words present.every reads
PERIODS = {"1": "every three years", "2": "every two years", "3": "every year", "4": "every six months",
           "5": "every three months", "7": "every month"}


def supplemental_facts(plan_id, plan):
    """Facts for the dental maximum and worldwide emergency care."""
    found = []
    dental = first(plan, "pbp_b16_dental")
    shared = dental.get("pbp_b16c_maxplan_cmp_type") == "1"
    for benefit, amt, per, more in (("dental" if shared else "dental.preventive", "pbp_b16b_maxplan_pv_amt",
                                     "pbp_b16b_maxplan_pv_per", ["pbp_b16c_maxplan_cmp_type"]),
                                    ("dental.comprehensive", "pbp_b16c_maxplan_cmp_amt", "pbp_b16c_maxplan_cmp_per", [])):
        # A maximum shared with other benefits names no pool here, so it is left out.
        if dental.get(amt) and dental.get("pbp_b16b_maxplan_excl_csg_yn") != "1":
            limit = PERIODS.get(dental.get(per), "")
            fields = [amt] + ([per] if limit else []) + [n for n in more if dental.get(n)]
            found.append(fact(plan_id, benefit, "in", "max", money(float(dental[amt])), fields, covered_by="supplemental",
                              limit=limit))
    er = first(plan, "pbp_b4_emerg_urgent")
    if er.get("pbp_b4c_bendesc_yn") == "1":
        copay = ["pbp_b4c_copay_amt_wec_min", "pbp_b4c_copay_amt_wec_max"]
        for kind, names in (("copay", copay), ("max", ["pbp_b4c_wwc_maxplan_amt"])):
            if amount(er, names, money):
                found.append(fact(plan_id, "emergency", "any", kind, amount(er, names, money), names,
                                  setting="outside_us", covered_by="supplemental"))
    return found


def facts_for(plan_id, plan):
    rows = plan.get(B8, [])
    if len(rows) != 1:
        raise ValueError(f"{plan_id}: {len(rows)} rows in {B8}, not 1")
    refuse_unmodeled(plan_id, rows[0])
    return in_network(plan_id, rows[0]) + out_of_network(plan_id, plan)


def main(plans_csv, reads_csv, pbp_dir, out_csv):
    with open(plans_csv, newline="") as f:
        plans = list(csv.DictReader(f))
    with open(reads_csv, newline="") as f:
        reads = list(csv.DictReader(f))
    data = pbp.load(pbp_dir, [p["plan_id"] for p in plans])
    facts.write(out_csv, [row for p in plans for row in
                          facts_for(p["plan_id"], data[p["plan_id"]]) + plan_facts(p, reads, data[p["plan_id"]])
                          + deductible_facts(p["plan_id"], data[p["plan_id"]])
                          + supplemental_facts(p["plan_id"], data[p["plan_id"]])])


if __name__ == "__main__":
    main(*sys.argv[1:])
