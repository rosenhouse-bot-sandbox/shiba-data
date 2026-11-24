import contextlib, io, os, pathlib, subprocess, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import changes, years


def sheet(**cells):
    return {"main": [dict(section="MA", plan_id="H1036-001-0", plan_name="A plan") | cells]}


class ChangedTest(unittest.TestCase):
    def test_lists_each_cell_whose_value_differs(self):
        before, after = sheet(P_vision="●", Q_hearing="$0"), sheet(P_vision="●", Q_hearing="", section="PD", plan_name="B")
        self.assertEqual(changes.changed(before, after), [("main", "H1036-001-0", "Q_hearing", "$0", "")])

    def test_lists_the_cells_of_a_plan_that_is_new_or_gone(self):
        self.assertEqual(changes.changed(sheet(Q_hearing="$0"), {"main": []}), [("main", "H1036-001-0", "Q_hearing", "$0", "")])
        self.assertEqual(changes.changed({"main": []}, sheet(Q_hearing="$0")), [("main", "H1036-001-0", "Q_hearing", "", "$0")])

    def test_prints_the_table_of_changes_since_a_ref(self):
        out = io.StringIO()
        with mock.patch.object(changes, "at", lambda ref, year, tmp: sheet(Q_hearing="")), \
             mock.patch.object(changes.sheets, "read", lambda data: sheet(Q_hearing="$0")), \
             contextlib.redirect_stdout(out):
            changes.main(str(years.LIVE), "HEAD")
        self.assertIn("| main | H1036-001-0 | Q_hearing | (blank) | `$0` |", out.getvalue())

    def test_a_table_escapes_pipes(self):
        self.assertEqual(changes.table([("main", "H1036-001-0", "H_inpatient", "$550 | 1-5", "")]),
                         "| Sheet | Plan | Column | Before | After |\n|---|---|---|---|---|\n"
                         "| main | H1036-001-0 | H_inpatient | `$550 \\| 1-5` | (blank) |\n")
        self.assertEqual(changes.table([]), "No sheet cell changes.\n")


FAKE_PRESENT = """import os, pathlib, sys
assert not {"SHIBA_DATA", "SHIBA_CANDIDATE"} & set(os.environ)
gen = pathlib.Path(__file__).parents[1] / "data" / sys.argv[1] / "generated"
gen.mkdir(exist_ok=True)
(gen / "main_chart.csv").write_text("section,plan_id,plan_name,Q_hearing\\nMA,H1036-001-0,A plan,$0\\n")
(gen / "dvha.csv").write_text("section,plan_id,plan_name\\n")
"""


def commit(repo, files):
    for path, text in files.items():
        pathlib.Path(repo, path).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(repo, path).write_text(text)
    for args in (["init", "-q"], ["add", "."],
                 ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "commit", "-qm", "x"]):
        subprocess.run(["git", "-C", repo, *args], check=True)


class AtTest(unittest.TestCase):
    def test_runs_the_present_step_of_the_ref(self):
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as out, \
                mock.patch.dict(os.environ, SHIBA_DATA="/nowhere", SHIBA_CANDIDATE="present@2"):
            commit(repo, {"pipeline/present.py": FAKE_PRESENT, "data/2027/config.json": "{}"})
            got = changes.at("HEAD", 2027, out, repo)
        self.assertEqual(got["main"], [dict(section="MA", plan_id="H1036-001-0", plan_name="A plan", Q_hearing="$0")])

    def test_a_year_the_ref_lacks_has_no_sheets(self):
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as out:
            commit(repo, {"pipeline/present.py": FAKE_PRESENT, "data/2027/config.json": "{}"})
            self.assertEqual(changes.at("HEAD", 2028, out, repo), {})

if __name__ == "__main__":
    unittest.main()
