"""Runs the generators on the Appendix B plans and checks the corrected 2027 values in docs/2027-bootstrap/CLAUDE_ANALYSIS_METHODS.md Appendix B.

fixtures/pbp_appendix_b.json.gz holds those plans' PBP rows. make_fixture.py regenerates it.
"""
import csv
import gzip
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import dvha  # noqa: E402
import fields  # noqa: E402
import main_chart as mc  # noqa: E402
import years  # noqa: E402
from appendix_b import DVHA_CASES, MAIN_CHART_CASES  # noqa: E402

DATA = years.data_dir(2027)


def rows(name):
    with open(os.path.join(DATA, name)) as f:
        return list(csv.DictReader(f))


def load(name):
    return {r["plan_id"]: r for r in rows(name)}


def generate():
    with gzip.open(os.path.join(HERE, "fixtures", "pbp_appendix_b.json.gz"), "rt") as f:
        fixture = json.load(f)
    dvha.DICTIONARY = {(stem, field): {"codes": codes} for stem, field, codes in fixture["codes"]}
    plans = [p for p in rows("plans.csv") if p["plan_id"] in fixture["plans"]]
    citations = rows("citations.csv")
    main, _ = mc.sheet(plans, fixture["plans"], citations, mc.chart_row)
    extra, _ = dvha.sheet(plans, fixture["plans"], citations)
    return {r["plan_id"]: r for r in main}, {r["plan_id"]: r for r in extra}


MAIN, DVHA = {}, {}


def setUpModule():
    main, extra = generate()
    MAIN.update(main)
    DVHA.update(extra)


class ColumnsTest(unittest.TestCase):
    def test_generators_make_the_spec_columns(self):
        for sheet, made in (("main", MAIN), ("dvha", DVHA)):
            for row in made.values():
                self.assertEqual(list(row), ["section", "plan_id", "plan_name"] + list(fields.labels(sheet)))


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


class CommittedSheetsHoldEveryCitation(unittest.TestCase):
    def test_values(self):
        sheets = {"main": load("main_chart.csv"), "dvha": load("dvha.csv")}
        for c in rows("citations.csv"):
            name = "dvha" if c["column"].startswith("dvha.") else "main"
            cell = sheets[name][c["plan_id"]][c["column"].removeprefix("dvha.")]
            with self.subTest(**c):
                self.assertEqual(cell.split(" | ")[int(c["line"]) - 1] if c["line"] else cell, c["value"])


class DvhaReproducesCorrections(unittest.TestCase):
    def test_cases(self):
        for item, plan, col, expected in DVHA_CASES:
            with self.subTest(item=item, plan=plan, col=col):
                self.assertIn(expected, DVHA[plan][col])


if __name__ == "__main__":
    unittest.main()
