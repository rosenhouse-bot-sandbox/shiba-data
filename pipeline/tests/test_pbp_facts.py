import json, os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import expected
import facts
import layers
import pbp_facts
import years

PLAN = "H1111-001-0"


def b8b(**fields):
    row = dict(pbp_b8b_copay_yn="2", pbp_b8b_coins_yn="2", pbp_b8b_ded_yn="2", pbp_b8b_maxenr_yn="2")
    row.update(fields)
    return {"pbp_b8_clin_diag_ther": [row]}


def oon(cats, **fields):
    row = dict(pbp_c_oon_out_mc_bendesc_cats=cats, pbp_c_oon_outpt_copay_yn="2", pbp_c_oon_outpt_coins_yn="2",
               pbp_c_oon_outpt_ded_yn="2")
    row.update(fields)
    return row


def terms(rows):
    return sorted((r["benefit"], r["network"], r["cost_kind"], r["amount"], tuple(json.loads(r["quotes"])))
                  for r in rows)


class FactsTest(unittest.TestCase):
    def test_turns_a_zero_width_range_into_one_amount(self):
        plan = b8b(pbp_b8b_copay_yn="1", pbp_b8b_copay_ehc="100", pbp_b8b_copay_mc_amt="30.00",
                   pbp_b8b_copay_mc_amt_max="30.00")
        self.assertIn(("imaging.xray", "in", "copay", "$30", ("pbp_b8b_copay_mc_amt", "pbp_b8b_copay_mc_amt_max")),
                      terms(pbp_facts.facts_for(PLAN, plan)))

    def test_turns_a_min_and_max_into_a_range(self):
        plan = b8b(pbp_b8b_copay_yn="1", pbp_b8b_copay_ehc="010", pbp_b8b_copay_amt_drs="0.00",
                   pbp_b8b_copay_amt_drs_max="1250.50")
        self.assertIn(("imaging.diagnostic", "in", "copay", "$0-$1,250.50",
                       ("pbp_b8b_copay_amt_drs", "pbp_b8b_copay_amt_drs_max")), terms(pbp_facts.facts_for(PLAN, plan)))

    def test_reads_coinsurance_for_each_service(self):
        plan = b8b(pbp_b8b_coins_yn="1", pbp_b8b_coins_ehc="111",
                   pbp_b8b_coins_pct_cmc="20", pbp_b8b_coins_pct_cmc_max="20",
                   pbp_b8b_coins_pct_drs="10", pbp_b8b_coins_pct_drs_max="12.5",
                   pbp_b8b_coins_pct_tmc="20", pbp_b8b_coins_pct_tmc_max="20")
        self.assertEqual(terms(pbp_facts.facts_for(PLAN, plan)), [
            ("imaging.diagnostic", "in", "coinsurance", "10%-12.5%",
             ("pbp_b8b_coins_pct_drs", "pbp_b8b_coins_pct_drs_max")),
            ("imaging.xray", "in", "coinsurance", "20%", ("pbp_b8b_coins_pct_cmc", "pbp_b8b_coins_pct_cmc_max")),
            ("radiation_therapy", "in", "coinsurance", "20%", ("pbp_b8b_coins_pct_tmc", "pbp_b8b_coins_pct_tmc_max")),
        ])

    def test_a_service_can_have_a_copay_and_coinsurance(self):
        plan = b8b(pbp_b8b_copay_yn="1", pbp_b8b_copay_ehc="100", pbp_b8b_copay_mc_amt="5.00",
                   pbp_b8b_coins_yn="1", pbp_b8b_coins_ehc="100", pbp_b8b_coins_pct_cmc_max="20")
        xray = [t[2:4] for t in terms(pbp_facts.facts_for(PLAN, plan)) if t[0] == "imaging.xray"]
        self.assertEqual(xray, [("coinsurance", "20%"), ("copay", "$5")])

    def test_a_service_with_no_cost_sharing_has_a_zero_copay(self):
        plan = b8b(pbp_b8b_copay_yn="1", pbp_b8b_copay_ehc="010", pbp_b8b_copay_amt_drs="10.00",
                   pbp_b8b_coins_yn="1", pbp_b8b_coins_ehc="001", pbp_b8b_coins_pct_tmc="20")
        xray = [t for t in terms(pbp_facts.facts_for(PLAN, plan)) if t[0] == "imaging.xray"]
        self.assertEqual(xray, [("imaging.xray", "in", "copay", "$0",
                                 ("pbp_b8b_copay_yn", "pbp_b8b_copay_ehc", "pbp_b8b_coins_yn", "pbp_b8b_coins_ehc"))])

    def test_reads_out_of_network_groups_by_category(self):
        plan = dict(b8b(), pbp_Section_C_OON=[
            oon("8a1;8b1;", pbp_c_oon_outpt_coins_yn="1", pbp_c_oon_outpt_coins_min_pct="30",
                pbp_c_oon_outpt_coins_max_pct="50"),
            oon("8b3;", pbp_c_oon_outpt_copay_yn="1", pbp_c_oon_outpt_copay_min_amt="0.00",
                pbp_c_oon_outpt_copay_max_amt="0.00", pbp_c_oon_outpt_coins_yn="1",
                pbp_c_oon_outpt_coins_min_pct="50", pbp_c_oon_outpt_coins_max_pct="50"),
            oon("8b2;")])
        out = [t for t in terms(pbp_facts.facts_for(PLAN, plan)) if t[1] == "out"]
        self.assertEqual(out, [
            ("imaging.diagnostic", "out", "coinsurance", "30%-50%",
             ("pbp_c_oon_outpt_coins_min_pct", "pbp_c_oon_outpt_coins_max_pct")),
            ("imaging.xray", "out", "coinsurance", "50%",
             ("pbp_c_oon_outpt_coins_min_pct", "pbp_c_oon_outpt_coins_max_pct")),
            ("imaging.xray", "out", "copay", "$0",
             ("pbp_c_oon_outpt_copay_min_amt", "pbp_c_oon_outpt_copay_max_amt")),
            ("radiation_therapy", "out", "copay", "$0", ("pbp_c_oon_outpt_copay_yn", "pbp_c_oon_outpt_coins_yn")),
        ])

    def test_reads_point_of_service_groups_as_out_of_network(self):
        plan = dict(b8b(), pbp_Section_C_POS=[dict(
            pbp_c_pos_outpt_mc_bencats="8a1;8b1;8b3;14e5;", pbp_c_pos_outpt_copay_yn="1",
            pbp_c_pos_outpt_copay_min_amt="25.00", pbp_c_pos_outpt_copay_max_amt="25.00",
            pbp_c_pos_outpt_coins_yn="2")])
        out = [t for t in terms(pbp_facts.facts_for(PLAN, plan)) if t[1] == "out"]
        fields = ("pbp_c_pos_outpt_copay_min_amt", "pbp_c_pos_outpt_copay_max_amt")
        self.assertEqual(out, [("imaging.diagnostic", "out", "copay", "$25", fields),
                               ("imaging.xray", "out", "copay", "$25", fields)])

    def test_refuses_a_plan_with_out_of_network_benefits_that_do_not_price_a_service(self):
        plan = dict(b8b(), pbp_Section_C=[dict(pbp_c_oon_yn="1")], pbp_Section_C_OON=[oon("8b1;"), oon("8b3;")])
        with self.assertRaises(ValueError):
            pbp_facts.facts_for(PLAN, plan)
        plan["pbp_Section_C_OON"].append(oon("8b2;"))
        self.assertEqual(len(pbp_facts.facts_for(PLAN, plan)), 6)

    def test_every_row_is_a_medicare_pbp_fact_for_any_setting(self):
        plan = dict(b8b(pbp_b8b_coins_yn="1", pbp_b8b_coins_ehc="001", pbp_b8b_coins_pct_tmc="20"),
                    pbp_Section_C_OON=[oon("8b1;")])
        rows = pbp_facts.facts_for(PLAN, plan)
        self.assertEqual(len(rows), 4)
        for row in rows:
            self.assertEqual(facts.check(row), [])
            self.assertEqual((row["plan_id"], row["setting"], row["covered_by"], row["source"]),
                             (PLAN, "any", "medicare", "PBP"))

    def test_refuses_a_service_bit_without_amounts_or_amounts_without_a_bit(self):
        for plan in (b8b(pbp_b8b_copay_yn="1", pbp_b8b_copay_ehc="100"),
                     b8b(pbp_b8b_copay_yn="1", pbp_b8b_copay_ehc="100", pbp_b8b_copay_amt_drs="5.00",
                         pbp_b8b_copay_mc_amt="5.00")):
            with self.subTest(plan), self.assertRaises(ValueError):
                pbp_facts.facts_for(PLAN, plan)

    def test_refuses_terms_it_does_not_turn_into_facts(self):
        for plan in (b8b(pbp_b8b_ded_yn="1"), b8b(pbp_b8b_maxenr_yn="1"),
                     dict(b8b(), pbp_Section_C_OON=[oon("8b1;", pbp_c_oon_outpt_ded_yn="1")]),
                     dict(b8b(), pbp_Section_C_OON=[oon("8b1;", pbp_c_oon_outpt_maxplan_yn="1")]),
                     dict(b8b(), pbp_Section_C_POS=[dict(pbp_c_pos_outpt_mc_bencats="8b1;",
                                                         pbp_c_pos_outpt_deduct_yn="1")])):
            with self.subTest(plan), self.assertRaises(ValueError):
                pbp_facts.facts_for(PLAN, plan)

    def test_refuses_a_plan_without_one_section_8_row(self):
        for plan in ({}, {"pbp_b8_clin_diag_ther": [{}, {}]}):
            with self.subTest(plan), self.assertRaises(ValueError):
                pbp_facts.facts_for(PLAN, plan)


