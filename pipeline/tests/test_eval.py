import contextlib
import csv
import io
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import eval  # noqa: E402
import years  # noqa: E402

SPECIALIST, DENTAL = ("main", "H1-001-0", "G_specialist"), ("dvha", "H1-001-0", "F_dental")


def row(cell, value, quote="q", line=""):
    sheet, plan_id, column = cell
    return dict(sheet=sheet, plan_id=plan_id, column=column, line=line, value=value, url="u", pdf_page="1", quote=quote)


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def write_layers(data):
    """One plan whose specialist and dental cells edits override, and whose naturopathy dot code sets."""
    plan = dict(section="", plan_id="H1-001-0", plan_name="A")
    write(data / "generated/main_chart.csv", [dict(plan, G_specialist="$0-$40", U_naturopath="")])
    write(data / "generated/dvha.csv", [dict(plan, F_dental="Dental")])
    write(data / "generated/citations.csv", [row(("main", "H1-001-0", "U_naturopath"), "◐")])
    write(data / "machine/eoc_citations.csv", [dict(step="filled", prompt="p", **row(SPECIALIST, "$40"))])
    write(data / "edits.csv", [row(SPECIALIST, "$40"), row(DENTAL, "PREV $0")])


class ScoreTest(unittest.TestCase):
    live = {SPECIALIST: "$40", DENTAL: "PREV $0"}
    generated = {SPECIALIST: "$0-$40", DENTAL: "PREV $0"}

    def score(self, *machine, cited=()):
        return eval.score(self.live, self.generated, set(cited), list(machine))

    def test_a_right_correction_counts_for_recall_and_precision(self):
        got = self.score(row(SPECIALIST, "$40"))
        self.assertEqual(got["correction recall"], (1, 1, []))
        self.assertEqual(got["correction precision"], (1, 1, []))

    def test_a_wrong_correction_costs_precision(self):
        got = self.score(row(SPECIALIST, "$45"), row(DENTAL, "PREV $10"))
        self.assertEqual(got["correction recall"], (0, 1, [SPECIALIST]))
        self.assertEqual(got["correction precision"], (0, 2, sorted([SPECIALIST, DENTAL])))

    def test_ignores_a_cell_whose_rows_disagree(self):
        got = self.score(row(SPECIALIST, "$40"), row(SPECIALIST, "$45"), row(DENTAL, "PREV $10"), row(DENTAL, "PREV $20"),
                         cited=[DENTAL])
        self.assertEqual(got["correction recall"], (0, 1, [SPECIALIST]))
        self.assertEqual(got["correction precision"], (0, 0, []))
        self.assertEqual(got["citations"], (0, 1, [DENTAL]))

    def test_ignores_a_row_without_a_quote(self):
        got = self.score(row(SPECIALIST, "$40", quote=" "), row(DENTAL, "PREV $0", quote=""), cited=[DENTAL])
        self.assertEqual(got["correction recall"], (0, 1, [SPECIALIST]))
        self.assertEqual(got["citations"], (0, 1, [DENTAL]))

    def test_a_citation_needs_a_machine_row(self):
        self.assertEqual(self.score(cited=[DENTAL])["citations"], (0, 1, [DENTAL]))

    def test_a_citation_needs_the_live_value(self):
        got = self.score(row(SPECIALIST, "$45"), row(DENTAL, "PREV $0"), cited=[SPECIALIST, DENTAL])
        self.assertEqual(got["citations"], (1, 2, [SPECIALIST]))
        self.assertEqual(got["correction precision"], (0, 1, [SPECIALIST]))

    def test_fails_on_a_row_that_sets_one_line(self):
        with self.assertRaisesRegex(SystemExit, "one line"):
            self.score(row(SPECIALIST, "$40", line="1"))

    def test_fails_on_a_row_that_names_no_cell(self):
        with self.assertRaisesRegex(SystemExit, "H1-002-0"):
            self.score(row(("main", "H1-002-0", "G_specialist"), "$40"))


class LayersTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = pathlib.Path(tmp.name, "data", "2099")
        write_layers(self.data)

    def test_generated_cells_keep_code_made_cells(self):
        live, generated, _ = eval.measured(self.data)
        self.assertEqual(live[("main", "H1-001-0", "U_naturopath")], "◐")
        self.assertEqual({cell: v for cell, v in generated.items() if v != live[cell]},
                         {SPECIALIST: "$0-$40", DENTAL: "Dental"})

    def test_cited_cells_leave_out_cells_that_only_code_cites(self):
        self.assertEqual(eval.measured(self.data)[2], {SPECIALIST, DENTAL})

    def test_main_scores_a_machine_file(self):
        machine = self.data / "machine.csv"
        write(machine, [row(SPECIALIST, "$40")])
        out = io.StringIO()
        with mock.patch.object(years, "REPO", self.data.parent.parent), contextlib.redirect_stdout(out):
            eval.main("2099", str(machine))
        self.assertTrue(out.getvalue().startswith("correction recall: 1 of 2\ncorrection precision: 1 of 1\ncitations: 1 of 2\n"))


class ReportTest(unittest.TestCase):
    def test_counts_missed_corrections_by_column(self):
        result = {"correction recall": (0, 3, [DENTAL, SPECIALIST, ("main", "H1-002-0", "G_specialist")]),
                  "citations": (1, 1, [])}
        self.assertEqual(eval.report(result), "correction recall: 0 of 3\ncitations: 1 of 1\n"
                                              "corrections missed, by column:\n  main.G_specialist: 2\n  dvha.F_dental: 1")


class Data2027Test(unittest.TestCase):
    def test_the_live_data_as_machine_rows_scores_full_marks(self):
        live, generated, cited = eval.measured(years.data_dir(2027))
        result = eval.score(live, generated, cited, [row(cell, value) for cell, value in live.items()])
        self.assertGreater(result["correction recall"][1], 0)
        for name, (hit, total, missed) in result.items():
            self.assertEqual((hit, missed), (total, []), name)


if __name__ == "__main__":
    unittest.main()
