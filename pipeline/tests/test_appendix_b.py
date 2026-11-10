"""Checks the live sheets against the corrected 2027 values in appendix_b.py."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, ".."), HERE]
import layers  # noqa: E402
import years  # noqa: E402
from appendix_b import DVHA_CASES, MAIN_CHART_CASES  # noqa: E402

# Cases whose detail the facts miss.
MISSED = {
    ("10", "H6815-038-0", "K_tests_labs"): "the facts take a $200 price for tests that is not a diagnostic test",
    ("1", "H5439-015-0", "F_dental"): "the rule does not show that comprehensive care covers only adjunctive services",
    ("7", "H5216-048-0", "E_optional_packages"): "the facts give no yearly maximum for the package",
}


class AppendixBTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.live = {sheet: {r["plan_id"]: r for r in rows} for sheet, rows in layers.live(years.data_dir(2027))[0].items()}

    def test_main_chart_cases(self):
        for item, plan, col, expected in MAIN_CHART_CASES:
            with self.subTest(item=item, plan=plan, col=col):
                self.assertEqual(self.live["main"][plan][col] == expected, (item, plan, col) not in MISSED)

    def test_dvha_cases(self):
        for item, plan, col, expected in DVHA_CASES:
            with self.subTest(item=item, plan=plan, col=col):
                self.assertEqual(expected in self.live["dvha"][plan][col], (item, plan, col) not in MISSED)


if __name__ == "__main__":
    unittest.main()
