import contextlib
import csv
import hashlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import build  # noqa: E402

DATA = pathlib.Path(__file__).resolve().parents[2] / "repro" / "data"


EOC_HEADER = ["sheet", "plan_id", "column", "value", "url", "pdf_page", "quote"]


def data_copy(tmp, eoc_rows):
    """A copy of DATA whose eoc_citations.csv holds only eoc_rows."""
    data = pathlib.Path(tmp)
    for f in DATA.glob("*.csv"):
        (data / f.name).write_bytes(f.read_bytes())
    with open(data / "eoc_citations.csv", "w", newline="") as f:
        csv.writer(f).writerows([EOC_HEADER, *eoc_rows])
    return data


class SiteDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            cls.site = build.site_data(data_copy(tmp, []))

    def cell(self, sheet, plan_id, column):
        row = next(r for r in self.site[sheet]["rows"] if r["plan_id"] == plan_id)
        return row["cells"][column]

    def test_has_all_39_plans_in_each_sheet(self):
        self.assertEqual(len(self.site["plans"]), 39)
        self.assertEqual(len(self.site["main"]["rows"]), 39)
        self.assertEqual(len(self.site["dvha"]["rows"]), 39)

    def test_cited_cell_points_to_document_page_and_quote(self):
        cell = self.cell("main", "H2001-045-0", "H_inpatient")
        self.assertEqual(cell["value"], "$0 or $1,980 per stay")
        [cite] = cell["cites"]
        self.assertEqual(cite["page"], 6)
        self.assertIn("$1,980 copay per stay", cite["quote"])
        doc = self.site["docs"][cite["doc"]]
        self.assertEqual(doc["url"], "https://www.aarpmedicareplans.com/alphadog/UHOR27LP0412518_000")
        self.assertEqual(doc["kind"], "SB")

    def test_cite_keeps_line_number(self):
        cell = self.cell("main", "H3805-048-0", "L_xray_imaging")
        self.assertEqual([c["line"] for c in cell["cites"]], [2])

    def test_uncited_cell_has_no_cites(self):
        self.assertEqual(self.cell("main", "H3805-048-0", "E_moop"), {"value": "$6,700", "cites": []})

    def test_pbp_override_is_attached_to_cell(self):
        cell = self.cell("main", "H3805-048-0", "L_xray_imaging")
        self.assertEqual(cell["pbp"], "$30 | $0-$320")

    def test_wellcare_tests_cells_carry_ekg_comment(self):
        for plan_id in ("H6815-038-0", "H5439-015-0", "H5439-019-0", "H5439-011-0", "H5439-010-0"):
            self.assertIn("EKG", self.cell("main", plan_id, "K_tests_labs")["comment"]["text"], plan_id)

    def test_comment_points_to_its_eoc_page(self):
        comment = self.cell("main", "H6815-038-0", "K_tests_labs")["comment"]
        self.assertEqual((comment["doc"], comment["page"]), ("90a4efa6544175a2", 83))
        self.assertIn("EKGs", comment["quote"])

    def test_comment_on_unknown_cell_fails(self):
        for plan_id, column in (("H6815-038-0", "K_tests"), ("H6815-999-0", "K_tests_labs")):
            with self.subTest(plan_id=plan_id, column=column), tempfile.TemporaryDirectory() as tmp:
                data = data_copy(tmp, [])
                (data / "comments.csv").write_text(f"sheet,plan_id,column,comment,url,pdf_page,quote\nmain,{plan_id},{column},typo,,,\n")
                with self.assertRaisesRegex(ValueError, f"{plan_id} {column}"):
                    build.site_data(data)

    def test_second_comment_on_a_cell_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = data_copy(tmp, [])
            with open(data / "comments.csv", newline="") as f:
                first = list(csv.reader(f))[1]
            with open(data / "comments.csv", "a", newline="") as f:
                csv.writer(f).writerow(first)
            with self.assertRaisesRegex(ValueError, f"{first[1]} {first[2]}"):
                build.site_data(data)

    def test_every_plan_has_an_sb(self):
        for p in self.site["plans"]:
            kinds = [self.site["docs"][d]["kind"] for d in p["docs"]]
            self.assertIn("SB", kinds, p["plan_id"])

    def test_plan_links_to_medicare_plan_finder(self):
        plan = next(p for p in self.site["plans"] if p["plan_id"] == "H2923-028-3")
        self.assertEqual(plan["plan_finder_url"],
                         "https://www.medicare.gov/plan-compare/#/plan-details/2027-H2923-028-3?year=2027&lang=en")

    def test_columns_have_labels(self):
        labels = {c["key"]: c["label"] for c in self.site["main"]["columns"]}
        self.assertEqual(labels["L_xray_imaging"], "X-Ray / Diag Radiology")
        labels = {c["key"]: c["label"] for c in self.site["dvha"]["columns"]}
        self.assertEqual(labels["F_dental"], "Included Dental")

    def test_doc_ids_are_sha_prefixes(self):
        for doc_id, doc in self.site["docs"].items():
            self.assertEqual(doc_id, doc["sha256"][:16])


class EocCitationsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        eoc = next(d for d in build.rows("documents_checked.csv", DATA)
                   if d["kind"] == "EOC" and "H3805-048-0" in d["plan_ids"])
        self.eoc_id = eoc["sha256"][:16]
        self.site = build.site_data(data_copy(self.tmp.name, [
            ["main", "H3805-048-0", "L_xray_imaging", "$30 | $320", eoc["url"], 80, "x-ray quote"],
            ["dvha", "H3805-048-0", "C_premium", "$0", eoc["url"], 9, "premium quote"],
        ]))

    def tearDown(self):
        self.tmp.cleanup()

    def cites(self, sheet, column):
        return next(r for r in self.site[sheet]["rows"] if r["plan_id"] == "H3805-048-0")["cells"][column]["cites"]

    def test_eoc_cite_follows_existing_cites(self):
        cites = self.cites("main", "L_xray_imaging")
        self.assertEqual([(c["line"], c["quote"]) for c in cites], [(2, "$320 copay otherwise"), (None, "x-ray quote")])
        self.assertEqual(cites[-1], {"line": None, "value": "$30 | $320", "doc": self.eoc_id, "page": 80, "quote": "x-ray quote"})

    def test_eoc_cite_goes_to_its_own_sheet(self):
        self.assertEqual([c["quote"] for c in self.cites("dvha", "C_premium")], ["premium quote"])
        self.assertEqual(self.cites("main", "C_premium"), [])


