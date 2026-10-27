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


class SiteDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.site = build.site_data(DATA)

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
        self.assertEqual(cell["cites"][0]["line"], 2)

    def test_uncited_cell_has_no_cites(self):
        self.assertEqual(self.cell("main", "H3805-048-0", "D_premium_full_extra_help"), {"value": "$0", "cites": []})

    def test_pbp_override_is_attached_to_cell(self):
        cell = self.cell("main", "H3805-048-0", "L_xray_imaging")
        self.assertEqual(cell["pbp"], "$30 | $0-$320")

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
        self.data = pathlib.Path(self.tmp.name)
        for f in DATA.glob("*.csv"):
            (self.data / f.name).write_bytes(f.read_bytes())
        eoc = next(d["url"] for d in build.rows("documents_checked.csv", DATA)
                   if d["kind"] == "EOC" and "H3805-048-0" in d["plan_ids"])
        with open(self.data / "eoc_citations.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["sheet", "plan_id", "column", "value", "url", "pdf_page", "quote"])
            w.writerow(["main", "H3805-048-0", "L_xray_imaging", "$30 | $320", eoc, 80, "x-ray quote"])
            w.writerow(["dvha", "H3805-048-0", "C_premium", "$0", eoc, 9, "premium quote"])

    def tearDown(self):
        self.tmp.cleanup()

    def cell(self, site, sheet, column):
        return next(r for r in site[sheet]["rows"] if r["plan_id"] == "H3805-048-0")["cells"][column]

    def test_eoc_cite_follows_existing_cites(self):
        cell = self.cell(build.site_data(self.data), "main", "L_xray_imaging")
        self.assertEqual([c["quote"] for c in cell["cites"]][-1], "x-ray quote")
        self.assertEqual(cell["cites"][-1], {"line": None, "value": "$30 | $320", "doc": cell["cites"][-1]["doc"],
                                             "page": 80, "quote": "x-ray quote"})
        self.assertGreater(len(cell["cites"]), 1)

    def test_eoc_cite_goes_to_its_own_sheet(self):
        site = build.site_data(self.data)
        self.assertEqual([c["quote"] for c in self.cell(site, "dvha", "C_premium")["cites"]], ["premium quote"])
        self.assertEqual(self.cell(site, "main", "C_premium")["cites"], [])


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
