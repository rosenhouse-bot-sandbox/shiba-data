import copy
import pathlib
import sys
import tempfile
import unittest

import openpyxl

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import build  # noqa: E402
import spreadsheet  # noqa: E402
from test_build import data_copy  # noqa: E402

SITE = "https://shibasheets.org/"


def book(site):
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "plans.xlsx"
        spreadsheet.write(site, path)
        return openpyxl.load_workbook(path)


class WorkbookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            cls.site = build.site_data(data_copy(tmp, []))
        cls.book = book(cls.site)

    def row(self, ws, plan_id):
        return next(r for r in ws.iter_rows() if r[1].value == plan_id)

    def cell(self, ws, plan_id, label):
        header = [c.value for c in ws[1]]
        return self.row(ws, plan_id)[header.index(label)]

    def test_has_one_tab_per_sheet(self):
        self.assertEqual(self.book.sheetnames, ["Main chart", "Dental, vision, hearing, extras"])

    def test_header_names_plan_id_and_benefits(self):
        header = [c.value for c in self.book["Main chart"][1]]
        self.assertEqual(header[:2], ["Plan", "Plan ID"])
        self.assertEqual(header[2:], list(build.fields.labels("main").values()))

    def test_header_and_plan_columns_stay_in_view(self):
        self.assertEqual(self.book["Main chart"].freeze_panes, "C2")

    def test_has_a_row_per_plan_under_its_section(self):
        ws = self.book["Dental, vision, hearing, extras"]
        self.assertEqual(sum(1 for r in ws.iter_rows(min_row=2) if r[1].value), 39)
        self.assertEqual(ws["A2"].value, build.SECTIONS["MA-PD"])

    def test_plan_name_links_to_its_plan_page(self):
        name = self.row(self.book["Main chart"], "H3805-048-0")[0]
        self.assertEqual(name.hyperlink.target, f"{SITE}#/plan/H3805-048-0")

    def test_multiline_value_wraps_onto_lines(self):
        cell = self.cell(self.book["Main chart"], "H3805-048-0", build.fields.labels("main")["L_xray_imaging"])
        self.assertIn("\n", cell.value)
        self.assertTrue(cell.alignment.wrap_text)

    def test_cited_cell_links_to_its_cell_on_the_site(self):
        cell = self.cell(self.book["Main chart"], "H2001-045-0", build.fields.labels("main")["H_inpatient"])
        self.assertEqual(cell.value, "$0 or $1,980 per stay")
        self.assertEqual(cell.hyperlink.target, f"{SITE}#/main/H2001-045-0/H_inpatient")

    def test_uncited_cell_has_no_link(self):
        cell = self.cell(self.book["Main chart"], "H3805-048-0", build.fields.labels("main")["E_moop"])
        self.assertEqual(cell.value, "$6,700")
        self.assertIsNone(cell.hyperlink)

    def test_empty_cited_cell_has_no_link(self):
        cell = self.cell(self.book["Main chart"], "H3805-048-0", build.fields.labels("main")["R_dental"])
        self.assertIsNone(cell.value)
        self.assertIsNone(cell.hyperlink)

    def test_columns_fit_their_longest_line_up_to_a_cap(self):
        ws = self.book["Dental, vision, hearing, extras"]
        widths = [ws.column_dimensions[c[0].column_letter].width for c in ws.iter_cols(min_col=3, max_row=1)]
        self.assertEqual(max(widths), spreadsheet.MAX_WIDTH)
        self.assertGreater(min(widths), len("Premium"))

    def test_commented_cell_carries_comment_and_color(self):
        cell = self.cell(self.book["Main chart"], "H6815-038-0", build.fields.labels("main")["K_tests_labs"])
        self.assertIn("EKG", cell.comment.text)
        self.assertEqual(cell.fill.fgColor.rgb, "00" + spreadsheet.FILLS["note"])

    def test_commented_cell_links_to_its_cell_on_the_site(self):
        cell = self.cell(self.book["Main chart"], "H6815-038-0", build.fields.labels("main")["K_tests_labs"])
        self.assertEqual(cell.hyperlink.target, f"{SITE}#/main/H6815-038-0/K_tests_labs")

    def test_contradicting_comment_has_its_own_color(self):
        site = copy.deepcopy(self.site)
        row = next(r for r in site["main"]["rows"] if r["plan_id"] == "H6815-038-0")
        row["cells"]["K_tests_labs"]["comment"]["kind"] = "contradicts"
        cell = self.cell(book(site)["Main chart"], "H6815-038-0", build.fields.labels("main")["K_tests_labs"])
        self.assertEqual(cell.fill.fgColor.rgb, "00" + spreadsheet.FILLS["contradicts"])


if __name__ == "__main__":
    unittest.main()
