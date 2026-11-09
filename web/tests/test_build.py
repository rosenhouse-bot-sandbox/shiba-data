import contextlib
import csv
import datetime
import io
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile
import unittest
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


def bare_site(**kw):
    empty = {"columns": [], "rows": []}
    return {"docs": {}, "year": 2027, "area": "A", "sections": {}, "plans": [], "main": empty, "dvha": empty, **kw}


H6815_038_EOC = "https://www.wellcareor.com/content/dam/centene/medicare/pdfs/aep/2027/eoc/H6815_038_2027_OR_EOC_HMAPD_7001734ENG_C.pdf"

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
        self.assertEqual(cell["value"], "$1,980 per admission")
        cite = next(c for c in cell["cites"] if c["page"] == 77)
        self.assertEqual(len(cell["cites"]), len({(c["doc"], c["page"], c["quote"]) for c in cell["cites"]}))
        self.assertIn("$1,980", cite["quote"])
        doc = self.site["docs"][cite["doc"]]
        self.assertEqual(doc["url"], "https://www.aarpmedicareplans.com/alphadog/UHOR27LP0418588_000")
        self.assertEqual(doc["kind"], "EOC")

    def test_cite_keeps_line_number(self):
        cell = self.cell("main", "H3805-041-0", "L_xray_imaging")
        self.assertEqual([c["line"] for c in cell["cites"]], [1, 2, 2])

    def test_uncited_cell_has_no_cites(self):
        self.assertEqual(self.cell("main", "H3805-048-0", "E_moop"), {"value": "$6,700", "cites": []})

    def test_pbp_override_is_attached_to_cell(self):
        cell = self.cell("main", "H3805-048-0", "G_specialist")
        self.assertEqual(cell["pbp"], "$0-$55")

    def test_wellcare_tests_cells_carry_ekg_comment(self):
        for plan_id in ("H6815-038-0", "H5439-015-0", "H5439-019-0", "H5439-011-0", "H5439-010-0"):
            self.assertIn("EKG", self.cell("main", plan_id, "K_tests_labs")["comment"]["text"], plan_id)

    def test_comment_points_to_its_eoc_page(self):
        comment = self.cell("main", "H6815-038-0", "K_tests_labs")["comment"]
        self.assertEqual((comment["doc"], comment["page"]), ("90a4efa6544175a2", 83))
        self.assertIn("EKGs", comment["quote"])

    def test_comment_kind_is_a_question_or_a_hand_written_fact(self):
        self.assertEqual(self.cell("main", "H6815-038-0", "K_tests_labs")["comment"]["kind"], "question")
        with tempfile.TemporaryDirectory() as tmp:
            data = data_copy(tmp, [])
            (data / "comments.csv").write_text(
                f"sheet,plan_id,column,kind,comment,url,pdf_page,quote\nmain,H6815-038-0,K_tests_labs,hand_written,x,{H6815_038_EOC},83,EKGs\n")
            rows = build.site_data(data)["main"]["rows"]
        row = next(r for r in rows if r["plan_id"] == "H6815-038-0")
        self.assertEqual(row["cells"]["K_tests_labs"]["comment"]["kind"], "hand_written")

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
            cite("main", "G_specialist", "$55", eoc["url"], 80, "specialist quote"),
            cite("dvha", "C_premium", "$0", eoc["url"], 9, "premium quote"),
            cite("main", "G_specialist", "$0-$55", eoc["url"], 76, "stale quote"),
            cite("main", "O_medical_deductible", "$0", eoc["url"], 9, "deductible quote"),
        ]))

    def tearDown(self):
        self.tmp.cleanup()

    def cites(self, sheet, column):
        return next(r for r in self.site[sheet]["rows"] if r["plan_id"] == "H3805-048-0")["cells"][column]["cites"]

    def test_eoc_cite_replaces_sb_cites(self):
        cites = self.cites("main", "G_specialist")
        self.assertIn({"line": None, "value": "$55", "doc": self.eoc_id, "page": 80, "quote": "specialist quote"}, cites)
        self.assertEqual({c["doc"] for c in cites}, {self.eoc_id})

    def test_eoc_cite_goes_to_its_own_sheet(self):
        self.assertIn("premium quote", [c["quote"] for c in self.cites("dvha", "C_premium")])
        self.assertNotIn("premium quote", [c["quote"] for c in self.cites("main", "C_premium")])

    def test_a_cite_of_an_unknown_document_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = data_copy(tmp, [cite("main", "E_moop", "$6,700", "https://x/reissued.pdf", 45, "q")])
            with self.assertRaisesRegex(ValueError, "machine/eoc_citations.csv main H3805-048-0 E_moop.*reissued.pdf"):
                build.site_data(data)

    def test_cited_cell_lists_no_cms_fields(self):
        cell = next(r for r in self.site["main"]["rows"] if r["plan_id"] == "H3805-048-0")["cells"]["O_medical_deductible"]
        self.assertNotIn("cms", cell)

    def test_drops_a_cite_whose_value_an_edit_changed(self):
        self.assertNotIn("stale quote", [c["quote"] for c in self.cites("main", "G_specialist")])


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

    def test_an_uncited_edit_lists_no_cms_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = data_copy(tmp, [])
            with open(data / "edits.csv", "a", newline="") as f:
                csv.DictWriter(f, fieldnames=build.layers.EDIT_COLUMNS).writerow(
                    dict(cite("main", "O_medical_deductible", "$100", "", "", ""), line="", saw="", source="volunteer",
                         author="v1", note=""))
            site = build.site_data(data)
        cell = next(r for r in site["main"]["rows"] if r["plan_id"] == "H3805-048-0")["cells"]["O_medical_deductible"]
        self.assertEqual((cell["value"], "cms" in cell), ("$100", False))

    def test_an_edit_of_an_unknown_document_sets_its_cell_and_warns(self):
        cell, _, out = self.dental("https://x/unknown.pdf")
        self.assertEqual((cell["value"], cell["cites"]), ("fixed", []))
        self.assertIn("::warning::", out)
        self.assertIn("edits.csv dvha H3805-048-0 F_dental https://x/unknown.pdf", out)


class SiteCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_docs_command_lists_each_linked_pdfs_hash(self):
        site = bare_site(docs={"a" * 16: {"sha256": "a" * 64}, "b" * 16: {"sha256": "b" * 64}})
        out = io.StringIO()
        with mock.patch.object(build, "site_data", return_value=site), contextlib.redirect_stdout(out):
            build.main("docs")
        self.assertEqual(out.getvalue(), f"{'a' * 64}\n{'b' * 64}\n")

    def test_site_command_warns_of_dropped_cites(self):
        dropped = dict(cite("main", "E_moop", "$6,800", "u", 45, "stale quote"), layer="edits.csv", line="")
        out = io.StringIO()
        with (mock.patch.object(build, "site_data", return_value=bare_site()),
              mock.patch.object(build.layers, "live", return_value=({}, [], [dropped])), contextlib.redirect_stdout(out)):
            build.main("site", self.dir / "site")
        self.assertIn("::warning::", out.getvalue())
        self.assertIn("edits.csv main H3805-048-0 E_moop", out.getvalue())

    def test_site_command_warns_of_an_edit_whose_cell_changed_beneath_it(self):
        edit = dict(cite("main", "E_moop", "$6,800", "u", 45, "q"), layer="edits.csv", line="", saw="$6,700", beneath="$6,900")
        out = io.StringIO()
        with (mock.patch.object(build, "site_data", return_value=bare_site()),
              mock.patch.object(build.layers, "live", return_value=({}, [], [edit])), contextlib.redirect_stdout(out)):
            build.main("site", self.dir / "site")
        self.assertIn("::warning::An edit's author saw $6,700, but the cell beneath it is now $6,900: "
                      "edits.csv main H3805-048-0 E_moop", out.getvalue())

    def test_site_command_warns_of_a_strike_that_matches_no_machine_quote(self):
        strike = dict(sheet="main", plan_id="H3805-048-0", column="E_moop", quote="gone", note="")
        out = io.StringIO()
        with (mock.patch.object(build, "site_data", return_value=bare_site()),
              mock.patch.object(build.layers, "live", return_value=({}, [], [])),
              mock.patch.object(build.layers, "stale_strikes", return_value=[strike]), contextlib.redirect_stdout(out)):
            build.main("site", self.dir / "site")
        self.assertIn("::warning::A strike matches no machine quote: main H3805-048-0 E_moop gone", out.getvalue())

    def test_site_command_records_build_time_and_titles_the_page(self):
        with mock.patch.object(build, "site_data", return_value=bare_site(year=2099, area="A & B")):
            build.main("site", self.dir / "site")
        built = datetime.datetime.fromisoformat(json.loads((self.dir / "site" / "data.json").read_text())["built"])
        self.assertLess(datetime.datetime.now(datetime.timezone.utc) - built, datetime.timedelta(minutes=1))
        self.assertIn("<title>pdxplans.org – 2099 Medicare Advantage plans</title>", (self.dir / "site" / "index.html").read_text())
