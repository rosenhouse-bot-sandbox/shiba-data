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
                f.write(f"plan_id\n{PLAN}\n")
            os.mkdir(f"{tmp}/pbp")
            with open(f"{tmp}/pbp/pbp_b8_clin_diag_ther.txt", "w") as f:
                f.write("pbp_a_hnumber\tpbp_a_plan_identifier\tsegment_id\tpbp_b8b_copay_yn\tpbp_b8b_coins_yn\n"
                        "H1111\t001\t0\t2\t2\n")
            pbp_facts.main(f"{tmp}/plans.csv", f"{tmp}/pbp", f"{tmp}/out.csv")
            rows = facts.read(f"{tmp}/out.csv")
        self.assertEqual([(r["plan_id"], r["benefit"], r["amount"]) for r in rows],
                         [(PLAN, "imaging.diagnostic", "$0"), (PLAN, "imaging.xray", "$0"),
                          (PLAN, "radiation_therapy", "$0")])


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
