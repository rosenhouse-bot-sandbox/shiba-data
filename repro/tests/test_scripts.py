import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import cite  # noqa: E402
import fetch_docs  # noqa: E402
import main_chart as mc  # noqa: E402
import universe  # noqa: E402


def landscape_row(**kw):
    row = {"State Territory Abbreviation": "OR", "County Name": "Multnomah", "Contract ID": "H1111",
           "Plan ID": "001", "Segment ID": "0", "Contract Category Type": "MA-PD", "SNP Type": "Not Applicable",
           "Part D Coverage Indicator": "Yes", "Plan Name": "A"}
    row.update(kw)
    return row


class UniverseTest(unittest.TestCase):
    def test_keeps_plans_in_both_counties_and_drops_dsnp_isnp(self):
        rows = [landscape_row(), landscape_row(**{"County Name": "Clackamas"}),
                landscape_row(**{"Plan ID": "002"}),
                landscape_row(**{"Plan ID": "003", "SNP Type": "Dual-Eligible"}),
                landscape_row(**{"Plan ID": "003", "SNP Type": "Dual-Eligible", "County Name": "Clackamas"})]
        self.assertEqual([universe.plan_id(r) for r in universe.select_plans(rows)], ["H1111-001-0"])

    def test_full_extra_help_premium_is_part_c_plus_lis_part_d(self):
        row = landscape_row(**{"Part C Premium": "$159.40 ", "Part D Low Income Beneficiary Premium Amount": "$40.30 "})
        self.assertEqual(universe.full_extra_help_premium(row), "$199.70")
        self.assertEqual(universe.full_extra_help_premium(landscape_row(**{"Part D Coverage Indicator": "No"})), "n/a")


class MainChartTest(unittest.TestCase):
    def test_span_and_default_zero(self):
        self.assertEqual(mc.span("0.00", "100.00", mc.money), "$0-$100")
        self.assertEqual(mc.span("45.00", "45.00", mc.money), "$45")
        self.assertEqual(mc.copay_or_coins({}, "a", "b", "c", "d"), "$0")

    def test_flag_reads_cms_bit_positions(self):
        self.assertTrue(mc.flag({"f": "0110000"}, "f", 2))
        self.assertFalse(mc.flag({"f": "0110000"}, "f", 1))

    def test_pharmacy_deductible_names_exempt_tiers(self):
        plan = {"pbp_mrx": [{"mrx_alt_no_ded_tier": "0110000"}]}
        self.assertEqual(mc.pharmacy_deductible(plan, {"part_d_deductible": "$700"}), "$700 not tiers 1,2")

    def test_medical_deductible_scope(self):
        some = {"pbp_Section_D": [{"pbp_d_inn_deduct_yn": "1", "pbp_d_inn_deduct_amt": "200.00", "pbp_d_inn_deduct_m_yn": "2"}]}
        oon = {"pbp_Section_D": [{"pbp_d_ann_deduct_yn": "1", "pbp_d_ann_deduct_amt": "100.00",
                                  "pbp_d_ann_deduct_bens": "100", "pbp_d_ann_deduct_inn_mc_yn": "2"}]}
        part_b = {"pbp_Section_D": [{"pbp_d_inn_deduct_yn": "1", "pbp_d_inn_deduct_partb_yn": "1", "pbp_d_inn_deduct_m_yn": "2"}]}
        self.assertEqual(mc.medical_deductible(some), "$200 some")
        self.assertEqual(mc.medical_deductible(oon), "$100 out-of-network only")
        self.assertEqual(mc.medical_deductible(part_b), "Part B deductible some")
        self.assertEqual(mc.medical_deductible({}), "$0")

    def test_inpatient_day_intervals(self):
        plan = {"pbp_b1a_inpat_hosp": [{"pbp_b1a_copay_mcs_int_num_t1": "3", "pbp_b1a_copay_mcs_amt_int1_t1": "465.00",
                                        "pbp_b1a_copay_mcs_bgnd_int1_t1": "1", "pbp_b1a_copay_mcs_endd_int1_t1": "5",
                                        "pbp_b1a_copay_mcs_amt_int2_t1": "0.00"}]}
        self.assertEqual(mc.inpatient(plan), "$465 | 1-5")

    def test_apply_citations_replaces_one_line(self):
        row = {"L_xray_imaging": "$0-$145 | $0-$345", "U_naturopath": ""}
        mc.apply_citations(row, [{"column": "L_xray_imaging", "line": "2", "value": "$205-$345"},
                                 {"column": "U_naturopath", "line": "", "value": "●"}])
        self.assertEqual(row, {"L_xray_imaging": "$0-$145 | $205-$345", "U_naturopath": "●"})


class DocumentTest(unittest.TestCase):
    def test_id_patterns_match_printed_forms(self):
        for printed in ("H5439 | 015 | 000", "H1036153000EOC27", "H3817_008001EOC2027", "H2923-028-003"):
            plan = {"H5439": "H5439-015-0", "H1036": "H1036-153-0", "H3817": "H3817-008-1", "H2923": "H2923-028-3"}[printed[:5]]
            self.assertTrue(any(__import__("re").search(rx, printed) for rx in fetch_docs.id_patterns(plan)), printed)

    def test_naturopathy_ignores_exclusion_table(self):
        excluded = {1: "Naturopath services (uses natural or alternative treatments) Not covered under any condition"}
        covered = {2: "allowance toward Massage, Routine Acupuncture, and/or Naturopath Services combined."}
        self.assertEqual(cite.naturopathy_mentions(excluded), [])
        self.assertEqual(cite.naturopathy_mentions(covered)[0][0], 2)

    def test_find_page_collapses_whitespace(self):
        self.assertEqual(cite.find_page({7: "MRI, CT, and PET $150 per visit"}, "MRI, CT,\nand PET  $150"), 7)


if __name__ == "__main__":
    unittest.main()
