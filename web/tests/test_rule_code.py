import pathlib
import sys
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import rule_code  # noqa: E402
import present  # noqa: E402
import years  # noqa: E402

SHA = "abc123"
LATEST = max(present.VERSIONS)


def names(links):
    return [link["name"] for link in links]


class RuleCodeTest(unittest.TestCase):
    def cited(self, link):
        """The present.py lines that a link names."""
        prefix = f"{rule_code.REPO_URL}/blob/{SHA}/pipeline/present.py#L"
        self.assertTrue(link["url"].startswith(prefix), link["url"])
        start, end = link["url"][len(prefix):].split("-L")
        with open(present.__file__) as f:
            return "".join(f.readlines()[int(start) - 1:int(end)])

    def test_links_the_columns_entry_then_the_function_it_names(self):
        links = rule_code.links("main", "K_tests_labs", LATEST, SHA)
        self.assertEqual(names(links), ["K_tests_labs in COLUMNS", "every_test_and_lab"])
        self.assertEqual(self.cited(links[0]).strip(), '"K_tests_labs": every_test_and_lab,')
        self.assertTrue(self.cited(links[1]).startswith("def every_test_and_lab("))
        self.assertTrue(self.cited(links[1]).rstrip().endswith("tests + labs)]"))

    def test_links_each_name_a_composed_rule_uses_in_source_order_once(self):
        links = rule_code.links("dvha", "F_dental", LATEST, SHA)
        self.assertEqual(names(links), [
            "F_dental in DVHA", "or_none", "with_lacking", "with_packages", "with_details", "dental", "no_maximum",
            "dental_deductible", "dental_rollover", "dental_reimbursement", "dental_exclusions", "DENTAL_OON",
            "out_of_network", "preventive_limits", "provider_network"])
        self.assertTrue(self.cited(links[0]).lstrip().startswith('"F_dental": or_none('))
        self.assertTrue(self.cited(links[11]).startswith("DENTAL_OON = out_of_network("))
        for link in links[1:]:
            if link["name"] != "DENTAL_OON":
                self.assertTrue(self.cited(link).startswith(f"def {link['name']}("), link)

    def test_links_the_earlier_rule_that_a_version_uses(self):
        dvha = rule_code.links("dvha", "F_dental", 31, SHA)
        self.assertEqual(names(dvha)[:2], ["F_dental in EARLIER_RULES", "or_none"])
        self.assertTrue(self.cited(dvha[0]).lstrip().startswith("(32, or_none("))
        main = rule_code.links("main", "K_tests_labs", 20, SHA)
        self.assertEqual(names(main)[:2], ["K_tests_labs in CHART_18", "tests_labs"])
        self.assertEqual(names(rule_code.links("main", "K_tests_labs", 17, SHA)), ["K_tests_labs in EARLIER_RULES", "tests_labs"])

    def test_resolves_every_column_at_the_pinned_version(self):
        with mock.patch.object(present, "current", return_value=31):
            got = rule_code.resolve(years.data_dir(), SHA)
        self.assertEqual(set(got["main"]), set(present.COLUMNS))
        self.assertEqual(set(got["dvha"]), set(present.DVHA))
        self.assertEqual(names(got["dvha"]["F_dental"])[0], "F_dental in EARLIER_RULES")
        self.assertEqual(names(got["main"]["AB_ambulance"]), ["AB_ambulance in COLUMNS", "ambulance"])


if __name__ == "__main__":
    unittest.main()
