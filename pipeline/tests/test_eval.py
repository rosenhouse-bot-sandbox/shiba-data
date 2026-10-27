import csv
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import eval  # noqa: E402
import years  # noqa: E402

SPECIALIST, DENTAL = ("main", "H1-001-0", "G_specialist"), ("dvha", "H1-001-0", "F_dental")


def row(cell, value):
    sheet, plan_id, column = cell
    return dict(sheet=sheet, plan_id=plan_id, column=column, value=value)


def write(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


class ScoreTest(unittest.TestCase):
    live = {SPECIALIST: "$40", DENTAL: "PREV $0"}
    generated = {SPECIALIST: "$0-$40", DENTAL: "PREV $0"}

    def score(self, *machine, cited=()):
        return eval.score(self.live, self.generated, set(cited), list(machine))

    def test_a_right_correction_counts_for_recall_and_precision(self):
        got = self.score(row(SPECIALIST, "$40"))
        self.assertEqual(got["corrections"], (1, 1, []))
        self.assertEqual(got["correction precision"], (1, 1, []))

    def test_a_wrong_correction_costs_precision(self):
        got = self.score(row(SPECIALIST, "$45"), row(DENTAL, "PREV $10"))
        self.assertEqual(got["corrections"], (0, 1, [SPECIALIST]))
        self.assertEqual(got["correction precision"], (0, 2, sorted([SPECIALIST, DENTAL])))

    def test_ignores_a_cell_whose_rows_disagree(self):
        got = self.score(row(SPECIALIST, "$40"), row(SPECIALIST, "$45"))
        self.assertEqual(got["corrections"], (0, 1, [SPECIALIST]))
        self.assertEqual(got["correction precision"], (0, 0, []))

    def test_a_citation_needs_a_machine_row(self):
        self.assertEqual(self.score(cited=[DENTAL])["citations"], (0, 1, [DENTAL]))

    def test_a_citation_needs_the_live_value(self):
        got = self.score(row(SPECIALIST, "$45"), row(DENTAL, "PREV $0"), cited=[SPECIALIST, DENTAL])
        self.assertEqual(got["citations"], (1, 2, [SPECIALIST]))
        self.assertEqual(got["correction precision"], (0, 1, [SPECIALIST]))


class LayersTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = pathlib.Path(tmp.name)
        plan = dict(section="", plan_id="H1-001-0", plan_name="A")
        write(self.data / "main_chart.csv", [dict(plan, G_specialist="$40", U_naturopath="◐")])
        write(self.data / "dvha.csv", [dict(plan, F_dental="PREV $0")])
        write(self.data / "sb_facts.csv", [
            dict(plan_ids="H1-002-0;H1-001-0", column="G_specialist", line="", value="$40", kind="SB", quote=""),
            dict(plan_ids="H1-001-0", column="dvha.F_dental", line="", value="PREV $0", kind="EOC", quote="")])
        write(self.data / "pbp_vs_documents.csv", [
            dict(plan_id="H1-001-0", column="G_specialist", pbp="$0-$40", documents="$40", citations=""),
            dict(plan_id="H1-001-0", column="U_naturopath", pbp="", documents="◐", citations="")])
        write(self.data / "pbp_vs_documents_dvha.csv", [
            dict(plan_id="H1-001-0", column="F_dental", pbp="Dental", documents="PREV $0", citations="")])
        write(self.data / "citations.csv", [dict(plan_id="H1-001-0", column="dvha.F_dental", value="PREV $0")])
        write(self.data / "eoc_citations.csv", [row(SPECIALIST, "$40")])

    def test_generated_cells_undo_only_hand_written_rows(self):
        live = eval.live_cells(self.data)
        self.assertEqual(live[("main", "H1-001-0", "U_naturopath")], "◐")
        generated = eval.generated_cells(self.data, live)
        self.assertEqual({cell: v for cell, v in generated.items() if v != live[cell]},
                         {SPECIALIST: "$0-$40", DENTAL: "Dental"})

    def test_cited_cells_come_from_both_citation_files(self):
        self.assertEqual(eval.cited_cells(self.data), {SPECIALIST, DENTAL})


class ReportTest(unittest.TestCase):
    def test_counts_missed_corrections_by_column(self):
        result = {"corrections": (0, 3, [DENTAL, SPECIALIST, ("main", "H1-002-0", "G_specialist")]),
                  "citations": (1, 1, [])}
        self.assertEqual(eval.report(result), "corrections: 0 of 3\ncitations: 1 of 1\ncorrections missed, by column:\n"
                                              "  main.G_specialist: 2\n  dvha.F_dental: 1")


class Data2027Test(unittest.TestCase):
    def test_the_live_data_as_machine_rows_scores_full_marks(self):
        data = years.data_dir(2027)
        live = eval.live_cells(data)
        result = eval.score(live, eval.generated_cells(data, live), eval.cited_cells(data),
                            [row(cell, value) for cell, value in live.items()])
        self.assertGreater(result["corrections"][1], 0)
        for name, (hit, total, missed) in result.items():
            self.assertEqual((hit, missed), (total, []), name)


if __name__ == "__main__":
    unittest.main()
