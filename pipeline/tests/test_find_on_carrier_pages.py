import csv, os, pathlib, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import find_on_carrier_pages as fc

FIXTURES = pathlib.Path(__file__).parent / "fixtures/carrier_pages"
WELLCARE = "https://www.wellcareor.com/plan-benefit-materials.html"
ATRIO = "https://atriohp.com/oregon/members/2027-benefit-plans/"
AGERIGHT = "https://agerightadvantage.com/for-members/plan-documents/"
FIXTURE_BY_URL = {WELLCARE: "wellcare.html", ATRIO: "atrio.html", AGERIGHT: "ageright.html"}


def fetch(url):
    return (FIXTURES / FIXTURE_BY_URL[url]).read_text()


def rows(url, plans, year_mark=""):
    return [(r["plan_ids"], r["kind"], r["url"]) for r in fc.documents(fetch(url), url, plans, year_mark)]


class DocumentsTest(unittest.TestCase):
    def test_wellcare_keeps_the_years_english_sb_and_eoc(self):
        base = "https://www.wellcareor.com/content/dam/centene/medicare/pdfs/aep/2027/"
        self.assertEqual(rows(WELLCARE, ["H6815-038-0"], "/aep/2027/"), [
            ("H6815-038-0", "SB", base + "sb/H6815_038_2027_OR_SB_HMAPD_7017558ENG_M.pdf"),
            ("H6815-038-0", "EOC", base + "eoc/H6815_038_2027_OR_EOC_HMAPD_7001734ENG_C.pdf")])

    def test_atrio_shares_an_sb_with_the_plans_listed_beside_it(self):
        base = "https://atriohp.com/media/"
        self.assertEqual(rows(ATRIO, ["H7006-018-0", "H7006-021-0"]), [
            ("H7006-018-0;H7006-021-0", "SB", base + "254ghvxu/2027-portland-sb_final-v2.pdf"),
            ("H7006-018-0", "EOC", base + "qzyffvwm/h7006_018_eoc_2027_atrio-choice-rx-ppo-portland.pdf"),
            ("H7006-021-0", "EOC", base + "qyfpfa50/h7006_021_eoc_2027_atrio-freedom-ppo-portland.pdf")])

    def test_ageright_matches_a_filename_with_a_segment(self):
        base = "https://agerightadvantage.com/wp-content/uploads/2026/"
        self.assertEqual(rows(AGERIGHT, ["H1372-003-0"]), [
            ("H1372-003-0", "SB", base + "09/H1372_003_0_SB_v07.pdf"),
            ("H1372-003-0", "EOC", base + "10/H1372_003_0_EOC_v03_508.pdf")])
        self.assertEqual(rows(AGERIGHT, ["H1372-003-1"]), [])

    def test_rows_cite_the_page(self):
        self.assertEqual({r["found_via"] for r in fc.documents(fetch(WELLCARE), WELLCARE, ["H6815-038-0"], "/aep/2027/")},
                         {"carrier page (wellcareor.com/plan-benefit-materials.html)"})

    def test_rejects_two_documents_of_one_kind_for_a_plan(self):
        with self.assertRaisesRegex(SystemExit, "several EOCs for H6815-038-0"):
            rows(WELLCARE, ["H6815-038-0"])


class MainTest(unittest.TestCase):
    def test_rewrites_only_these_carriers_rows(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, SHIBA_DATA=tmp):
            data = pathlib.Path(tmp, "2027")
            (data / "generated").mkdir(parents=True)
            with open(data / "generated/plans.csv", "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["plan_id", "organization"])
                w.writeheader()
                w.writerows([dict(plan_id="H1036-153-0", organization="Humana"),
                             dict(plan_id="H1372-003-0", organization="AgeRight Advantage")])
            (data / "found.csv").write_text("plan_ids,kind,url,found_via\n"
                                            "H1036-153-0,SB,humana-sb,browser\n"
                                            "H1372-003-0,SB,stale-sb,browser\n")
            fc.main("2027", fetch=fetch)
            base = "https://agerightadvantage.com/wp-content/uploads/2026/"
            self.assertEqual([(r["plan_ids"], r["kind"], r["url"]) for r in fc.read(data / "found.csv")], [
                ("H1036-153-0", "SB", "humana-sb"), ("H1372-003-0", "SB", base + "09/H1372_003_0_SB_v07.pdf"),
                ("H1372-003-0", "EOC", base + "10/H1372_003_0_EOC_v03_508.pdf")])


if __name__ == "__main__":
    unittest.main()
