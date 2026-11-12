import os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import changes, layers, years


def sheet(**cells):
    return {"main": [dict(section="MA", plan_id="H1036-001-0", plan_name="A plan") | cells]}


class ChangedTest(unittest.TestCase):
    def test_lists_each_cell_whose_value_differs(self):
        before, after = sheet(P_vision="●", Q_hearing="$0"), sheet(P_vision="●", Q_hearing="")
        self.assertEqual(changes.changed(before, after), [("main", "H1036-001-0", "Q_hearing", "$0", "")])

    def test_a_table_escapes_the_lines_of_a_cell(self):
        self.assertEqual(changes.table([("main", "H1036-001-0", "H_inpatient", "$550 | 1-5", "")]),
                         "| Sheet | Plan | Column | Before | After |\n|---|---|---|---|---|\n"
                         "| main | H1036-001-0 | H_inpatient | `$550 \\| 1-5` | (blank) |\n")
        self.assertEqual(changes.table([]), "No sheet cell changes.\n")


class AtTest(unittest.TestCase):
    def test_reads_the_live_sheets_at_a_ref(self):
        data = years.data_dir(years.LIVE)
        with tempfile.TemporaryDirectory() as out:
            sheets = changes.at("HEAD", data, out)
        self.assertEqual(set(sheets), set(layers.SHEETS))
        self.assertTrue(sheets["main"] and sheets["dvha"])


if __name__ == "__main__":
    unittest.main()
