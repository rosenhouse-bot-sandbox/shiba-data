"""Checks the sheets against the corrected 2027 values in appendix_b.py."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, ".."), HERE]
import sheets  # noqa: E402
import years  # noqa: E402
from appendix_b import DVHA_CASES, MAIN_CHART_CASES  # noqa: E402

# Cases the sheets do not match.
MISSED = {
    ("1", "H5216-048-0", "K_tests_labs"): "the cell also shows outpatient hospital prices",
    ("1", "H5216-048-0", "L_xray_imaging"): "the cell also shows outpatient hospital prices and a $0 mammogram",
    ("12", "H1036-153-0", "L_xray_imaging"): "the cell also shows outpatient hospital prices and a $0 mammogram",
    ("1", "H5439-015-0", "F_dental"): "the rule does not show that comprehensive care covers only adjunctive services",
    ("1", "H6815-038-0", "F_dental"): "the rule does not show that comprehensive care covers only adjunctive services",
    ("7", "H5216-048-0", "E_optional_packages"): "the facts give no yearly maximum for the package",
}


class AppendixBTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sheets = {sheet: {r["plan_id"]: r for r in rows} for sheet, rows in sheets.read(years.data_dir(2027)).items()}

    def test_main_chart_cases(self):
        for item, plan, col, expected in MAIN_CHART_CASES:
            with self.subTest(item=item, plan=plan, col=col):
                self.assertEqual(self.sheets["main"][plan][col] == expected, (item, plan, col) not in MISSED)

    def test_dvha_cases(self):
        for item, plan, col, expected in DVHA_CASES:
            with self.subTest(item=item, plan=plan, col=col):
                self.assertEqual(expected in self.sheets["dvha"][plan][col], (item, plan, col) not in MISSED)


if __name__ == "__main__":
    unittest.main()
