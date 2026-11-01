import csv
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import cms_sources  # noqa: E402
import main_chart as mc  # noqa: E402
import test_reproduction  # noqa: E402

FIXTURE = test_reproduction.fixture()
PLANS = [p for p in test_reproduction.rows("generated/plans.csv") if p["plan_id"] in FIXTURE["plans"]]
DICTIONARY = {(stem, field): {"codes": codes} for stem, field, codes in FIXTURE["codes"]}
for stem, field, title in FIXTURE["titles"]:
    DICTIONARY.setdefault((stem, field), {"codes": {}})["title"] = title


def only(plan, stem, fields):
    return {stem: [{k: v for k, v in r.items() if k in fields} for r in plan.get(stem, [])]}


class PbpFieldsTest(unittest.TestCase):
    def test_listed_fields_alone_make_each_cell(self):
        for landscape in PLANS:
            plan = FIXTURE["plans"][landscape["plan_id"]]
            whole = mc.chart_row(landscape, plan)
            for column, (stem, fields) in cms_sources.PBP_FIELDS.items():
                with self.subTest(plan=landscape["plan_id"], column=column):
                    self.assertEqual(mc.chart_row(landscape, only(plan, stem, fields))[column], whole[column])


class DecodeTest(unittest.TestCase):
    CODES = {("f", "yn"): {"codes": {"1": "Yes", "2": "No"}},
             ("f", "bits"): {"codes": {"1 in 1": "Tier 7", "1 in 2": "Tier 1", "1 in 3": "Tier 2"}},
             ("f", "amt"): {"codes": {"": ""}}}

    def test_names_a_code(self):
        self.assertEqual(cms_sources.meaning(self.CODES, "f", "yn", "2"), "No")

    def test_names_each_set_bit(self):
        self.assertEqual(cms_sources.meaning(self.CODES, "f", "bits", "011"), "Tier 1; Tier 2")

    def test_leaves_amounts_alone(self):
        self.assertEqual(cms_sources.meaning(self.CODES, "f", "amt", "20"), "")
        self.assertEqual(cms_sources.meaning(self.CODES, "f", "unknown", "20"), "")


class LandscapeTest(unittest.TestCase):
    ROW = {"Part D Coverage Indicator": "Yes", "Part C Premium": "$0.00 ",
           "Part D Low Income Beneficiary Premium Amount": "$12.30", "Annual Part D Deductible Amount": "$615.00"}

    def fields(self, row):
        return [(r["column"], r["field"], r["value"]) for r in cms_sources.landscape_rows("H1-1-0", row)]

    def test_lists_the_premium_and_deductible_columns(self):
        self.assertEqual(self.fields(self.ROW), [
            ("D_premium_full_extra_help", "Part D Coverage Indicator", "Yes"),
            ("D_premium_full_extra_help", "Part C Premium", "$0.00"),
            ("D_premium_full_extra_help", "Part D Low Income Beneficiary Premium Amount", "$12.30"),
            ("N_pharmacy_deductible", "Part D Coverage Indicator", "Yes"),
            ("N_pharmacy_deductible", "Annual Part D Deductible Amount", "$615.00")])

    def test_a_plan_without_part_d_lists_only_that(self):
        self.assertEqual(self.fields(dict(self.ROW, **{"Part D Coverage Indicator": "No"})), [
            ("D_premium_full_extra_help", "Part D Coverage Indicator", "No"),
            ("N_pharmacy_deductible", "Part D Coverage Indicator", "No")])

    def test_a_plan_without_part_d_lists_no_drug_tiers(self):
        plan = FIXTURE["plans"]["H2923-001-0"]
        self.assertIn("N_pharmacy_deductible", {r["column"] for r in cms_sources.pbp_rows("p", plan, {}, True)})
        self.assertNotIn("N_pharmacy_deductible", {r["column"] for r in cms_sources.pbp_rows("p", plan, {}, False)})


class CommittedSourcesMatchGenerator(unittest.TestCase):
    def test_pbp_rows(self):
        made = [r for p in PLANS for r in cms_sources.pbp_rows(
            p["plan_id"], FIXTURE["plans"][p["plan_id"]], DICTIONARY, p["premium_full_extra_help"] != "n/a")]
        with open(os.path.join(test_reproduction.DATA, "generated/cms_sources.csv")) as f:
            committed = [r for r in csv.DictReader(f) if r["plan_id"] in FIXTURE["plans"] and r["file"] != "Landscape"]
        self.assertTrue(made)
        self.assertEqual(committed, made)

    def test_a_plan_without_a_deductible_says_no(self):
        rows = cms_sources.pbp_rows("H2923-001-0", FIXTURE["plans"]["H2923-001-0"], DICTIONARY, True)
        self.assertIn({"plan_id": "H2923-001-0", "column": "O_medical_deductible", "file": "pbp_Section_D",
                       "field": "pbp_d_inn_deduct_yn", "title": "In-Ntwk Plan Deductible YN", "value": "2", "meaning": "No"},
                      rows)


if __name__ == "__main__":
    unittest.main()
