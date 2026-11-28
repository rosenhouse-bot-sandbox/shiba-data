import csv, os, pathlib, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sheets


def write(path, rows, columns=sheets.COLUMNS):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


def cite(column, value, line="", sheet="main", quote="q", url="u"):
    return dict(sheet=sheet, plan_id="H1-001-0", column=column, line=line, value=value, url=url, pdf_page="1", quote=quote)


class CitationsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = pathlib.Path(tmp.name)
        plan = dict(section="", plan_id="H1-001-0", plan_name="A")
        write(self.data / "generated/main_chart.csv",
              [dict(plan, G_specialist="$0-$40", L_xray_imaging="$0 | $0-$300", U_naturopath="●")],
              list(plan) + ["G_specialist", "L_xray_imaging", "U_naturopath"])
        write(self.data / "generated/dvha.csv", [dict(plan, F_dental="Dental")], list(plan) + ["F_dental"])

    def citations(self, *rows):
        write(self.data / sheets.PRESENTED, rows)
        return sheets.citations(self.data, {"u": "EOC", "sb": "SB"})

    def hidden(self, *rows):
        return [(c["quote"], c["hidden"]) for c in self.citations(*rows)[1]]

    def test_reads_the_sheets_and_numbers_each_citation(self):
        got, cited = self.citations(cite("L_xray_imaging", "$0", line="1"), cite("F_dental", "Dental", sheet="dvha"))
        self.assertEqual(got["main"][0]["L_xray_imaging"], "$0 | $0-$300")
        self.assertEqual(got["dvha"][0]["F_dental"], "Dental")
        self.assertEqual([(c["column"], c["position"], c["hidden"]) for c in cited],
                         [("L_xray_imaging", 0, ""), ("F_dental", 1, "")])

    def test_hides_sb_citations_when_another_document_cites_the_cell(self):
        sb = cite("U_naturopath", "●", quote="sb", url="sb")
        self.assertEqual(self.hidden(sb, cite("U_naturopath", "●", quote="eoc")),
                         [("sb", sheets.NOT_SB_CITES_CELL), ("eoc", "")])
        self.assertEqual(self.hidden(sb), [("sb", "")])

    def test_rejects_a_citation_that_names_no_cell(self):
        for column in ("G_specialists", "plan_name"):
            with self.subTest(column=column), self.assertRaisesRegex(ValueError, f"names no cell: main H1-001-0 {column}"):
                self.citations(cite(column, "A"))

    def test_rejects_a_citation_whose_value_is_not_its_cells(self):
        for line, value in (("", "$45"), ("2", "$0"), ("0", "$0"), ("3", "$0")):
            with self.subTest(line=line), self.assertRaisesRegex(ValueError, "value is not its cell's: main H1-001-0 L_xray"):
                self.citations(cite("L_xray_imaging", value, line=line))

    def test_rejects_a_citation_of_an_unknown_document(self):
        with self.assertRaisesRegex(ValueError, "names a document not in documents_checked.csv"):
            self.citations(cite("U_naturopath", "●", url="elsewhere"))

    def test_rejects_a_file_without_its_columns(self):
        write(self.data / sheets.PRESENTED, [dict(cite("G_specialist", "$0-$40"), extra="x")], sheets.COLUMNS + ["extra"])
        with self.assertRaisesRegex(ValueError, "presented.csv has columns"):
            sheets.citations(self.data, {"u": "EOC"})


def note(column, comment, kind="caveat"):
    return dict(sheet="main", plan_id="H1-001-0", column=column, kind=kind, comment=comment, url="u", pdf_page="1", quote="q")


class NotesTest(unittest.TestCase):
    def test_a_cell_with_a_comment_and_a_caveat_gets_both_texts_and_the_comments_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = pathlib.Path(tmp)
            write(data / sheets.COMMENTS, [note("G_specialist", "Odd.", "question"), note("L_xray_imaging", "Hand.")],
                  sheets.NOTE_COLUMNS)
            write(data / sheets.CAVEATS, [dict(note("L_xray_imaging", "Rule."), url="v"), note("U_naturopath", "Only.")],
                  sheets.NOTE_COLUMNS)
            self.assertEqual(sheets.notes(data), [note("G_specialist", "Odd.", "question"), note("L_xray_imaging", "Hand. Rule."),
                                                  note("U_naturopath", "Only.")])

    def test_a_comment_is_stale_once_its_cell_shows_another_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = pathlib.Path(tmp)
            os.makedirs(data / "generated")
            for sheet, name in sheets.SHEETS.items():
                write(data / "generated" / name, [dict(plan_id="H1-001-0", G_specialist="$40", L_xray_imaging="$5")],
                      ["plan_id", "G_specialist", "L_xray_imaging"])
            write(data / sheets.COMMENTS, [dict(note("G_specialist", "Odd.", "question"), cell="$40"),
                                           dict(note("L_xray_imaging", "Old."), cell="$0")], sheets.COMMENT_COLUMNS)
            write(data / sheets.CAVEATS, [], sheets.NOTE_COLUMNS)
            self.assertEqual([c["column"] for c in sheets.stale_comments(data)], ["L_xray_imaging"])
            self.assertEqual(sheets.notes(data)[0], note("G_specialist", "Odd.", "question"))


if __name__ == "__main__":
    unittest.main()