class MainTest(unittest.TestCase):
    def test_writes_each_plans_facts_from_the_pbp_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(f"{tmp}/plans.csv", "w") as f:
                f.write(f"plan_id,premium,premium_full_extra_help,part_d_deductible\n{PLAN},$0,n/a,n/a\n")
            with open(f"{tmp}/reads.csv", "w") as f:
                f.write(f"plan_id,plan_field,field,value\n{PLAN},premium,Part C Premium,$0.00\n"
                        f"{PLAN},part_d_deductible,Part D Coverage Indicator,No\n")
            os.mkdir(f"{tmp}/pbp")
            with open(f"{tmp}/pbp/pbp_b8_clin_diag_ther.txt", "w") as f:
                f.write("pbp_a_hnumber\tpbp_a_plan_identifier\tsegment_id\tpbp_b8b_copay_yn\tpbp_b8b_coins_yn\n"
                        "H1111\t001\t0\t2\t2\n")
            pbp_facts.main(f"{tmp}/plans.csv", f"{tmp}/reads.csv", f"{tmp}/pbp", f"{tmp}/out.csv", "$283")
            rows = facts.read(f"{tmp}/out.csv")
        self.assertEqual([(r["plan_id"], r["benefit"], r["amount"]) for r in rows],
                         [(PLAN, "imaging.diagnostic", "$0"), (PLAN, "imaging.xray", "$0"),
                          (PLAN, "part_d_deductible", ""), (PLAN, "plan_premium", "$0"), (PLAN, "radiation_therapy", "$0")])


