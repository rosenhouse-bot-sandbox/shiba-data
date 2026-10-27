"""Runs the generators on the Appendix B plans and checks the corrected 2027 values in docs/2027-bootstrap/CLAUDE_ANALYSIS_METHODS.md Appendix B.
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


def generate():
    with gzip.open(os.path.join(HERE, "fixtures", "pbp_appendix_b.json.gz"), "rt") as f:
        fixture = json.load(f)
    dvha.DICTIONARY = {(stem, field): {"codes": codes} for stem, field, codes in fixture["codes"]}
    plans = [p for p in rows("generated/plans.csv") if p["plan_id"] in fixture["plans"]]
    return {"main": by_plan(mc.sheet(plans, fixture["plans"], mc.chart_row)),
            "dvha": by_plan(dvha.sheet(plans, fixture["plans"]))}


GENERATED, LIVE = {}, {}


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
                self.assertEqual(LIVE["main"][plan][col], expected)

    def test_devoted_core_keeps_tests_before_labs(self):
        self.assertTrue(LIVE["main"]["H2923-001-0"]["K_tests_labs"].startswith("$0-$95/$0-$40"))


class DvhaReproducesCorrections(unittest.TestCase):
    def test_cases(self):
        for item, plan, col, expected in DVHA_CASES:
            with self.subTest(item=item, plan=plan, col=col):
                self.assertIn(expected, LIVE["dvha"][plan][col])


if __name__ == "__main__":
    unittest.main()
