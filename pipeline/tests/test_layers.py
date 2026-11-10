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


def edit(column, value, saw, line="", sheet="main", quote="q"):
    return dict(cite(column, value, line, sheet, quote), saw=saw, source="volunteer", author="v1", note="")


def write_edits(data, *rows):
    write(data / "edits.csv", rows, layers.EDIT_COLUMNS)


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
        write(self.data / layers.PRESENTED, [cite("U_naturopath", "●")])
        write_edits(self.data, edit("L_xray_imaging", "$150-$300", "$0-$300", line="2"),
                    edit("F_dental", "PREV $0", "Dental", sheet="dvha"))

    def live(self, *names):
        return layers.live(self.data, *([names] if names else []))

    def test_applies_code_rows_then_edits(self):
        sheets, kept, dropped = self.live()
        self.assertEqual(sheets["main"][0], dict(section="", plan_id="H1-001-0", plan_name="A", G_specialist="$0-$40",
                                                 L_xray_imaging="$0 | $150-$300", U_naturopath="●"))
        self.assertEqual(sheets["dvha"][0]["F_dental"], "PREV $0")
        self.assertEqual(len(kept), 3)
        self.assertEqual(dropped, [])

    def test_applies_only_the_layers_asked_for(self):
        sheets, kept, _ = self.live(layers.LAYERS[0])
        self.assertEqual(sheets["main"][0]["L_xray_imaging"], "$0 | $0-$300")
        self.assertEqual([(c["column"], c["layer"]) for c in kept], [("U_naturopath", layers.LAYERS[0])])

    def test_skips_the_rows_asked_for(self):
        def xray_edit(r):
            return r["layer"] == layers.EDITS and r["column"] == "L_xray_imaging"

        sheets, kept, dropped = layers.live(self.data, layers.LAYERS, ignore=xray_edit)
        self.assertEqual(sheets["main"][0]["L_xray_imaging"], "$0 | $0-$300")
        self.assertEqual(sheets["dvha"][0]["F_dental"], "PREV $0")
        self.assertFalse(any(map(xray_edit, kept + dropped)))

    def test_lists_citations_from_the_latest_layer_first(self):
        write(self.data / layers.PRESENTED, [cite("L_xray_imaging", "$0 | $150-$300", quote="code")])
        write_edits(self.data, edit("L_xray_imaging", "$0 | $150-$300", quote="edit", saw=""))
        _, kept, _ = self.live()
        self.assertEqual([c["quote"] for c in kept], ["edit", "code"])

    def test_drops_a_citation_whose_value_a_later_layer_changed(self):
        write(self.data / layers.PRESENTED, [cite("L_xray_imaging", "$0 | $150-$300", quote="code")])
        write_edits(self.data, edit("L_xray_imaging", "$45", saw=""))
        sheets, kept, dropped = self.live()
        self.assertEqual(sheets["main"][0]["L_xray_imaging"], "$45")
        self.assertEqual([c["quote"] for c in dropped], ["code"])

    def test_keeps_a_line_citation_whose_line_a_later_layer_kept(self):
        write(self.data / layers.PRESENTED, [cite("L_xray_imaging", "$0", line="1", quote="code")])
        write_edits(self.data, edit("L_xray_imaging", "$0 | $150-$300", saw=""))
        _, kept, dropped = self.live()
        self.assertIn("code", [c["quote"] for c in kept])
        self.assertEqual(dropped, [])

    def test_drops_a_line_citation_whose_line_a_later_layer_removed(self):
        write(self.data / layers.PRESENTED, [cite("L_xray_imaging", "$0-$300", line="2", quote="code")])
        write_edits(self.data, edit("L_xray_imaging", "$45", saw=""))
        _, _, dropped = self.live()
        self.assertEqual([c["quote"] for c in dropped], ["code"])

    def test_rejects_a_row_that_names_no_cell(self):
        for column in ("G_specialists", "plan_name"):
            with self.subTest(column=column):
                write_edits(self.data, edit(column, "$45", saw=""))
                with self.assertRaisesRegex(ValueError, f"names no cell: edits.csv main H1-001-0 {column}"):
                    self.live()

    def test_rejects_a_row_that_names_no_line(self):
        for line in ("0", "3"):
            with self.subTest(line=line):
                write_edits(self.data, edit("L_xray_imaging", "$45", line=line, saw=""))
                with self.assertRaisesRegex(ValueError,
                                            f"names no line: edits.csv main H1-001-0 L_xray_imaging line {line}"):
                    self.live()

    def test_rejects_code_rows_that_set_a_cell_two_ways(self):
        write(self.data / layers.PRESENTED, [cite("G_specialist", "$40"), cite("G_specialist", "$45")])
        with self.assertRaisesRegex(ValueError, "set different values: generated/presented.csv main H1-001-0 G_specialist"):
            self.live()

    def test_a_later_edit_wins(self):
        write_edits(self.data, edit("G_specialist", "$40", "$0-$40", quote="first"),
                    edit("G_specialist", "$45", "$40", quote="second"))
        sheets, kept, dropped = self.live()
        self.assertEqual(sheets["main"][0]["G_specialist"], "$45")
        self.assertEqual([(c["quote"], c in kept) for c in kept + dropped if c["column"] == "G_specialist"],
                         [("second", True), ("first", False)])

    def test_marks_an_edit_whose_cell_changed_beneath_it(self):
        write_edits(self.data, edit("G_specialist", "$40", "$0-$40", quote="fresh"),
                    edit("G_specialist", "$40", "$0-$40", quote="another quote"),
                    edit("L_xray_imaging", "$300", "$0-$250", line="2", quote="stale"),
                    edit("F_dental", "PREV $0", "PREV $0", sheet="dvha", quote="stale confirmation"),
                    edit("U_naturopath", "", "", quote="unknown view"))
        _, kept, dropped = self.live()
        self.assertEqual({c["quote"]: c.get("beneath") for c in kept + dropped if c["layer"] == "edits.csv"},
                         {"fresh": None, "another quote": None, "stale": "$0-$300", "stale confirmation": "Dental",
                          "unknown view": None})

    def test_rejects_a_layer_without_its_columns(self):
        for name in layers.LAYERS:
            with self.subTest(name=name):
                write(self.data / name, [dict(cite("G_specialist", "$0-$40"), extra="x")],
                      layers.COLUMNS + ["extra"])
                with self.assertRaisesRegex(ValueError, f"{name} has columns"):
                    layers.layer(self.data, name)

    def test_reads_a_missing_layer_as_empty(self):
        (self.data / "edits.csv").unlink()
        self.assertEqual(self.live()[0]["dvha"][0]["F_dental"], "Dental")