class DvhaCitationsTest(unittest.TestCase):
    def test_dvha_citation_and_pbp_value_go_to_dvha_cell(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = data_copy(tmp, [])
            sb = next(d for d in build.rows("documents_checked.csv", DATA)
                      if d["kind"] == "SB" and "H3805-048-0" in d["plan_ids"])
            with open(data / "citations.csv", "a", newline="") as f:
                csv.writer(f).writerow(["H3805-048-0", "dvha.F_dental", "", "fixed", "SB", sb["url"], 4, "dental quote"])
            with open(data / "pbp_vs_documents_dvha.csv", "w", newline="") as f:
                csv.writer(f).writerows([["plan_id", "column", "pbp", "documents", "citations"],
                                         ["H3805-048-0", "F_dental", "", "fixed", "SB p4"]])
            site = build.site_data(data)
        row = next(r for r in site["dvha"]["rows"] if r["plan_id"] == "H3805-048-0")
        cell = row["cells"]["F_dental"]
        self.assertEqual(cell["pbp"], "")
        self.assertEqual([(c["value"], c["page"], c["quote"]) for c in cell["cites"]], [("fixed", 4, "dental quote")])
        self.assertNotIn("dvha.F_dental", str(site["main"]))


class EocCitationsDataTest(unittest.TestCase):
    def test_each_cites_the_current_cell_value(self):
        sheets = {"main": ("main_chart.csv", build.MAIN_LABELS), "dvha": ("dvha.csv", build.DVHA_LABELS)}
        for c in build.rows("eoc_citations.csv", DATA):
            name, labels = sheets[c["sheet"]]
            row = next(r for r in build.rows(name, DATA) if r["plan_id"] == c["plan_id"])
            self.assertIn(c["column"], labels)
            self.assertEqual(c["value"], row[c["column"]], c)


class FetchPdfsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.src = self.dir / "src.pdf"
        self.src.write_bytes(b"%PDF-1.4 test")
        sha = hashlib.sha256(self.src.read_bytes()).hexdigest()
        self.docs = {sha[:16]: {"url": self.src.as_uri(), "sha256": sha}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_saves_matching_pdf_and_records_date(self):
        build.fetch_pdfs(self.docs, self.dir / "site", "2026-10-26")
        [doc] = self.docs.values()
        self.assertEqual(doc["file"], f"pdfs/{doc['sha256'][:16]}.pdf")
        self.assertEqual(doc["retrieved"], "2026-10-26")
        self.assertFalse(doc["changed"])
        self.assertEqual((self.dir / "site" / doc["file"]).read_bytes(), b"%PDF-1.4 test")

    def test_flags_changed_pdf(self):
        self.src.write_bytes(b"%PDF-1.4 reissued")
        build.fetch_pdfs(self.docs, self.dir / "site", "2026-10-26")
        [doc] = self.docs.values()
        self.assertTrue(doc["changed"])
        self.assertTrue(os.path.exists(self.dir / "site" / doc["file"]))

    def test_reports_failed_download(self):
        self.src.write_bytes(b"<html>not found</html>")
        failed = build.fetch_pdfs(self.docs, self.dir / "site", "2026-10-26")
        [doc] = self.docs.values()
        self.assertIsNone(doc["file"])
        self.assertEqual(failed, [doc["url"]])

    def test_reports_no_failures(self):
        self.assertEqual(build.fetch_pdfs(self.docs, self.dir / "site", "2026-10-26"), [])


class DocumentsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.src = self.dir / "src.pdf"
        self.src.write_bytes(b"%PDF-1.4 test")
        sha = hashlib.sha256(self.src.read_bytes()).hexdigest()
        self.id = sha[:16]
        self.docs = {self.id: {"url": self.src.as_uri(), "sha256": sha},
                     "0000000000000000": {"url": (self.dir / "gone.pdf").as_uri(), "sha256": "0" * 64}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_release_holds_downloaded_pdfs_and_manifest(self):
        failed = build.save_documents(self.docs, self.dir / "release", "2026-10-27")
        self.assertEqual(failed, [self.docs["0000000000000000"]["url"]])
        manifest = json.loads((self.dir / "release" / "documents.json").read_text())
        self.assertEqual(manifest, {self.id: {"file": f"pdfs/{self.id}.pdf", "retrieved": "2026-10-27", "changed": False}})
        self.assertTrue((self.dir / "release" / f"pdfs/{self.id}.pdf").exists())

    def test_site_uses_release_pdfs_and_marks_others_missing(self):
        build.save_documents(self.docs, self.dir / "release", "2026-10-27")
        site_docs = {i: {"url": d["url"], "sha256": d["sha256"]} for i, d in self.docs.items()}
        missing = build.attach_documents(site_docs, self.dir / "release", self.dir / "site")
        self.assertEqual(missing, ["0000000000000000"])
        self.assertEqual(site_docs[self.id]["retrieved"], "2026-10-27")
        self.assertIsNone(site_docs["0000000000000000"]["file"])
        self.assertEqual((self.dir / "site" / f"pdfs/{self.id}.pdf").read_bytes(), b"%PDF-1.4 test")


    def test_documents_command_fails_when_a_download_fails(self):
        with mock.patch.object(build, "site_data", return_value={"docs": self.docs}):
            with self.assertRaises(SystemExit) as e:
                build.main("documents", self.dir / "release")
        self.assertIn("gone.pdf", str(e.exception.code))

    def test_site_command_attaches_release(self):
        build.save_documents(self.docs, self.dir / "release", "2026-10-27")
        site = {"docs": {i: {"url": d["url"], "sha256": d["sha256"]} for i, d in self.docs.items()}}
        out = io.StringIO()
        with mock.patch.object(build, "site_data", return_value=site), contextlib.redirect_stdout(out):
            build.main("site", self.dir / "site", self.dir / "release")
        data = json.loads((self.dir / "site" / "data.json").read_text())
        self.assertEqual(data["docs"][self.id]["file"], f"pdfs/{self.id}.pdf")
        self.assertIn("::warning::", out.getvalue())
        self.assertIn("gone.pdf", out.getvalue())


if __name__ == "__main__":
    unittest.main()
