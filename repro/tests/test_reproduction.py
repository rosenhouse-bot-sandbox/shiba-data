"""Checks the generated sheets against the corrected 2027 values in CLAUDE_ANALYSIS_METHODS.md Appendix B."""
import csv
import os
import unittest

DATA = os.path.join(os.path.dirname(__file__), "..", "data")


def load(name):
    return {r["plan_id"]: r for r in csv.DictReader(open(os.path.join(DATA, name)))}


MAIN = load("main_chart.csv")
DVHA = load("dvha.csv")

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


class DvhaReproducesCorrections(unittest.TestCase):
    def test_cases(self):
        for item, plan, col, expected in DVHA_CASES:
            with self.subTest(item=item, plan=plan, col=col):
                self.assertIn(expected, DVHA[plan][col])


if __name__ == "__main__":
    unittest.main()
