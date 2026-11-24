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
        with mock.patch.object(changes, "at", lambda ref, year, tmp, work: sheet(Q_hearing=work)), \
             mock.patch.object(changes.sheets, "read", lambda data: sheet(Q_hearing="$0")), \
             contextlib.redirect_stdout(out):
            changes.main(str(years.LIVE), "HEAD", "/work")
        self.assertIn("| main | H1036-001-0 | Q_hearing | `/work` | `$0` |", out.getvalue())

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
    for path, text in ({"web/static/highlight.js": ""} | files).items():
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

    def test_runs_the_tables_step_of_a_ref_that_has_one(self):
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as out:
            commit(repo, {"pipeline/tables.py": FAKE_PRESENT + "assert sys.argv[2] == " + repr(f"{out}/work") + "\n",
                          "data/2027/config.json": "{}"})
            got = changes.at("HEAD", 2027, out, repo)
        self.assertEqual(got["main"][0]["Q_hearing"], "$0")

    def test_runs_the_tables_step_in_a_given_work_dir(self):
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as out:
            commit(repo, {"pipeline/tables.py": FAKE_PRESENT + "assert sys.argv[2] == '/given'\n", "data/2027/config.json": "{}"})
            self.assertEqual(changes.at("HEAD", 2027, out, repo, "/given")["main"][0]["Q_hearing"], "$0")

    def test_a_refs_tables_step_can_check_quotes(self):
        pipeline = pathlib.Path(changes.__file__).parent
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as out:
            commit(repo, {"pipeline/tables.py": FAKE_PRESENT + "import subprocess\nsubprocess.run(['node', "
                          "str(pathlib.Path(__file__).with_name('match.mjs')), '.'], input=b'', check=True)\n",
                          "pipeline/match.mjs": (pipeline / "match.mjs").read_text(),
                          "web/static/highlight.js": (pipeline.parent / "web/static/highlight.js").read_text(),
                          "data/2027/config.json": "{}"})
            self.assertEqual(changes.at("HEAD", 2027, out, repo)["main"][0]["Q_hearing"], "$0")

    def test_shows_what_the_refs_code_printed_when_it_stops(self):
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as out:
            commit(repo, {"pipeline/tables.py": "print('2 of 9 tasks have no answer')\nraise SystemExit(1)\n",
                          "data/2027/config.json": "{}"})
            done = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {os.path.dirname(changes.__file__)!r}); "
                                   f"import changes; changes.at('HEAD', 2027, {out!r}, {repo!r})"], capture_output=True, text=True)
        self.assertEqual((done.returncode, done.stdout), (1, ""))
        self.assertIn("2 of 9 tasks have no answer", done.stderr)

    def test_prints_nothing_the_refs_code_prints(self):
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as out:
            commit(repo, {"pipeline/present.py": FAKE_PRESENT + "print('39 plans')\n", "data/2027/config.json": "{}"})
            done = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {os.path.dirname(changes.__file__)!r}); "
                                   f"import changes; changes.at('HEAD', 2027, {out!r}, {repo!r})"], capture_output=True, text=True)
        self.assertEqual((done.returncode, done.stdout), (0, ""))

    def test_a_year_the_ref_lacks_has_no_sheets(self):
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as out:
            commit(repo, {"pipeline/present.py": FAKE_PRESENT, "data/2027/config.json": "{}"})
            self.assertEqual(changes.at("HEAD", 2028, out, repo), {})

if __name__ == "__main__":
    unittest.main()
