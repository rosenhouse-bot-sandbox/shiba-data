import contextlib
import csv
import datetime
import io
import json
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import build  # noqa: E402

DATA = build.years.data_dir(2027)


def data_copy(tmp, presented_rows, year=2027):
    """A copy of DATA, as data for `year`, whose presented.csv also holds presented_rows."""
    data = pathlib.Path(tmp) / str(year)
    shutil.copytree(DATA, data)
    with open(data / build.sheets.PRESENTED, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=build.sheets.COLUMNS, lineterminator="\n").writerows(
            dict(line="", **r) for r in presented_rows)
    return data


def cite(sheet, column, value, url, page, quote, plan_id="H3805-048-0"):
    return dict(sheet=sheet, plan_id=plan_id, column=column, value=value, url=url, pdf_page=page, quote=quote)


def bare_site(**kw):
    empty = {"columns": [], "rows": []}
    return {"docs": {}, "year": 2027, "area": "A", "sections": {}, "plans": [], "main": empty, "dvha": empty, **kw}


H6815_038_EOC = "https://www.wellcareor.com/content/dam/centene/medicare/pdfs/aep/2027/eoc/H6815_038_2027_OR_EOC_HMAPD_7001734ENG_C.pdf"

class NoteWordingTest(unittest.TestCase):
    def test_notes_do_not_name_the_pipeline(self):
        jargon = re.compile(r"reader|expert's|#\d", re.I)
        notes = [r["comment"] for r in build.sheets.notes(DATA)]
        self.assertEqual([n for n in notes if jargon.search(n)], [])


class SiteDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            cls.site = build.site_data(data_copy(tmp, []))

    def cell(self, sheet, plan_id, column):
        row = next(r for r in self.site[sheet]["rows"] if r["plan_id"] == plan_id)
        return row["cells"][column]

    def test_names_the_years_google_sheet(self):
        self.assertEqual(self.site["sheet_id"], build.years.config(DATA)["sheet_id"])

    def test_links_each_pdf_by_its_full_hash(self):
        self.assertEqual({d["file"] for d in self.site["docs"].values()},
                         {f"docs/{d['sha256']}.pdf" for d in self.site["docs"].values()})

    def test_has_all_39_plans_in_each_sheet(self):
        self.assertEqual(len(self.site["plans"]), 39)
        self.assertEqual(len(self.site["main"]["rows"]), 39)
        self.assertEqual(len(self.site["dvha"]["rows"]), 39)

    def test_cited_cell_points_to_document_page_and_quote(self):
        cell = self.cell("main", "H2001-045-0", "H_inpatient")
        self.assertEqual(cell["value"], "$1,980 per admit")
        cite = next(c for c in cell["cites"] if c["page"] == 77)
        self.assertEqual(len(cell["cites"]), len({(c["doc"], c["page"], c["quote"]) for c in cell["cites"]}))
        self.assertIn("$1,980", cite["quote"])
        doc = self.site["docs"][cite["doc"]]
        self.assertEqual(doc["url"], "https://www.aarpmedicareplans.com/alphadog/UHOR27LP0418588_000")
        self.assertEqual(doc["kind"], "EOC")

    def test_cite_keeps_line_number(self):
        cell = self.cell("main", "H3805-041-0", "L_xray_imaging")
        self.assertEqual(sorted({c["line"] for c in cell["cites"]}), [1, 2])

    def test_uncited_cell_has_no_cites(self):
        cell = self.cell("main", "H2406-042-0", "D_premium_full_extra_help")
        self.assertEqual((cell["value"], cell["cites"]), ("$87.70", []))

    def test_a_caveat_the_rule_wrote_is_a_note(self):
        comment = self.cell("main", "H9003-006-0", "X_transportation")["comment"]
        self.assertEqual((comment["kind"], comment["page"]), ("caveat", 99))

    def test_comment_points_to_its_eoc_page(self):
        comment = self.cell("main", "H5439-019-0", "K_tests_labs")["comment"]
        self.assertEqual((comment["doc"], comment["page"]), ("516ff586a12c8288", 90))
        self.assertIn("lab services", comment["quote"])

    def test_comment_kind_is_a_question_caveat_or_contradiction(self):
        self.assertEqual(self.cell("main", "H2923-009-0", "I_outpatient_surgery")["comment"]["kind"], "question")
        with tempfile.TemporaryDirectory() as tmp:
            data = data_copy(tmp, [])
            comment = f"sheet,plan_id,column,kind,comment,url,pdf_page,quote\nmain,H6815-038-0,K_tests_labs,{{}},x,{H6815_038_EOC},83,EKGs\n"
            for kind in ("caveat", "contradiction"):
                (data / "comments.csv").write_text(comment.format(kind))
                row = next(r for r in build.site_data(data)["main"]["rows"] if r["plan_id"] == "H6815-038-0")
                self.assertEqual(row["cells"]["K_tests_labs"]["comment"]["kind"], kind)
            (data / "comments.csv").write_text(comment.format("added"))
            with self.assertRaisesRegex(ValueError, "unknown kind added"):
                build.site_data(data)

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
                (data / "comments.csv").write_text(f"sheet,plan_id,column,kind,comment,url,pdf_page,quote\nmain,{plan_id},{column},question,typo,,,\n")
                with self.assertRaisesRegex(ValueError, f"{plan_id} {column}"):
                    build.site_data(data)

    def test_comment_page_reference_must_name_one_document_page(self):
        for text in ("EOC page 9999 says so.", "Rider page 2 says so."):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp:
                data = data_copy(tmp, [])
                (data / "comments.csv").write_text(
                    f"sheet,plan_id,column,kind,comment,url,pdf_page,quote\nmain,H6815-038-0,K_tests_labs,question,{text},{H6815_038_EOC},83,EKGs\n")
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
            (data / "config.json").write_text(json.dumps({"counties": ["A", "B"], "landscape_zip": "l", "pbp_zip": "p"}))
            site = build.site_data(data)
        self.assertEqual((site["year"], site["area"]), (2099, "A & B"))
        self.assertTrue(site["plans"][0]["plan_finder_url"].startswith(
            "https://www.medicare.gov/plan-compare/#/plan-details/2099-"))

    def test_titles_the_page_with_the_year_and_counties(self):
        html = "<title>Medicare Advantage plans</title><h1>Medicare Advantage plans</h1>"
        self.assertEqual(build.titled(html, {"year": 2099, "area": "A & B"}),
                         "<title>pdxplans.org – 2099 Medicare Advantage plans</title>"
                         "<h1>pdxplans.org – 2099 Medicare Advantage plans <span>for A &amp; B</span></h1>")

    def test_columns_are_the_spec_columns_in_order(self):
        for sheet in ("main", "dvha"):
            self.assertEqual([(c["key"], c["label"]) for c in self.site[sheet]["columns"]],
                             list(build.fields.labels(sheet).items()))
        self.assertIn({"key": "L_xray_imaging", "id": "xray_imaging", "label": "X-Ray / Diag Radiology"}, self.site["main"]["columns"])

    def test_column_ids_drop_the_sheet_letter_and_are_unique(self):
        for sheet in ("main", "dvha"):
            ids = [c["id"] for c in self.site[sheet]["columns"]]
            self.assertEqual(len(set(ids)), len(ids))
            self.assertFalse([i for i in ids if re.match(r"[A-Z]+_", i)])

    def test_uncited_cell_lists_the_cms_fields_behind_it(self):
        self.assertEqual(self.cell("main", "H7006-021-0", "O_medical_deductible")["cms"],
                         [{"file": "pbp_Section_D", "field": "pbp_d_ann_deduct_yn", "title": "Deductible YN?",
                           "value": "2", "meaning": "No"}])

    def test_extra_help_premium_lists_its_landscape_columns_on_both_sheets(self):
        for sheet in ("main", "dvha"):
            self.assertEqual([(f["file"], f["field"], f["value"])
                              for f in self.cell(sheet, "H3805-048-0", "D_premium_full_extra_help")["cms"]],
                             [("Landscape", "Part D Coverage Indicator", "Yes"), ("Landscape", "Part C Premium", "$0.00"),
                              ("Landscape", "Part D Low Income Beneficiary Premium Amount", "$0.00")])

    def test_links_the_cms_files_and_names_the_column_on_medicare_gov(self):
        self.assertEqual(self.site["cms_files"], {"Landscape": "https://www.cms.gov/files/zip/cy2027-landscape-202610.zip",
                                                  "PBP": "https://www.cms.gov/files/zip/pbp-benefits-2027.zip"})
        self.assertIn({"key": "O_medical_deductible", "id": "medical_deductible", "label": "Medical Deductible", "medicare_gov": "It shows this as “Health deductible”."},
                      self.site["main"]["columns"])

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
            cite("main", "G_specialist", "$0-$55", eoc["url"], 80, "specialist quote"),
            cite("dvha", "C_premium", "$0", eoc["url"], 9, "premium quote"),
            cite("main", "O_medical_deductible", "$0", eoc["url"], 9, "deductible quote"),
        ]))

    def tearDown(self):
        self.tmp.cleanup()

    def cites(self, sheet, column):
        return next(r for r in self.site[sheet]["rows"] if r["plan_id"] == "H3805-048-0")["cells"][column]["cites"]

    def test_eoc_cite_replaces_sb_cites(self):
        cites = self.cites("main", "G_specialist")
        self.assertIn({"line": None, "value": "$0-$55", "doc": self.eoc_id, "page": 80, "quote": "specialist quote"}, cites)
        self.assertEqual({c["doc"] for c in cites}, {self.eoc_id})

    def test_eoc_cite_goes_to_its_own_sheet(self):
        self.assertIn("premium quote", [c["quote"] for c in self.cites("dvha", "C_premium")])
        self.assertNotIn("premium quote", [c["quote"] for c in self.cites("main", "C_premium")])

    def test_a_cite_of_an_unknown_document_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = data_copy(tmp, [cite("main", "E_moop", "$6,700", "https://x/reissued.pdf", 45, "q")])
            with self.assertRaisesRegex(ValueError, "main H3805-048-0 E_moop.*reissued.pdf"):
                build.site_data(data)

    def test_cited_cell_lists_no_cms_fields(self):
        cell = next(r for r in self.site["main"]["rows"] if r["plan_id"] == "H3805-048-0")["cells"]["O_medical_deductible"]
        self.assertNotIn("cms", cell)


class SiteCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.traces = self.enterContext(mock.patch.object(build, "write_traces"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_docs_command_lists_each_linked_pdfs_hash(self):
        site = bare_site(docs={"a" * 16: {"sha256": "a" * 64}, "b" * 16: {"sha256": "b" * 64}})
        out = io.StringIO()
        with mock.patch.object(build, "site_data", return_value=site), contextlib.redirect_stdout(out):
            build.main("docs")
        self.assertEqual(out.getvalue(), f"{'a' * 64}\n{'b' * 64}\n")

    def test_site_command_writes_traces_from_the_commit(self):
        with mock.patch.object(build, "site_data", return_value=bare_site()), mock.patch.object(build, "commit", return_value="abc"):
            build.main("site", self.dir / "site")
        self.traces.assert_called_once_with(self.dir / "site", "abc")

    def test_site_command_records_build_time_and_titles_the_page(self):
        with mock.patch.object(build, "site_data", return_value=bare_site(year=2099, area="A & B")):
            build.main("site", self.dir / "site")
        built = datetime.datetime.fromisoformat(json.loads((self.dir / "site" / "data.json").read_text())["built"])
        self.assertLess(datetime.datetime.now(datetime.timezone.utc) - built, datetime.timedelta(minutes=1))
        self.assertIn("<title>pdxplans.org – 2099 Medicare Advantage plans</title>", (self.dir / "site" / "index.html").read_text())

    def test_site_command_hosts_pdfjs_itself(self):
        with mock.patch.object(build, "site_data", return_value=bare_site()):
            build.main("site", self.dir / "site")
        site = self.dir / "site"
        for name in ["pdf.min.mjs", "pdf.worker.min.mjs", "pdf_viewer.css"]:
            self.assertTrue((site / "pdfjs" / name).is_file(), name)
        for page in [*site.glob("*.html"), *site.glob("*.js")]:
            self.assertNotIn("https://cdn", page.read_text(), page.name)


class TraceFilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = pathlib.Path(self.tmp.name)

    def test_writes_each_cells_trace(self):
        build.write_traces(self.dir / "site", "abc")
        year = build.years.config(build.DATA)["year"]
        traces = self.dir / f"site/trace/{year}"
        by_sheet = build.sheets.read(build.DATA)
        cells = {f"{sheet}/{r['plan_id']}/{col}.json" for sheet in ("main", "dvha") for r in by_sheet[sheet]
                 for col in build.fields.labels(sheet)}
        self.assertEqual({str(p.relative_to(traces)) for p in traces.rglob("*.json")}, cells)
        build.trace.build(year, self.dir / "trace.sqlite", "abc")
        with contextlib.closing(sqlite3.connect(self.dir / "trace.sqlite")) as db:
            for key in (("main", "H1036-153-0", "AB_ambulance"), ("dvha", "H1036-153-0", "F_dental")):
                self.assertEqual(json.loads((traces / "/".join(key)).with_suffix(".json").read_text()), build.trace.cell(db, *key))

    def test_each_pipeline_step_names_a_record_of_the_trace(self):
        build.trace.build(2027, self.dir / "trace.sqlite", "abc")
        with contextlib.closing(sqlite3.connect(self.dir / "trace.sqlite")) as db:
            records = build.trace.cell(db, "main", "H1036-153-0", "AB_ambulance")
        script = 'import("./static/pipeline.js").then((m) => console.log(JSON.stringify(m.STEPS.map((s) => s.record))))'
        named = json.loads(subprocess.run(["node", "-e", script], cwd=build.HERE, capture_output=True, text=True, check=True).stdout)
        self.assertEqual([r for r in named if r not in records], [])