class CitationsTest(unittest.TestCase):
    setUp = LiveTest.setUp

    def citations(self, kinds=None):
        return layers.citations(self.data, kinds or {"u": "EOC", "sb": "SB"})[1]

    def hidden(self, column, **kinds):
        return [(c["quote"], c["layer"], c["hidden"]) for c in self.citations(kinds or None) if c["column"] == column]

    def test_shows_kept_rows_and_says_why_it_hides_the_others(self):
        write(self.data / layers.PRESENTED, [cite("L_xray_imaging", "$0", line="1", quote="code"),
                                                      cite("L_xray_imaging", "$0-$300", line="2", quote="stale")])
        self.assertEqual(self.hidden("L_xray_imaging"), [
            ("q", layers.EDITS, ""), ("code", layers.LAYERS[0], ""), ("stale", layers.LAYERS[0], layers.OTHER_VALUE)])

    def test_hides_sb_rows_when_another_document_cites_the_cell(self):
        sb = dict(cite("U_naturopath", "●", quote="sb"), url="sb")
        write(self.data / layers.PRESENTED, [sb, cite("U_naturopath", "●", quote="eoc")])
        self.assertEqual(self.hidden("U_naturopath"), [("sb", layers.LAYERS[0], layers.NOT_SB_CITES_CELL),
                                                       ("eoc", layers.LAYERS[0], "")])
        write(self.data / layers.PRESENTED, [sb])
        self.assertEqual(self.hidden("U_naturopath"), [("sb", layers.LAYERS[0], "")])

    def test_hides_edits_without_a_known_document(self):
        write_edits(self.data, dict(edit("G_specialist", "$40", ""), url=""),
                    dict(edit("G_specialist", "$40", "", quote="other"), url="elsewhere"))
        self.assertEqual(self.hidden("G_specialist"), [("q", layers.EDITS, layers.NO_DOCUMENT),
                                                       ("other", layers.EDITS, layers.UNKNOWN_DOCUMENT)])

    def test_rejects_other_rows_that_cite_an_unknown_document(self):
        write(self.data / layers.PRESENTED, [dict(cite("U_naturopath", "●"), url="elsewhere")])
        with self.assertRaisesRegex(ValueError, "names a document not in documents_checked.csv"):
            self.citations()


if __name__ == "__main__":
    unittest.main()
