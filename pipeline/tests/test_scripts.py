import csv
import json
import os
import pathlib
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import fetch_docs  # noqa: E402
import fields  # noqa: E402
import pbp  # noqa: E402
import universe  # noqa: E402
import years  # noqa: E402


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
        self.assertEqual([universe.plan_id(r) for r in universe.select_plans(rows, "OR", ("Multnomah", "Clackamas"))], ["H1111-001-0"])

    def test_keeps_only_the_state(self):
        rows = [landscape_row(**{"State Territory Abbreviation": "WA"}),
                landscape_row(**{"State Territory Abbreviation": "WA", "County Name": "Clackamas"})]
        self.assertEqual(universe.select_plans(rows, "OR", ("Multnomah", "Clackamas")), [])

    def test_full_extra_help_premium_is_part_c_plus_lis_part_d(self):
        row = landscape_row(**{"Part C Premium": "$159.40 ", "Part D Low Income Beneficiary Premium Amount": "$40.30 "})
        self.assertEqual(universe.full_extra_help_premium(row), "$199.70")
        self.assertEqual(universe.full_extra_help_premium(landscape_row(**{"Part D Coverage Indicator": "No"})), "n/a")


class YearsTest(unittest.TestCase):
    def test_the_live_year_has_data(self):
        self.assertTrue((years.data_dir() / "config.json").exists())
        self.assertEqual(years.data_dir().name, str(years.LIVE))

    def test_config_takes_the_year_from_the_directory_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = pathlib.Path(tmp, "2099")
            data.mkdir()
            (data / "config.json").write_text(json.dumps({"state": "OR"}))
            self.assertEqual(years.config(data), {"state": "OR", "year": 2099})


class CoverCheckTest(unittest.TestCase):
    def check(self, year, counties):
        text = "Evidence of Coverage for 2027, plan H1111-001, Multnomah County"
        return fetch_docs.cover_check(text, ["H1111-001-0"], "RIDER", {"H1111-001-0": "A"}, year, counties)

    def test_wants_the_year_on_the_first_pages(self):
        self.assertEqual(self.check(2027, ["Multnomah"]), [])
        self.assertEqual(self.check(2028, ["Multnomah"]), ["no 2028 on first pages"])

    def test_wants_every_county(self):
        self.assertEqual(self.check(2027, ["Multnomah", "Clackamas"]), ["Clackamas not mentioned"])


class PbpDictionaryTest(unittest.TestCase):
    def test_names_the_pattern_when_the_dictionary_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(FileNotFoundError, "PBP_Benefits_\\*_dictionary.xlsx"):
                pbp.load_dictionary(tmp)


class SpecTest(unittest.TestCase):
    def test_carriers_are_organizations_in_the_plans_file(self):
        with open(f"{years.data_dir()}/generated/plans.csv") as f:
            organizations = {r["organization"] for r in csv.DictReader(f)}
        self.assertLessEqual(set(fields.CARRIERS), organizations)


class DocumentTest(unittest.TestCase):
    def test_id_patterns_match_printed_forms(self):
        cases = [("H5439-015-0", "H5439 | 015 | 000"), ("H1036-153-0", "H1036153000EOC27"),
                 ("H3817-008-1", "H3817_008001EOC2027"), ("H2923-028-3", "H2923-028-003")]
        for plan, printed in cases:
            self.assertTrue(any(re.search(rx, printed) for rx in fetch_docs.id_patterns(plan)), printed)


if __name__ == "__main__":
    unittest.main()
