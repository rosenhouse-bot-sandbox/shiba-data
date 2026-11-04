import contextlib, csv, io, json, os, pathlib, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import layers
import rebuild
import years
from test_eval import DENTAL, SPECIALIST, row, write, write_layers

SEEDS = {"H1-001-0": {"main.G_specialist": "$50", "dvha.F_dental": ""}}


def machine_row(cell, value, step="filled", quote="q"):
    return dict(step=step, prompt="p", **row(cell, value, quote=quote))


class DataDirTest(unittest.TestCase):
    def test_reads_another_data_root_from_the_environment(self):
        with mock.patch.dict(os.environ, {"SHIBA_DATA": "/elsewhere"}):
            self.assertEqual(years.data_dir(2099), pathlib.Path("/elsewhere/2099"))


class RebuildTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)
        self.data = self.root / "data" / "2099"
        write_layers(self.data)
        (self.data / "answers").mkdir()
        (self.data / "answers" / "a.json").write_text("{}")
        (self.data / "rebuilds" / "old").mkdir(parents=True)

    def test_scratch_copy_drops_model_work_and_adds_the_seeds_as_uncited_edits(self):
        copy = rebuild.scratch_copy(self.data, self.root / "work", SEEDS, self.root / "kept")
        self.assertEqual(sorted(p.name for p in copy.iterdir()), ["answers", "edits.csv", "generated", "machine"])
        self.assertEqual(os.listdir(copy / "machine"), [])
        (copy / "answers" / "b.json").write_text("{}")
        self.assertEqual(os.listdir(self.root / "kept"), ["b.json"])
        sheets, kept, _ = layers.live(copy)
        self.assertEqual(sheets["main"][0]["G_specialist"], "$50")
        self.assertEqual(sheets["dvha"][0]["F_dental"], "")
        self.assertNotIn(SPECIALIST, {(c["sheet"], c["plan_id"], c["column"]) for c in kept if c["quote"]})
        self.assertTrue((self.data / "answers" / "a.json").exists())

    def test_report_scores_the_rows_against_live_data_and_lists_seeds_they_cite(self):
        rows = [machine_row(SPECIALIST, "$40"), machine_row(DENTAL, "", step="blanks")]
        report = rebuild.report(self.data, rows, SEEDS)
        self.assertTrue(report.startswith("correction recall: 1 of 2\n"))
        self.assertIn("seeded errors cited: 1 of 2\n  dvha H1-001-0 F_dental", report)

    def test_save_keeps_the_run_and_its_report(self):
        out = self.data / "rebuilds" / "run1"
        copy = rebuild.scratch_copy(self.data, self.root / "work", SEEDS, out / "answers")
        write(copy / layers.FILLED, [machine_row(SPECIALIST, "$40")])
        (copy / rebuild.DOCUMENT_FACTS).write_text("facts")
        (copy / layers.PRESENTED).write_text("presented")
        with contextlib.redirect_stdout(io.StringIO()):
            rebuild.save(copy, out, self.data, SEEDS)
        self.assertEqual(sorted(p.name for p in out.iterdir()),
                         ["answers", "document_facts.csv", "filled.csv", "presented.csv", "report.txt"])
        self.assertIn("seeded errors cited: 0 of 2", (out / "report.txt").read_text())

    def main(self, name="run1", mode="api", candidate=""):
        calls = []
        with (mock.patch.object(years, "REPO", self.root), mock.patch.object(rebuild, "SEEDS", self.root / "seeds.json"),
              mock.patch.object(rebuild.subprocess, "run", lambda args, **kw: calls.append((args, kw["env"]))),
              contextlib.redirect_stdout(io.StringIO())):
            (self.root / "seeds.json").write_text(json.dumps(SEEDS))
            rebuild.main("2099", self.root / "work", name, mode, candidate)
        return calls

    def test_main_runs_the_steps_on_the_copy_and_keeps_answers_in_the_repository(self):
        with mock.patch.object(years, "LIVE", 2099):
            [(args, env)] = self.main()
        self.assertEqual(args[-4:], ["steps", str(self.root / "work"), "api", ""])
        self.assertEqual(env["SHIBA_DATA"], str(self.root / "work" / "data"))
        self.assertEqual((self.root / "work/data/2099/answers").resolve(), self.data / "rebuilds/run1/answers")
        self.assertTrue((self.data / "rebuilds/run1/report.txt").exists())
        self.assertEqual(len(layers.layer(self.data, layers.FILLED)), 1)

    def test_main_passes_the_candidate_versions_to_the_steps(self):
        with mock.patch.object(years, "LIVE", 2099):
            [(args, _)] = self.main(candidate="filled@6")
        self.assertEqual(args[-1], "filled@6")

    def test_main_keeps_a_trial_run_s_answers_out_of_the_repository(self):
        with mock.patch.object(years, "LIVE", 2099):
            self.main(mode="")
        self.assertEqual((self.root / "work/data/2099/answers").resolve(), self.root / "work/rebuilds/run1/answers")
        self.assertFalse((self.data / "rebuilds/run1").exists())

    def test_main_resumes_a_rebuild_until_it_is_done(self):
        with mock.patch.object(years, "LIVE", 2099):
            self.main()
            with self.assertRaisesRegex(SystemExit, "is done"):
                self.main()
            for name in ("../machine", "a/b"):
                with self.subTest(name=name), self.assertRaises(SystemExit):
                    self.main(name)

    def test_main_rebuilds_only_the_live_year(self):
        with self.assertRaisesRegex(SystemExit, "Only"):
            self.main()

    def test_steps_run_every_model_step_at_the_pinned_or_candidate_versions_on_the_data_root_given(self):
        (self.data / "steps.json").write_text(json.dumps({"filled": 5, "document_facts": 8}))
        order = []
        with (mock.patch.dict(os.environ, {"SHIBA_DATA": str(self.root / "data")}), mock.patch.object(years, "LIVE", 2099),
              mock.patch.object(rebuild.run, "blanks_step", side_effect=lambda *a: order.append("blanks")) as blanks,
              mock.patch.object(rebuild.document_facts, "step", side_effect=lambda *a, **k: order.append("facts")) as found,
              mock.patch.object(rebuild.present, "write", side_effect=lambda *a: order.append("present")),
              mock.patch.object(rebuild.run, "filled_step", side_effect=lambda *a, **k: order.append("filled")) as filled):
            rebuild.steps("w", "", "document_facts@7")
        self.assertEqual(order, ["blanks", "facts", "present", "filled"])
        self.assertEqual(blanks.call_args.args[2].saved, self.data / "answers")
        self.assertEqual((found.call_args.args[0], found.call_args.args[-1]), (self.data, 7))
        self.assertEqual(found.call_args.kwargs, {"reviewed": False})
        self.assertEqual(filled.call_args.kwargs, {"every": True, "version": 5})

    def test_steps_go_on_to_filled_when_facts_cannot_be_presented(self):
        (self.data / "steps.json").write_text(json.dumps({"filled": 5, "document_facts": 8}))
        with (mock.patch.dict(os.environ, {"SHIBA_DATA": str(self.root / "data")}), mock.patch.object(years, "LIVE", 2099),
              mock.patch.object(rebuild.run, "blanks_step"), mock.patch.object(rebuild.document_facts, "step"),
              mock.patch.object(rebuild.present, "write", side_effect=ValueError("two lines")),
              mock.patch.object(rebuild.run, "filled_step") as filled, mock.patch("builtins.print") as printed):
            rebuild.steps("w", "")
        self.assertTrue(filled.called)
        self.assertIn("two lines", printed.call_args[0][0])

    def test_compare_counts_cells_by_whether_both_runs_cite_them_alike(self):
        other = ("main", "H1-001-0", "U_naturopath")
        for name, rows in (("a", [machine_row(SPECIALIST, "$40"), machine_row(DENTAL, "PREV $0")]),
                           ("b", [machine_row(SPECIALIST, "$40"), machine_row(DENTAL, "PREV $10"),
                                  machine_row(other, "◐", step="blanks")])):
            for step in ("filled", "blanks"):
                if any(r["step"] == step for r in rows):
                    write(self.data / "rebuilds" / name / f"{step}.csv", [r for r in rows if r["step"] == step])
        self.assertEqual(rebuild.compare(self.data, "a", "b"),
                         "cells both runs cite alike: 1\ncells the runs cite differently: 1\n"
                         "cells only a cites: 0\ncells only b cites: 1")


if __name__ == "__main__":
    unittest.main()
