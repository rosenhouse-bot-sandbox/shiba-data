import contextlib, csv, io, json, os, pathlib, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sheets
import ask, blobs, run, years

READER = "reader-model"

URL = "https://example.org/sb.pdf"


class LostQuotesTest(unittest.TestCase):
    def test_lists_citations_the_site_cannot_highlight_even_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, texts = pathlib.Path(tmp, "2027"), pathlib.Path(tmp, "texts")
            (data / "generated").mkdir(parents=True)
            (texts / "items").mkdir(parents=True)
            with open(data / "generated" / "documents_checked.csv", "w") as f:
                f.write(f"url,sha256\n{URL},{'a' * 64}\n")
            page = {"strs": ["Specialist $40 copay", "Specialist $40 copay"], "lefts": [0, 0]}
            (texts / "items" / f"{'a' * 16}.json").write_text(json.dumps({"2": page}))
            with open(data / sheets.PRESENTED, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=sheets.COLUMNS)
                w.writeheader()
                for quote in ("Specialist $40", "Specialist $50", ""):
                    w.writerow(dict(sheet="main", plan_id="P", column="G_specialist", line="", value="$40", url=URL,
                                    pdf_page="2", quote=quote))
            lost = run.lost_quotes(data, texts)
        self.assertEqual([c["quote"] for c in lost], ["Specialist $50"])


class AnswersTest(unittest.TestCase):
    def test_stops_and_lists_tasks_without_an_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            pathlib.Path(tmp, "P-1.md").write_text("task")
            out = io.StringIO()
            with self.assertRaises(SystemExit) as stop, contextlib.redirect_stdout(out):
                run.Answers(pathlib.Path(tmp), None)(tmp, READER)
        self.assertIn(f"{tmp}/P-1.md", out.getvalue())
        self.assertIn("1 of 1 tasks", str(stop.exception))

    def test_finds_answers_saved_with_an_effort(self):
        with tempfile.TemporaryDirectory() as tmp:
            pathlib.Path(tmp, "P-1.md").write_text("task")
            os.makedirs(f"{tmp}/answers")
            ask.write(f"{tmp}/answers/{ask.key(READER, 'task', 'high')}.json", {"reply": "[]"})
            run.Answers(pathlib.Path(tmp), None)(tmp, READER, "high")
            self.assertEqual(pathlib.Path(tmp, "P-1.json").read_text(), "[]\n")

    def test_saves_new_answers_where_it_is_told(self):
        with tempfile.TemporaryDirectory() as tmp:
            pathlib.Path(tmp, "P-1.md").write_text("task")
            run.Answers(pathlib.Path(tmp), lambda model, effort, texts: {k: ("[]", {}) for k in texts}, None,
                        f"{tmp}/elsewhere")(tmp, READER)
            self.assertEqual(os.listdir(f"{tmp}/elsewhere"), [f"{ask.key(READER, 'task')}.json"])
            self.assertFalse(os.path.exists(f"{tmp}/answers"))

    def test_lists_each_task_with_its_answer_key_and_keeps_its_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(f"{tmp}/step/read")
            pathlib.Path(tmp, "step/read/P-1.md").write_text("task ✓")
            os.makedirs(f"{tmp}/answers")
            ask.write(f"{tmp}/answers/{ask.key(READER, 'task ✓', 'high')}.json", {"reply": "[]"})
            run.Answers(pathlib.Path(tmp), None, tmp)(f"{tmp}/step/read", READER, "high")
            with open(f"{tmp}/{blobs.LEDGER}") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual([{k: r[k] for k in ("dir", "task", "model", "effort")} for r in rows],
                             [dict(dir="step/read", task="P-1.md", model=READER, effort="high")])
            prompt = pathlib.Path(tmp, blobs.PROMPTS, rows[0]["prompt"]).read_text()
            self.assertEqual(ask.key(READER, prompt, "high"), rows[0]["key"])
            self.assertTrue(os.path.exists(f"{tmp}/answers/{rows[0]['key']}.json"))


class StepsTest(unittest.TestCase):
    def test_presents_the_facts_its_reviewer_checked(self):
        order = []
        with mock.patch.object(run.document_facts, "step",
                               lambda data, texts, work, answer, version, present_version: order.append((work, version, present_version))), \
             mock.patch.object(run.present, "write", lambda data, version: order.append(("present", version))):
            run.model_steps("data", "texts", "work", None, {"document_facts": 3, "present": 4})
        self.assertEqual(order, [("work/facts", 3, 4), ("present", 4)])

    def test_knows_every_pinned_step(self):
        self.assertEqual(set(run.STEPS), set(json.loads((years.data_dir(years.LIVE) / "steps.json").read_text())))


class AskerTest(unittest.TestCase):
    def test_a_document_facts_candidate_asks_only_about_its_targets(self):
        with mock.patch.object(run.ask, "api", lambda: "api"):
            self.assertIsNone(run.asker("replay", "data", "work", {"document_facts": 23}, "document_facts@23"))
            self.assertEqual(run.asker("api", "data", "work", {"document_facts": 21}, "present@16"), "api")
            guard = run.asker("api", "data", "work", {"document_facts": 23}, "present@16,document_facts@23")
        self.assertEqual((guard.asker, guard.version), ("api", run.STEPS["document_facts"][23]))


class MainTest(unittest.TestCase):
    def run_main(self, mode, candidate=""):
        order = []
        with tempfile.TemporaryDirectory() as work, \
             mock.patch.multiple(run, tests=lambda kind, candidate: order.append((kind, candidate)),
                                 get=lambda *a: order.append("get"), py=lambda *a: None, check_quotes=lambda *a: None,
                                 model_steps=lambda *a: order.append("model_steps"), asker=lambda *a: None), \
             mock.patch.object(run.subprocess, "run"), mock.patch.object(run.blobs, "record_cms"), \
             mock.patch.object(run.blobs, "record_texts"), mock.patch.object(run, "pdfs"):
            run.main(str(years.LIVE), work, mode, candidate)
        return order

    def test_runs_the_code_tests_before_any_download_or_model_call(self):
        self.assertEqual(self.run_main("api", "present@2")[0], ("code", "present@2"))
        self.assertEqual(self.run_main("api", "present@2")[1], "get")

    def test_checks_the_built_data_after_the_model_steps(self):
        self.assertEqual(self.run_main("replay")[-2:], ["model_steps", ("checks", "")])
        self.assertEqual(self.run_main("api")[-2:], ["model_steps", ("checks", "")])

    def test_leaves_a_candidates_data_for_its_pin_to_check(self):
        self.assertEqual(self.run_main("api", "present@2")[-1], "model_steps")

if __name__ == "__main__":
    unittest.main()
