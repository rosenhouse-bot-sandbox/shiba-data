"""Runs the generators on the Appendix B plans and checks the corrected 2027 values in appendix_b.py.
The generators must reproduce the committed generated sheets. The corrections must hold once the layers apply.

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
import layers  # noqa: E402
import main_chart as mc  # noqa: E402
import years  # noqa: E402
from appendix_b import DVHA_CASES, MAIN_CHART_CASES  # noqa: E402

DATA = years.data_dir(2027)


def rows(name):
    with open(os.path.join(DATA, name)) as f:
        return list(csv.DictReader(f))


def by_plan(sheet_rows):
    return {r["plan_id"]: r for r in sheet_rows}


def fixture():
    with gzip.open(os.path.join(HERE, "fixtures", "pbp_appendix_b.json.gz"), "rt") as f:
        return json.load(f)


def generate():
    pbp = fixture()
    dvha.DICTIONARY = {(stem, field): {"codes": codes} for stem, field, codes in pbp["codes"]}
    plans = [p for p in rows("generated/plans.csv") if p["plan_id"] in pbp["plans"]]
    return {"main": by_plan(mc.sheet(plans, pbp["plans"], mc.chart_row)),
            "dvha": by_plan(dvha.sheet(plans, pbp["plans"]))}


GENERATED, LIVE = {}, {}
# Cases whose detail the facts miss.
MISSED = {
    ("10", "H6815-038-0", "K_tests_labs"): "the facts take a $200 price for tests that is not a diagnostic test",
    ("1", "H5439-015-0", "F_dental"): "the rule does not show that comprehensive care covers only adjunctive services",
    ("1", "H6815-038-0", "F_dental"): "the rule does not show that comprehensive care covers only adjunctive services",
    ("7", "H5216-048-0", "E_optional_packages"): "the facts give no yearly maximum for the package",
}


def setUpModule():
    GENERATED.update(generate())
    LIVE.update({sheet: by_plan(sheet_rows) for sheet, sheet_rows in layers.live(DATA)[0].items()})


class ColumnsTest(unittest.TestCase):
    def test_generators_make_the_spec_columns(self):
        for sheet, made in GENERATED.items():
            for row in made.values():
                self.assertEqual(list(row), ["section", "plan_id", "plan_name"] + list(fields.labels(sheet)))


class CommittedSheetsMatchGenerators(unittest.TestCase):
    def test_rows(self):
        for sheet, name in layers.SHEETS.items():
            committed = by_plan(rows(f"generated/{name}"))
            for plan_id, row in GENERATED[sheet].items():
                with self.subTest(sheet=name, plan=plan_id):
                    self.assertEqual(committed[plan_id], row)


class MainChartReproducesCorrections(unittest.TestCase):
    def test_cases(self):
        for item, plan, col, expected in MAIN_CHART_CASES:
            with self.subTest(item=item, plan=plan, col=col):
                self.assertEqual(LIVE["main"][plan][col] == expected, (item, plan, col) not in MISSED)

    def test_devoted_core_keeps_tests_before_labs(self):
        self.assertTrue(GENERATED["main"]["H2923-001-0"]["K_tests_labs"].startswith("$0-$95/$0-$40"))


class DvhaReproducesCorrections(unittest.TestCase):
    def test_cases(self):
        for item, plan, col, expected in DVHA_CASES:
            with self.subTest(item=item, plan=plan, col=col):
                self.assertEqual(expected in LIVE["dvha"][plan][col], (item, plan, col) not in MISSED)


if __name__ == "__main__":
    unittest.main()
