import contextlib, csv, io, json, os, pathlib, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import find_by_plan_page as fpp

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
AETNA = "https://www.aetna.com/medicare/plan.H2056.003.html"
DEVOTED = "https://www.devoted.com/plan-documents/benefit-and-coverage-details/H2923-028-003-2027/"
UHC = "https://www.aarpmedicareplans.com/health-plans/details.html/97201/051/H3805048000/2027"
PAGES = {AETNA: "aetna", DEVOTED: "devoted", UHC: "uhc"}


def page(name):
    return (FIXTURES / f"plan_page_{name}.html").read_text()


def plan(plan_id, organization):
    return dict(plan_id=plan_id, organization=organization)


class PageUrlTest(unittest.TestCase):
    def test_builds_each_carriers_page_from_the_plan_id(self):
        self.assertEqual(fpp.page_url(plan("H2056-003-0", "Aetna Medicare"), "2027", "Multnomah"), AETNA)
        self.assertEqual(fpp.page_url(plan("H2923-028-3", "Devoted Health"), "2027", "Multnomah"), DEVOTED)
        self.assertEqual(fpp.page_url(plan("H3805-048-0", "UnitedHealthcare"), "2027", "Multnomah"), UHC)
        self.assertIsNone(fpp.page_url(plan("H1036-153-0", "Humana"), "2027", "Multnomah"))

    def test_uhc_uses_the_countys_zip_and_fips(self):
        self.assertIn("/97045/005/", fpp.page_url(plan("H3805-048-0", "UnitedHealthcare"), "2027", "Clackamas"))


class LinksTest(unittest.TestCase):
    def test_keeps_english_sb_and_eoc_links(self):
        self.assertEqual(fpp.links(page("devoted"), DEVOTED), [
            ("SB", "https://assets.devoted.com/plan-documents/2027/2027-DEVOTED-CORE-001-OR-%28HMO%29-SB-H2923-001-ENG.pdf", ""),
            ("EOC", "https://assets.devoted.com/plan-documents/2027/2027-DEVOTED-CORE-001-OR-%28HMO%29-EOC-H2923-001-ENG.pdf", "")])
        base = "https://www.aetna.com/medicare/documents/individual/2027/"
        self.assertEqual(fpp.links(page("aetna"), AETNA), [
            ("SB", base + "sb/en/Y0001_H2056_003_HR01_SB2027_M.pdf", ""),
            ("EOC", base + "eoc/en/Y0001_H2056_003_HR01_EOC2027_C.pdf", "")])

    def test_uhc_optional_services_are_riders(self):
        base = "https://www.aarpmedicareplans.com/alphadog/"
        self.assertEqual(fpp.links(page("uhc"), UHC), [
            ("RIDER", base + "AAEX27HM0432520_000", "Platinum Dental"),
            ("EOC", base + "AAOR27HP0418846_000", ""), ("SB", base + "AAOR27HP0412776_000", "")])

    def test_a_link_repeated_on_the_page_is_listed_once(self):
        self.assertEqual(len(fpp.links(page("aetna") * 2, AETNA)), 2)

    def test_skips_an_anchor_without_href(self):
        self.assertEqual(fpp.links("<a>Summary of Benefits</a>", AETNA), [])


class MainTest(unittest.TestCase):
    def run_main(self, plans, found, render):
        with tempfile.TemporaryDirectory() as tmp:
            data = pathlib.Path(tmp, "2027")
            (data / "generated").mkdir(parents=True)
            (data / "config.json").write_text(json.dumps({"counties": ["Multnomah", "Clackamas"]}))
            write(data / "generated/plans.csv", plans)
            write(data / "found.csv", found)
            out = io.StringIO()
            with mock.patch.dict(os.environ, SHIBA_DATA=tmp), contextlib.redirect_stdout(out):
                fpp.main(2027, render=render)
            with open(data / "found.csv", newline="") as f:
                return list(csv.DictReader(f)), out.getvalue()

    def test_replaces_the_rows_of_its_carriers_and_keeps_the_rest(self):
        plans = [plan("H2056-003-0", "Aetna Medicare"), plan("H2923-028-3", "Devoted Health"),
                 plan("H3805-048-0", "UnitedHealthcare"), plan("H7006-018-0", "ATRIO")]
        found = [doc("H3805-048-0", "SB", "old"), doc("H7006-018-0", "SB", "atrio")]
        rows, out = self.run_main(plans, found, lambda urls: [page(PAGES[u]) for u in urls])
        self.assertEqual([(r["plan_ids"], r["kind"]) for r in rows], [
            ("H2056-003-0", "SB"), ("H2056-003-0", "EOC"), ("H2923-028-3", "SB"), ("H2923-028-3", "EOC"),
            ("H3805-048-0", "RIDER"), ("H3805-048-0", "EOC"), ("H3805-048-0", "SB"), ("H7006-018-0", "SB")])
        self.assertEqual(rows[0]["found_via"], f"carrier plan page {AETNA}")
        self.assertEqual(rows[4]["found_via"], f'carrier plan page {UHC}, "Platinum Dental"')
        self.assertEqual(rows[-1]["url"], "atrio")
        self.assertEqual(out, "")

    def test_keeps_the_old_rows_of_a_page_without_an_sb_or_eoc(self):
        found = [doc("H2056-003-0", "SB", "old-sb"), doc("H2056-003-0", "EOC", "old-eoc")]
        eoc_only = '<a href="/eoc.pdf">Evidence of Coverage (EOC)</a>'
        rows, out = self.run_main([plan("H2056-003-0", "Aetna Medicare")], found, lambda urls: [eoc_only])
        self.assertEqual([r["url"] for r in rows], ["old-sb", "old-eoc"])
        self.assertEqual(out, f"::warning::No SB on {AETNA}\n")


def doc(plan_ids, kind, url):
    return dict(plan_ids=plan_ids, kind=kind, url=url, found_via="old")


def write(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    unittest.main()
