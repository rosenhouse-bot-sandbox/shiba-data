import csv, os, pathlib, sys, tempfile, unittest

here = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [here, os.path.dirname(here)]
import freeze_expected
import layers
from test_layers import cite, edit, write, write_edits

EOC, SB = "https://x/eoc.pdf", "https://x/sb.pdf"


def at(row, url, page):
    return dict(row, url=url, pdf_page=page)


class FreezeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = pathlib.Path(tmp.name)
        plan = dict(section="", plan_id="H1-001-0", plan_name="A")
        write(self.data / "generated/main_chart.csv", [dict(plan, L_xray_imaging="$0 | $0-$300", G_specialist="$40")],
              list(plan) + ["L_xray_imaging", "G_specialist"])
        write(self.data / "generated/dvha.csv", [dict(plan, F_dental="Dental")], list(plan) + ["F_dental"])
        write(self.data / "generated/citations.csv", [])
        write(self.data / "generated/documents.csv",
              [dict(plan_ids="H1-001-0", kind="EOC", url=EOC, found_via=""),
               dict(plan_ids="H1-001-0", kind="SB", url=SB, found_via="")],
              ["plan_ids", "kind", "url", "found_via"])
        write(self.data / "machine/eoc_citations.csv",
              [dict(cite("G_specialist", "$30"), step="xref", prompt="")], layers.MACHINE_COLUMNS)
        write_edits(self.data,
                    at(edit("L_xray_imaging", "$0-$250", "$0-$300", line="2"), EOC, "9"),
                    at(edit("L_xray_imaging", "$0-$200", "$0-$300", line="2"), EOC, "7"),
                    at(edit("L_xray_imaging", "$0-$200", "$0-$300", line="2"), SB, "3"),
                    at(edit("F_dental", "PREV $0", "Dental", sheet="dvha"), EOC, "111"),
                    at(edit("F_dental", "PREV $0", "Dental", sheet="dvha"), EOC, "52"),
                    at(edit("G_specialist", "$40", "$40"), SB, "2"))

    def test_freezes_each_edited_line_with_its_live_value_and_eoc_pages(self):
        self.assertEqual(freeze_expected.freeze(self.data), [
            dict(sheet="dvha", plan_id="H1-001-0", column="F_dental", line="", value="PREV $0", eoc_url=EOC,
                 eoc_pages="52 111"),
            dict(sheet="main", plan_id="H1-001-0", column="G_specialist", line="", value="$40", eoc_url="",
                 eoc_pages=""),
            dict(sheet="main", plan_id="H1-001-0", column="L_xray_imaging", line="2", value="$0-$200", eoc_url=EOC,
                 eoc_pages="7"),
        ])

    def test_writes_a_csv(self):
        path = self.data / "expected.csv"
        freeze_expected.write(path, freeze_expected.freeze(self.data))
        with open(path, newline="") as f:
            self.assertEqual(len(list(csv.DictReader(f))), 3)


if __name__ == "__main__":
    unittest.main()