LANDSCAPE = dict(plan_id=PLAN, premium="$12.50", premium_full_extra_help="$1.20", part_d_deductible="$615")
READS = [dict(plan_id=PLAN, plan_field=k, field=f"Landscape {k}", value="") for k in LANDSCAPE if k != "plan_id"]


def plan_terms(rows):
    return sorted((r["benefit"], r["network"], r["condition"], r["cost_kind"], r["amount"], r["source"],
                   tuple(json.loads(r["quotes"]))) for r in rows)


class PlanFactsTest(unittest.TestCase):
    def test_landscape_gives_the_premiums_and_drug_deductible(self):
        self.assertEqual(plan_terms(pbp_facts.plan_facts(LANDSCAPE, READS, {})), [
            ("part_d_deductible", "any", "", "deductible", "$615", "Landscape", ("Landscape part_d_deductible",)),
            ("plan_premium", "any", "", "premium", "$12.50", "Landscape", ("Landscape premium",)),
            ("plan_premium", "any", "full Extra Help", "premium", "$1.20", "Landscape",
             ("Landscape premium_full_extra_help",))])

    def test_a_plan_without_part_d_does_not_cover_it_or_charge_an_extra_help_premium(self):
        found = pbp_facts.plan_facts(dict(LANDSCAPE, premium_full_extra_help="n/a", part_d_deductible="n/a"), READS, {})
        self.assertEqual([(r["benefit"], r["condition"], r["cost_kind"], r["amount"]) for r in found],
                         [("plan_premium", "", "premium", "$12.50"), ("part_d_deductible", "", "not_covered", "")])

    def test_names_the_drug_tiers_without_a_deductible(self):
        plan = {"pbp_mrx": [dict(mrx_alt_no_ded_tier="0110000")]}
        (ded,) = [r for r in pbp_facts.plan_facts(LANDSCAPE, READS, plan) if r["benefit"] == "part_d_deductible"]
        self.assertEqual((ded["condition"], json.loads(ded["quotes"])),
                         ("not tiers 1,2", ["Landscape part_d_deductible", "mrx_alt_no_ded_tier"]))

    def test_the_first_tier_bit_is_tier_7(self):
        plan = {"pbp_mrx": [dict(mrx_alt_no_ded_tier="1000000")]}
        (ded,) = [r for r in pbp_facts.plan_facts(LANDSCAPE, READS, plan) if r["benefit"] == "part_d_deductible"]
        self.assertEqual(ded["condition"], "not tiers 7")

    def test_a_zero_deductible_skips_no_tiers(self):
        plan = {"pbp_mrx": [dict(mrx_alt_no_ded_tier="0110000")]}
        (ded,) = [r for r in pbp_facts.plan_facts(dict(LANDSCAPE, part_d_deductible="$0"), READS, plan)
                  if r["benefit"] == "part_d_deductible"]
        self.assertEqual((ded["condition"], json.loads(ded["quotes"])), ("", ["Landscape part_d_deductible"]))

    def test_pbp_gives_the_in_network_and_combined_moop(self):
        plan = {"pbp_Section_D": [dict(pbp_d_out_pocket_amt="5900.00", pbp_d_comb_max_enr_amt="9550.00")]}
        moop = [r for r in pbp_facts.plan_facts(LANDSCAPE, READS, plan) if r["benefit"] == "moop"]
        self.assertEqual(plan_terms(moop), [
            ("moop", "any", "", "out_of_pocket_max", "$9,550", "PBP", ("pbp_d_comb_max_enr_amt",)),
            ("moop", "in", "", "out_of_pocket_max", "$5,900", "PBP", ("pbp_d_out_pocket_amt",))])

    def test_every_plan_fact_passes_the_fact_checks(self):
        plan = {"pbp_Section_D": [dict(pbp_d_out_pocket_amt="5900.00")], "pbp_mrx": [dict(mrx_alt_no_ded_tier="1")]}
        for r in pbp_facts.plan_facts(LANDSCAPE, READS, plan):
            self.assertEqual(facts.check(r), [], r)


