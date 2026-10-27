import csv, os, pathlib, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import layers


def write(path, rows, columns=layers.COLUMNS):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


def cite(column, value, line="", sheet="main", quote="q"):
    return dict(sheet=sheet, plan_id="H1-001-0", column=column, line=line, value=value, url="u", pdf_page="1", quote=quote)


def machine(*rows):
    return [dict(r, step="filled", prompt="p") for r in rows]


class LiveTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = pathlib.Path(tmp.name)
        plan = dict(section="", plan_id="H1-001-0", plan_name="A")
        write(self.data / "generated/main_chart.csv",
              [dict(plan, G_specialist="$0-$40", L_xray_imaging="$0 | $0-$300", U_naturopath="")],
              list(plan) + ["G_specialist", "L_xray_imaging", "U_naturopath"])
        write(self.data / "generated/dvha.csv", [dict(plan, F_dental="Dental")], list(plan) + ["F_dental"])
        write(self.data / "generated/citations.csv", [cite("U_naturopath", "●")])
        write(self.data / "machine/eoc_citations.csv", machine(cite("L_xray_imaging", "$0 | $150-$300", quote="machine")),
              layers.MACHINE_COLUMNS)
        write(self.data / "edits.csv", [cite("L_xray_imaging", "$150-$300", line="2"), cite("F_dental", "PREV $0", sheet="dvha")])

    def live(self, *names):
        return layers.live(self.data, *([names] if names else []))

    def test_applies_code_rows_then_edits(self):
        sheets, kept, dropped = self.live()
        self.assertEqual(sheets["main"][0], dict(section="", plan_id="H1-001-0", plan_name="A", G_specialist="$0-$40",
                                                 L_xray_imaging="$0 | $150-$300", U_naturopath="●"))
        self.assertEqual(sheets["dvha"][0]["F_dental"], "PREV $0")
        self.assertEqual(len(kept), 4)
        self.assertEqual(dropped, [])

    def test_applies_only_the_layers_asked_for(self):
        sheets, kept, _ = self.live(layers.LAYERS[0])
        self.assertEqual(sheets["main"][0]["L_xray_imaging"], "$0 | $0-$300")
        self.assertEqual([(c["column"], c["layer"]) for c in kept], [("U_naturopath", layers.LAYERS[0])])

    def test_machine_rows_only_cite(self):
        write(self.data / "edits.csv", [])
        sheets, kept, dropped = self.live()
        self.assertEqual(sheets["main"][0]["L_xray_imaging"], "$0 | $0-$300")
        self.assertEqual([c["quote"] for c in dropped], ["machine"])

    def test_lists_citations_from_the_latest_layer_first(self):
        write(self.data / "generated/citations.csv", [cite("L_xray_imaging", "$0 | $150-$300", quote="code")])
        write(self.data / "edits.csv", [cite("L_xray_imaging", "$0 | $150-$300", quote="edit")])
        _, kept, _ = self.live()
        self.assertEqual([c["quote"] for c in kept], ["edit", "machine", "code"])

    def test_drops_a_citation_whose_value_a_later_layer_changed(self):
        write(self.data / "edits.csv", [cite("L_xray_imaging", "$45")])
        sheets, kept, dropped = self.live()
        self.assertEqual(sheets["main"][0]["L_xray_imaging"], "$45")
        self.assertEqual([c["quote"] for c in dropped], ["machine"])

    def test_keeps_a_line_citation_whose_line_a_later_layer_kept(self):
        write(self.data / "generated/citations.csv", [cite("L_xray_imaging", "$0", line="1", quote="code")])
        write(self.data / "edits.csv", [cite("L_xray_imaging", "$0 | $150-$300")])
        _, kept, dropped = self.live()
        self.assertIn("code", [c["quote"] for c in kept])
        self.assertEqual(dropped, [])

    def test_drops_a_line_citation_whose_line_a_later_layer_removed(self):
        write(self.data / "generated/citations.csv", [cite("L_xray_imaging", "$0-$300", line="2", quote="code")])
        write(self.data / "edits.csv", [cite("L_xray_imaging", "$45")])
        _, _, dropped = self.live()
        self.assertEqual([c["quote"] for c in dropped], ["machine", "code"])

    def test_rejects_a_row_that_names_no_cell(self):
        for column in ("G_specialists", "plan_name"):
            with self.subTest(column=column):
                write(self.data / "edits.csv", [cite(column, "$45")])
                with self.assertRaisesRegex(ValueError, f"names no cell: edits.csv main H1-001-0 {column}"):
                    self.live()

    def test_rejects_a_row_that_names_no_line(self):
        for line in ("0", "3"):
            with self.subTest(line=line):
                write(self.data / "edits.csv", [cite("L_xray_imaging", "$45", line=line)])
                with self.assertRaisesRegex(ValueError,
                                            f"names no line: edits.csv main H1-001-0 L_xray_imaging line {line}"):
                    self.live()

    def test_rejects_rows_in_one_layer_that_set_a_cell_two_ways(self):
        write(self.data / "edits.csv", [cite("G_specialist", "$40"), cite("G_specialist", "$45")])
        with self.assertRaisesRegex(ValueError, "set different values: edits.csv main H1-001-0 G_specialist"):
            self.live()

    def test_rejects_a_layer_without_its_columns(self):
        write(self.data / "machine/eoc_citations.csv", [cite("G_specialist", "$40")])
        with self.assertRaisesRegex(ValueError, "machine/eoc_citations.csv has columns"):
            self.live()

    def test_reads_a_missing_layer_as_empty(self):
        (self.data / "edits.csv").unlink()
        self.assertEqual(self.live()[0]["dvha"][0]["F_dental"], "Dental")


if __name__ == "__main__":
    unittest.main()
