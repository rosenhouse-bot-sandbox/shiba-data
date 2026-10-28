import contextlib
import csv
import datetime
import hashlib
import io
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import build  # noqa: E402

DATA = build.years.data_dir(2027)


def data_copy(tmp, machine_rows, year=2027):
    """A copy of DATA, as data for `year`, whose machine layer holds only machine_rows."""
    data = pathlib.Path(tmp) / str(year)
    shutil.copytree(DATA, data)
    with open(data / "machine/eoc_citations.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=build.layers.MACHINE_COLUMNS)
        w.writeheader()
        w.writerows(dict(step="test", prompt="", line="", **r) for r in machine_rows)
    return data


def cite(sheet, column, value, url, page, quote, plan_id="H3805-048-0"):
    return dict(sheet=sheet, plan_id=plan_id, column=column, value=value, url=url, pdf_page=page, quote=quote)


H6815_038_EOC = "https://www.wellcareor.com/content/dam/centene/medicare/pdfs/aep/2027/eoc/H6815_038_2027_OR_EOC_HMAPD_7001734ENG_C.pdf"

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

    def test_comment_kind_says_whether_eoc_contradicts_cell(self):
        self.assertEqual(self.cell("main", "H6815-038-0", "K_tests_labs")["comment"]["kind"], "note")
        self.assertEqual(self.cell("dvha", "H1036-306-0", "F_dental")["comment"]["kind"], "note")
        with tempfile.TemporaryDirectory() as tmp:
            data = data_copy(tmp, [])
            (data / "comments.csv").write_text(
                f"sheet,plan_id,column,kind,comment,url,pdf_page,quote\nmain,H6815-038-0,K_tests_labs,contradicts,x,{H6815_038_EOC},83,EKGs\n")
            rows = build.site_data(data)["main"]["rows"]
        row = next(r for r in rows if r["plan_id"] == "H6815-038-0")
        self.assertEqual(row["cells"]["K_tests_labs"]["comment"]["kind"], "contradicts")

    def test_unknown_comment_kind_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = data_copy(tmp, [])
            (data / "comments.csv").write_text(
                f"sheet,plan_id,column,kind,comment,url,pdf_page,quote\nmain,H6815-038-0,K_tests_labs,warning,x,{H6815_038_EOC},83,EKGs\n")
            with self.assertRaisesRegex(ValueError, "warning"):
                build.site_data(data)

    def test_comment_on_unknown_cell_fails(self):
        for plan_id, column in (("H6815-038-0", "K_tests"), ("H6815-999-0", "K_tests_labs")):
            with self.subTest(plan_id=plan_id, column=column), tempfile.TemporaryDirectory() as tmp:
                data = data_copy(tmp, [])
                (data / "comments.csv").write_text(f"sheet,plan_id,column,kind,comment,url,pdf_page,quote\nmain,{plan_id},{column},note,typo,,,\n")
                with self.assertRaisesRegex(ValueError, f"{plan_id} {column}"):
                    build.site_data(data)

    def test_comment_page_reference_must_name_one_document_page(self):
        for text in ("EOC page 9999 says so.", "Rider page 2 says so."):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp:
                data = data_copy(tmp, [])
                (data / "comments.csv").write_text(
                    f"sheet,plan_id,column,kind,comment,url,pdf_page,quote\nmain,H6815-038-0,K_tests_labs,note,{text},{H6815_038_EOC},83,EKGs\n")
                with self.assertRaisesRegex(ValueError, text.split(" says")[0]):
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

    def test_names_the_plan_year_and_counties(self):
        self.assertEqual((self.site["year"], self.site["area"]), (2027, "Multnomah & Clackamas"))
        with tempfile.TemporaryDirectory() as tmp:
            data = data_copy(tmp, [], year=2099)
            (data / "config.json").write_text(json.dumps({"counties": ["A", "B"]}))
            site = build.site_data(data)
        self.assertEqual((site["year"], site["area"]), (2099, "A & B"))
        self.assertTrue(site["plans"][0]["plan_finder_url"].startswith(
            "https://www.medicare.gov/plan-compare/#/plan-details/2099-"))

    def test_titles_the_page_with_the_year_and_counties(self):
        html = "<title>Medicare Advantage plans</title><h1>Medicare Advantage plans</h1>"
        self.assertEqual(build.titled(html, {"year": 2099, "area": "A & B"}),
                         "<title>2099 Medicare Advantage plans: A &amp; B</title>"
                         "<h1>2099 Medicare Advantage plans <span>A &amp; B</span></h1>")

    def test_columns_are_the_spec_columns_in_order(self):
        for sheet in ("main", "dvha"):
            self.assertEqual([(c["key"], c["label"]) for c in self.site[sheet]["columns"]],
                             list(build.fields.labels(sheet).items()))
        self.assertIn({"key": "L_xray_imaging", "label": "X-Ray / Diag Radiology"}, self.site["main"]["columns"])

    def test_doc_ids_are_sha_prefixes(self):
        for doc_id, doc in self.site["docs"].items():
            self.assertEqual(doc_id, doc["sha256"][:16])


class EocCitationsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        eoc = next(d for d in build.rows("generated/documents_checked.csv", DATA)
                   if d["kind"] == "EOC" and "H3805-048-0" in d["plan_ids"])
        self.eoc_id = eoc["sha256"][:16]
        self.site = build.site_data(data_copy(self.tmp.name, [
            cite("main", "L_xray_imaging", "$30 | $320", eoc["url"], 80, "x-ray quote"),
            cite("dvha", "C_premium", "$0", eoc["url"], 9, "premium quote"),
            cite("main", "L_xray_imaging", "$30 | $0-$320", eoc["url"], 76, "stale quote"),
        ]))

    def tearDown(self):
        self.tmp.cleanup()

    def cites(self, sheet, column):
        return next(r for r in self.site[sheet]["rows"] if r["plan_id"] == "H3805-048-0")["cells"][column]["cites"]

    def test_eoc_cite_replaces_sb_cites(self):
        cites = self.cites("main", "L_xray_imaging")
        self.assertEqual(cites, [{"line": None, "value": "$30 | $320", "doc": self.eoc_id, "page": 80, "quote": "x-ray quote"}])

    def test_eoc_cite_goes_to_its_own_sheet(self):
        self.assertIn("premium quote", [c["quote"] for c in self.cites("dvha", "C_premium")])
        self.assertNotIn("premium quote", [c["quote"] for c in self.cites("main", "C_premium")])

    def test_a_cite_of_an_unknown_document_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = data_copy(tmp, [cite("main", "E_moop", "$6,700", "https://x/reissued.pdf", 45, "q")])
            with self.assertRaisesRegex(ValueError, "machine/eoc_citations.csv main H3805-048-0 E_moop.*reissued.pdf"):
                build.site_data(data)

    def test_drops_a_cite_whose_value_an_edit_changed(self):
        self.assertNotIn("stale quote", [c["quote"] for c in self.cites("main", "L_xray_imaging")])


class EditsTest(unittest.TestCase):
    def dental(self, url, page="4", quote="dental quote"):
        with tempfile.TemporaryDirectory() as tmp:
            data = data_copy(tmp, [])
            with open(data / "edits.csv", "a", newline="") as f:
                csv.DictWriter(f, fieldnames=build.layers.EDIT_COLUMNS).writerow(
                    dict(cite("dvha", "F_dental", "fixed", url, page, quote), line="", saw="", source="volunteer",
                         author="v1", note=""))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                site = build.site_data(data)
        return next(r for r in site["dvha"]["rows"] if r["plan_id"] == "H3805-048-0")["cells"]["F_dental"], site, out.getvalue()

    def test_an_edit_sets_its_dvha_cell_and_keeps_the_pbp_value(self):
        sb = next(d for d in build.rows("generated/documents_checked.csv", DATA)
                  if d["kind"] == "SB" and "H3805-048-0" in d["plan_ids"])
        cell, site, _ = self.dental(sb["url"])
        generated = next(r for r in build.rows("generated/dvha.csv", DATA) if r["plan_id"] == "H3805-048-0")
        self.assertEqual((cell["value"], cell["pbp"]), ("fixed", generated["F_dental"]))
        self.assertEqual([(c["value"], c["page"], c["quote"]) for c in cell["cites"]], [("fixed", 4, "dental quote")])
        self.assertNotIn("dental quote", str(site["main"]))

    def test_an_uncited_edit_sets_its_cell(self):
        cell, _, out = self.dental("", "", "")
        self.assertEqual((cell["value"], cell["cites"], out), ("fixed", [], ""))

    def test_an_edit_of_an_unknown_document_sets_its_cell_and_warns(self):
        cell, _, out = self.dental("https://x/unknown.pdf")
        self.assertEqual((cell["value"], cell["cites"]), ("fixed", []))
        self.assertIn("::warning::", out)
        self.assertIn("edits.csv dvha H3805-048-0 F_dental https://x/unknown.pdf", out)


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
        site = {"docs": {i: {"url": d["url"], "sha256": d["sha256"]} for i, d in self.docs.items()}, "year": 2027, "area": "A"}
        out = io.StringIO()
        with mock.patch.object(build, "site_data", return_value=site), contextlib.redirect_stdout(out):
            build.main("site", self.dir / "site", self.dir / "release")
        data = json.loads((self.dir / "site" / "data.json").read_text())
        self.assertEqual(data["docs"][self.id]["file"], f"pdfs/{self.id}.pdf")
        self.assertIn("::warning::", out.getvalue())
        self.assertIn("gone.pdf", out.getvalue())

    def test_site_command_warns_of_dropped_cites(self):
        dropped = dict(cite("main", "E_moop", "$6,800", "u", 45, "stale quote"), layer="edits.csv", line="")
        out = io.StringIO()
        with (mock.patch.object(build, "site_data", return_value={"docs": {}, "year": 2027, "area": "A"}),
              mock.patch.object(build.layers, "live", return_value=({}, [], [dropped])), contextlib.redirect_stdout(out)):
            build.main("site", self.dir / "site")
        self.assertIn("::warning::", out.getvalue())
        self.assertIn("edits.csv main H3805-048-0 E_moop", out.getvalue())

    def test_site_command_warns_of_an_edit_whose_cell_changed_beneath_it(self):
        edit = dict(cite("main", "E_moop", "$6,800", "u", 45, "q"), layer="edits.csv", line="", saw="$6,700", beneath="$6,900")
        out = io.StringIO()
        with (mock.patch.object(build, "site_data", return_value={"docs": {}, "year": 2027, "area": "A"}),
              mock.patch.object(build.layers, "live", return_value=({}, [], [edit])), contextlib.redirect_stdout(out)):
            build.main("site", self.dir / "site")
        self.assertIn("::warning::An edit's author saw $6,700, but the cell beneath it is now $6,900: "
                      "edits.csv main H3805-048-0 E_moop", out.getvalue())

    def test_site_command_records_build_time_and_titles_the_page(self):
        with mock.patch.object(build, "site_data", return_value={"docs": {}, "year": 2099, "area": "A & B"}):
            build.main("site", self.dir / "site")
        built = datetime.datetime.fromisoformat(json.loads((self.dir / "site" / "data.json").read_text())["built"])
        self.assertLess(datetime.datetime.now(datetime.timezone.utc) - built, datetime.timedelta(minutes=1))
        self.assertIn("<title>2099 Medicare Advantage plans: A &amp; B</title>", (self.dir / "site" / "index.html").read_text())


class ZipTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.data = self.dir / "data"
        (self.data / "generated").mkdir(parents=True)
        with open(self.data / "generated/documents_checked.csv", "w", newline="") as f:
            csv.writer(f).writerows([
                ["plan_ids", "kind", "sha256", "plan_names"],
                ["H1-001-0;H1-002-0", "EOC", "a" * 64, "Plan A (HMO); Plan B (PPO)"],
                ["H1-001-0", "SB", "b" * 64, "Plan A (HMO)"],
                ["H1-002-0", "SB", "c" * 64, "Plan B (PPO)"],
            ])
        self.release = self.dir / "release"
        (self.release / "pdfs").mkdir(parents=True)
        manifest = {}
        for doc_id in ("a" * 16, "b" * 16, "d" * 16):
            manifest[doc_id] = {"file": f"pdfs/{doc_id}.pdf"}
            (self.release / f"pdfs/{doc_id}.pdf").write_bytes(f"%PDF {doc_id}".encode())
        (self.release / "documents.json").write_text(json.dumps(manifest))
        build.zip_documents(self.release, self.dir / "documents.zip", self.data)
        self.zip = zipfile.ZipFile(self.dir / "documents.zip")

    def tearDown(self):
        self.zip.close()
        self.tmp.cleanup()

    def test_names_each_plans_copy_of_a_pdf_after_the_plan(self):
        self.assertEqual(self.zip.read("Plan A (HMO) (H1-001-0) EOC.pdf"), b"%PDF " + b"a" * 16)
        self.assertEqual(self.zip.read("Plan B (PPO) (H1-002-0) EOC.pdf"), b"%PDF " + b"a" * 16)
        self.assertEqual(self.zip.read("Plan A (HMO) (H1-001-0) SB.pdf"), b"%PDF " + b"b" * 16)

    def test_keeps_hash_name_for_pdf_missing_from_data(self):
        self.assertEqual(self.zip.read(f"pdfs/{'d' * 16}.pdf"), b"%PDF " + b"d" * 16)

    def test_holds_only_pdfs_in_release(self):
        self.assertEqual(sorted(self.zip.namelist()), [
            "Plan A (HMO) (H1-001-0) EOC.pdf",
            "Plan A (HMO) (H1-001-0) SB.pdf",
            "Plan B (PPO) (H1-002-0) EOC.pdf",
            f"pdfs/{'d' * 16}.pdf",
        ])

    def test_fails_when_plan_names_and_ids_differ_in_count(self):
        with self.assertRaises(ValueError):
            list(build.plan_names({"plan_ids": "H1-001-0;H1-002-0", "plan_names": "Plan A (HMO)"}))

    def test_zip_command_writes_zip(self):
        build.main("zip", self.release, self.dir / "cli.zip")
        self.assertIn(f"pdfs/{'d' * 16}.pdf", zipfile.ZipFile(self.dir / "cli.zip").namelist())


class ZipDataTest(unittest.TestCase):
    def test_each_plan_has_one_pdf_per_kind(self):
        names = [build.zip_name(plan_id, name, d["kind"])
                 for d in build.rows("generated/documents_checked.csv", DATA)
                 for plan_id, name in build.plan_names(d)]
        self.assertEqual(len(names), len(set(names)))

    def test_names_are_valid_on_windows(self):
        for d in build.rows("generated/documents_checked.csv", DATA):
            for plan_id, name in build.plan_names(d):
                self.assertRegex(build.zip_name(plan_id, name, d["kind"]), r'^[^<>:"/\\|?*]+$')


if __name__ == "__main__":
    unittest.main()