def deductible(**fields):
    return plan_terms(pbp_facts.deductible_facts(PLAN, {"pbp_Section_D": [fields]}, "$283"))


class DeductibleFactsTest(unittest.TestCase):
    def test_a_plan_without_a_deductible_has_a_zero_one(self):
        for fields in ({"pbp_d_inn_deduct_yn": "2"}, {"pbp_d_ann_deduct_yn": "2"}):
            self.assertEqual(deductible(**fields), [
                ("medical_deductible", "in", "", "deductible", "$0", "PBP", tuple(fields))])

    def test_an_in_network_deductible_for_some_services(self):
        self.assertEqual(deductible(pbp_d_inn_deduct_yn="1", pbp_d_inn_deduct_partb_yn="2", pbp_d_inn_deduct_amt="750.00",
                                    pbp_d_inn_deduct_m_yn="2"), [
            ("medical_deductible.some", "in", "", "deductible", "$750", "PBP",
             ("pbp_d_inn_deduct_amt", "pbp_d_inn_deduct_m_yn"))])

    def test_an_in_network_deductible_for_every_service(self):
        self.assertEqual(deductible(pbp_d_inn_deduct_yn="1", pbp_d_inn_deduct_partb_yn="2", pbp_d_inn_deduct_amt="200.00",
                                    pbp_d_inn_deduct_m_yn="1")[0][:5], ("medical_deductible", "in", "", "deductible", "$200"))

    def test_the_part_b_deductible(self):
        self.assertEqual(deductible(pbp_d_inn_deduct_yn="1", pbp_d_inn_deduct_partb_yn="1", pbp_d_inn_deduct_m_yn="2"), [
            ("medical_deductible.part_b", "in", "", "covered", "", "PBP", ("pbp_d_inn_deduct_partb_yn",)),
            ("medical_deductible.some", "in", "", "deductible", "$283", "PBP",
             ("pbp_d_inn_deduct_partb_yn", "pbp_d_inn_deduct_m_yn"))])

    def test_a_combined_deductible_for_some_in_network_services(self):
        self.assertEqual(deductible(pbp_d_ann_deduct_yn="1", pbp_d_ann_deduct_amt_type="4", pbp_d_ann_deduct_amt="250.00",
                                    pbp_d_ann_deduct_bens="010", pbp_d_ann_deduct_inn_mc_yn="2"), [
            ("medical_deductible.some", "any", "", "deductible", "$250", "PBP",
             ("pbp_d_ann_deduct_amt", "pbp_d_ann_deduct_bens", "pbp_d_ann_deduct_inn_mc_yn"))])

    def test_a_combined_part_b_deductible(self):
        self.assertEqual([t[:5] for t in deductible(pbp_d_ann_deduct_yn="1", pbp_d_ann_deduct_amt_type="2",
                                                     pbp_d_ann_deduct_bens="010", pbp_d_ann_deduct_inn_mc_yn="2")], [
            ("medical_deductible.part_b", "any", "", "covered", ""),
            ("medical_deductible.some", "any", "", "deductible", "$283")])

    def test_a_deductible_only_out_of_network(self):
        self.assertEqual(deductible(pbp_d_ann_deduct_yn="1", pbp_d_ann_deduct_amt_type="4", pbp_d_ann_deduct_amt="100.00")
                         [0][:5], ("medical_deductible", "out", "", "deductible", "$100"))

    def test_a_plan_whose_pbp_gives_no_deductible_has_no_fact(self):
        self.assertEqual(deductible(), [])

    def test_every_deductible_fact_passes_the_fact_checks(self):
        for fields in ({"pbp_d_inn_deduct_yn": "2"}, {"pbp_d_inn_deduct_yn": "1", "pbp_d_inn_deduct_partb_yn": "1"}):
            for r in pbp_facts.deductible_facts(PLAN, {"pbp_Section_D": [fields]}, "$283"):
                self.assertEqual(facts.check(r), [], r)


