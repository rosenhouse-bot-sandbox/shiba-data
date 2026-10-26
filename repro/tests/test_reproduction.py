"""Runs the generators on the Appendix B plans and checks the corrected 2027 values in CLAUDE_ANALYSIS_METHODS.md Appendix B.

fixtures/pbp_appendix_b.json.gz holds those plans' PBP rows. make_fixture.py regenerates it.
"""
import csv
import gzip
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import dvha  # noqa: E402
import main_chart as mc  # noqa: E402


def rows(name):
    with open(os.path.join(DATA, name)) as f:
        return list(csv.DictReader(f))


def load(name):
    return {r["plan_id"]: r for r in rows(name)}


def generate():
    with gzip.open(os.path.join(HERE, "fixtures", "pbp_appendix_b.json.gz"), "rt") as f:
        fixture = json.load(f)
    dvha.DICTIONARY = {(stem, field): {"codes": codes} for stem, field, codes in fixture["codes"]}
    landscape = load("plans.csv")
    citations = rows("citations.csv")
    main, extra = {}, {}
    for plan_id, plan in fixture["plans"].items():
        main[plan_id] = mc.chart_row(landscape[plan_id], plan)
        mc.apply_citations(main[plan_id], [c for c in citations if c["plan_id"] == plan_id])
        extra[plan_id] = dvha.dvha_row(landscape[plan_id], plan)
    return main, extra


MAIN, DVHA = generate()

# (Appendix B item, plan, column, expected cell)
MAIN_CHART_CASES = [
    ("1", "H5216-048-0", "K_tests_labs", "$0-$100/$0"),
    ("1", "H5216-048-0", "L_xray_imaging", "$0-$145 | $205-$345"),
    ("1", "H5216-048-0", "O_medical_deductible", "$100 out-of-network only"),
    ("1", "H5216-048-0", "AA_opt_packages", "●"),
    ("2", "H2001-045-0", "O_medical_deductible", "Part B deductible some"),
    ("2", "H2001-045-0", "T_chiropractic", ""),
    ("3", "H9003-009-0", "K_tests_labs", "$15-$45/$0"),
    ("4", "H2923-001-0", "T_chiropractic", "●"),
    ("5", "H2923-009-0", "T_chiropractic", "●"),
    ("6", "H2923-028-3", "V_massage", "●"),
    ("7", "H2923-028-3", "O_medical_deductible", "$200 some"),
    ("7", "H2923-025-0", "O_medical_deductible", "$150 some"),
    ("7", "H2923-005-0", "O_medical_deductible", "$200 some"),
    ("7", "H7199-002-0", "O_medical_deductible", "$250 some"),
    ("10", "H6815-038-0", "K_tests_labs", "0%-20%/$0-$50"),
    ("11", "H1372-003-0", "S_acupuncture", "●"),
    ("11", "H1372-003-0", "T_chiropractic", "●"),
    ("12", "H1036-153-0", "L_xray_imaging", "$0-$145 | $205-$345"),
    ("13", "H1036-317-0", "Y_otc", "●"),
    ("13", "H1036-317-0", "O_medical_deductible", "Part B deductible some"),
]

# (Appendix B DVHA item, plan, column, text the cell must contain)
DVHA_CASES = [
    ("1", "H6815-038-0", "F_dental", "COMP $0 (adjunctive general services only)"),
    ("1", "H5439-015-0", "F_dental", "COMP $0 (adjunctive general services only)"),
    ("2", "H9003-006-0", "G_vision", "eyewear $100/two years"),
    ("6", "H3817-008-1", "J_extra_benefits", "Routine Podiatry"),
    ("6", "H3817-009-1", "J_extra_benefits", "Routine Podiatry"),
    ("6", "H3817-011-1", "J_extra_benefits", "Routine Podiatry"),
    ("7", "H5216-048-0", "E_optional_packages", "MyOption DEN972 $52.10/mo, max $1,500"),
] + [("3", p, "I_alt_care_otc_travel", "$25,000 max") for p in
     ("H2923-001-0", "H2923-028-3", "H2923-025-0", "H2923-005-0", "H7199-002-0", "H2923-019-0", "H2923-009-0")]


class MainChartReproducesCorrections(unittest.TestCase):
    def test_cases(self):
        for item, plan, col, expected in MAIN_CHART_CASES:
            with self.subTest(item=item, plan=plan, col=col):
                self.assertEqual(MAIN[plan][col], expected)

    def test_devoted_core_keeps_tests_before_labs(self):
        self.assertTrue(MAIN["H2923-001-0"]["K_tests_labs"].startswith("$0-$95/$0-$40"))


class CommittedSheetsMatchGenerators(unittest.TestCase):
    def test_rows(self):
        for name, generated in (("main_chart.csv", MAIN), ("dvha.csv", DVHA)):
            committed = load(name)
            for plan_id, row in generated.items():
                with self.subTest(sheet=name, plan=plan_id):
                    self.assertEqual(committed[plan_id], row)


class DvhaReproducesCorrections(unittest.TestCase):
    def test_cases(self):
        for item, plan, col, expected in DVHA_CASES:
            with self.subTest(item=item, plan=plan, col=col):
                self.assertIn(expected, DVHA[plan][col])


if __name__ == "__main__":
    unittest.main()
