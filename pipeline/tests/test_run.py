import contextlib, csv, io, json, os, pathlib, shutil, sys, tempfile, unittest
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
            with self.assertRaisesRegex(SystemExit, "Specialist \\$50"):
                run.check_quotes(data, texts)
            run.check_quotes(data, texts, skip={URL})
            with open(data / "generated" / "documents_checked.csv", "w") as f:
                f.write(f"url,sha256\n{URL},\n")
            with self.assertRaisesRegex(SystemExit, f"did not download:\n{URL}"):
                run.lost_quotes(data, texts)
        self.assertEqual([c["quote"] for c in lost], ["Specialist $50"])

    def test_names_the_documents_a_download_replaced(self):
        with tempfile.TemporaryDirectory() as gen:
            with open(f"{gen}/documents_checked.csv", "w") as f:
                f.write(f"url,sha256\n{URL},{'a' * 64}\nhttps://x/eoc.pdf,{'b' * 64}\nhttps://x/moved.pdf,{'e' * 64}\n"
                        f"https://x/dropped.pdf,{'f' * 64}\nhttps://x/gone.pdf,\n")
            before = run.checked(gen)
            with open(f"{gen}/documents_checked.csv", "w") as f:
                f.write(f"url,sha256\n{URL},{'c' * 64}\nhttps://x/eoc.pdf,{'b' * 64}\nhttps://x/moved.pdf,\n"
                        f"https://x/new.pdf,{'d' * 64}\nhttps://x/gone.pdf,{'a' * 64}\n")
            self.assertEqual(run.replaced(before, run.checked(gen)), {URL})


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


class RunTestsTest(unittest.TestCase):
    def test_runs_one_kind_with_the_candidate(self):
        with mock.patch.object(run.subprocess, "run") as sub:
            run.run_tests("checks", "present@2")
        args, kwargs = sub.call_args
        self.assertEqual(args[0][-2:], [os.path.join(run.HERE, "built.py"), "checks"])
        self.assertEqual(kwargs["env"][run.present.CANDIDATE], "present@2")


class CheckedPdfsTest(unittest.TestCase):
    def setUp(self):
        gen, work = tempfile.TemporaryDirectory(), tempfile.TemporaryDirectory()
        self.addCleanup(gen.cleanup)
        self.addCleanup(work.cleanup)
        self.gen, self.work = gen.name, work.name
        with open(f"{self.gen}/documents_checked.csv", "w") as f:
            f.write(f"plan_ids,kind,url,sha256\nH1036-306-0,SB,{URL},{'ab' * 32}\nH1036-306-0,EOC,https://x/new.pdf,\n")

    def test_refuses_without_the_checked_pdfs(self):
        with self.assertRaisesRegex(SystemExit, "needs the checked PDFs"):
            run.reuse_checked(self.gen, self.work)

    def test_puts_each_checked_pdf_where_fetch_docs_looks_for_its_download(self):
        blobs.pdf_path(self.work, "ab" * 32).parent.mkdir()
        blobs.pdf_path(self.work, "ab" * 32).write_bytes(b"%PDF")
        for _ in range(2):  # as a rerun in the same work dir does
            run.reuse_checked(self.gen, self.work)
        downloaded = pathlib.Path(run.fetch_docs.cached_pdf(f"{self.work}/docs", URL))
        self.assertEqual(downloaded.read_bytes(), b"%PDF")
        self.assertEqual(os.listdir(f"{self.work}/docs/pdf"), [downloaded.name])


class MainTest(unittest.TestCase):
    def run_main(self, mode, candidate="", facts=True, checked=("", ""), **patches):
        """Lists the order of run.main's steps. The year's data has steps.json, and has earlier facts if facts is true.
        checked holds the documents_checked.csv rows before and after fetch_docs.py. patches replace run's functions."""
        order = []

        def fetched(script, *args):
            if script == "fetch_docs.py":
                order.append(script)
                pathlib.Path(args[3]).write_text(f"url,sha256\n{checked[1]}")

        with tempfile.TemporaryDirectory() as work, tempfile.TemporaryDirectory() as root, \
             mock.patch.multiple(run, **{**dict(
                 run_tests=lambda kind, candidate: order.append((kind, candidate)), get=lambda *a: order.append("get"),
                 py=fetched, reuse_checked=lambda *a: order.append("reuse_checked"),
                 check_quotes=lambda *a: order.append("check_quotes"),
                 model_steps=lambda *a: order.append("model_steps"), asker=lambda *a: None), **patches}), \
             mock.patch.object(run.subprocess, "run"), mock.patch.object(run.blobs, "record_cms"), \
             mock.patch.object(run.blobs, "record_texts"), mock.patch.object(run, "pdfs"), \
             mock.patch.object(run.present, "write", lambda data, version: order.append("present")), \
             mock.patch.object(run.store, "pull", lambda data, work: order.append("pull")):
            data = pathlib.Path(root, str(years.LIVE))
            (data / "machine").mkdir(parents=True)
            for name in ("config.json", "steps.json"):
                shutil.copy(years.data_dir() / name, data)
            if facts:
                (data / run.FACTS).write_text("")
            (data / "generated").mkdir()
            (data / "generated" / "documents_checked.csv").write_text(f"url,sha256\n{checked[0]}")
            with mock.patch.object(run.years, "data_dir", lambda year: data):
                run.main(str(years.LIVE), work, mode, candidate)
        return order

    def test_runs_the_code_tests_before_any_download_or_model_call(self):
        self.assertEqual(self.run_main("api", "present@2")[:2], [("code", "present@2"), "get"])

    def test_checks_the_quotes_of_the_earlier_facts_before_any_model_call(self):
        self.assertEqual(self.run_main("api")[-7:], ["present", "fetch_docs.py", "check_quotes", "pull", "model_steps",
                                                    "check_quotes", ("checks", "")])

    def test_the_earlier_quotes_need_no_highlight_in_a_document_the_download_replaced(self):
        checks = []
        self.run_main("api", checked=(f"{URL},{'a' * 64}\n", f"{URL},{'b' * 64}\n"),
                      check_quotes=lambda data, texts, skip=frozenset(): checks.append(skip))
        self.assertEqual(checks, [{URL}, frozenset()])

    def test_without_earlier_facts_checks_only_the_new_quotes(self):
        self.assertEqual(self.run_main("replay", facts=False), [("code", ""), "pull", "model_steps", "check_quotes", ("checks", "")])

    def test_checks_the_built_data_after_the_model_steps(self):
        self.assertEqual(self.run_main("replay")[-3:], ["model_steps", "check_quotes", ("checks", "")])

    def test_a_candidate_downloads_only_documents_no_run_checked(self):
        order = self.run_main("api", "present@2")
        self.assertLess(order.index("reuse_checked"), order.index("fetch_docs.py"))
        self.assertNotIn("reuse_checked", self.run_main("api"))

    def test_leaves_a_candidates_data_for_its_pin_to_check(self):
        self.assertEqual(self.run_main("api", "present@2")[-2:], ["model_steps", "check_quotes"])


if __name__ == "__main__":
    unittest.main()