def supplemental_terms(rows):
    return sorted((r["benefit"], r["setting"], r["network"], r["covered_by"], r["cost_kind"], r["amount"], r["limit"],
                   tuple(json.loads(r["quotes"]))) for r in rows)


class SupplementalFactsTest(unittest.TestCase):
    def test_the_dental_maximum_and_how_often_it_renews(self):
        plan = {"pbp_b16_dental": [dict(pbp_b16b_maxplan_pv_amt="1250.00", pbp_b16b_maxplan_pv_per="3",
                                        pbp_b16c_maxplan_cmp_type="1")]}
        self.assertEqual(supplemental_terms(pbp_facts.supplemental_facts(PLAN, plan)), [
            ("dental", "any", "in", "supplemental", "max", "$1,250", "every year",
             ("pbp_b16b_maxplan_pv_amt", "pbp_b16b_maxplan_pv_per", "pbp_b16c_maxplan_cmp_type"))])

    def test_a_comprehensive_dental_maximum(self):
        plan = {"pbp_b16_dental": [dict(pbp_b16c_maxplan_cmp_type="2", pbp_b16c_maxplan_cmp_amt="1000.00",
                                        pbp_b16c_maxplan_cmp_per="2")]}
        self.assertEqual([t[:7] for t in supplemental_terms(pbp_facts.supplemental_facts(PLAN, plan))], [
            ("dental.comprehensive", "any", "in", "supplemental", "max", "$1,000", "every two years")])

    def test_a_period_no_rule_reads_gives_no_limit(self):
        plan = {"pbp_b16_dental": [dict(pbp_b16b_maxplan_pv_amt="150.00", pbp_b16b_maxplan_pv_per="5")]}
        (cap,) = pbp_facts.supplemental_facts(PLAN, plan)
        self.assertEqual((cap["limit"], json.loads(cap["quotes"])), ("", ["pbp_b16b_maxplan_pv_amt"]))

    def test_worldwide_emergency_copay_and_maximum(self):
        plan = {"pbp_b4_emerg_urgent": [dict(pbp_b4c_bendesc_yn="1", pbp_b4c_copay_amt_wec_min="130.00",
                                             pbp_b4c_copay_amt_wec_max="130.00", pbp_b4c_wwc_maxplan_amt="25000.00")]}
        self.assertEqual(supplemental_terms(pbp_facts.supplemental_facts(PLAN, plan)), [
            ("emergency", "outside_us", "any", "supplemental", "copay", "$130", "",
             ("pbp_b4c_copay_amt_wec_min", "pbp_b4c_copay_amt_wec_max")),
            ("emergency", "outside_us", "any", "supplemental", "max", "$25,000", "", ("pbp_b4c_wwc_maxplan_amt",))])

    def test_no_worldwide_coverage_gives_no_fact(self):
        plan = {"pbp_b4_emerg_urgent": [dict(pbp_b4c_bendesc_yn="2")]}
        self.assertEqual(pbp_facts.supplemental_facts(PLAN, plan), [])

    def test_every_supplemental_fact_passes_the_fact_checks(self):
        plan = {"pbp_b16_dental": [dict(pbp_b16b_maxplan_pv_amt="1250.00", pbp_b16b_maxplan_pv_per="3")],
                "pbp_b4_emerg_urgent": [dict(pbp_b4c_bendesc_yn="1", pbp_b4c_copay_amt_wec_min="0.00",
                                             pbp_b4c_copay_amt_wec_max="130.00")]}
        for r in pbp_facts.supplemental_facts(PLAN, plan):
            self.assertEqual(facts.check(r), [], r)


class ImagingCellsTest(unittest.TestCase):
    def test_facts_agree_with_every_imaging_line_built_from_the_pbp(self):
        data = years.data_dir()
        rows = facts.read(data / "generated" / "pbp_facts.csv")
        edited = {(e["plan_id"], e["line"]) for e in expected.load()
                  if (e["sheet"], e["column"]) == ("main", "L_xray_imaging")}
        sheets, _, _ = layers.live(data, layers.without(layers.EDITS))
        checked = []
        for cells in sheets["main"]:
            plan_id = cells["plan_id"]
            for line, benefit in (("1", "imaging.xray"), ("2", "imaging.diagnostic")):
                if {(plan_id, ""), (plan_id, line)} & edited:
                    continue
                found = {r["cost_kind"]: r["amount"] for r in rows
                         if (r["plan_id"], r["benefit"], r["network"]) == (plan_id, benefit, "in")}
                cell = " or ".join(found[k] for k in ("copay", "coinsurance") if k in found)
                self.assertEqual(cell, layers.shown(cells["L_xray_imaging"], line), (plan_id, line))
                checked.append((plan_id, line))
        self.assertGreaterEqual(len(checked), 20)


if __name__ == "__main__":
    unittest.main()
