import contextlib, csv, io, json, os, pathlib, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import layers
import run

URL = "https://example.org/sb.pdf"


class LostQuotesTest(unittest.TestCase):
    def test_lists_layer_rows_the_site_cannot_highlight_even_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, texts = pathlib.Path(tmp, "2027"), pathlib.Path(tmp, "texts")
            (data / "generated").mkdir(parents=True)
            (texts / "items").mkdir(parents=True)
            with open(data / "generated" / "documents_checked.csv", "w") as f:
                f.write(f"url,sha256\n{URL},{'a' * 64}\n")
            page = {"strs": ["Specialist $40 copay", "Specialist $40 copay"], "lefts": [0, 0]}
            (texts / "items" / f"{'a' * 16}.json").write_text(json.dumps({"2": page}))
            with open(data / "edits.csv", "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=layers.EDIT_COLUMNS)
                w.writeheader()
                for quote in ("Specialist $40", "Specialist $50", ""):
                    w.writerow(dict(sheet="main", plan_id="P", column="G_specialist", line="", value="$40", url=URL,
                                    pdf_page="2", quote=quote, saw="$40", source="session", author="", note=""))
            lost = run.lost_quotes(data, texts)
        self.assertEqual([c["quote"] for c in lost], ["Specialist $50"])


class AnswersTest(unittest.TestCase):
    def test_stops_and_lists_tasks_without_an_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            pathlib.Path(tmp, "P-1.md").write_text("task")
            out = io.StringIO()
            with self.assertRaises(SystemExit) as stop, contextlib.redirect_stdout(out):
                run.Answers(pathlib.Path(tmp), None)(tmp, run.READER)
        self.assertIn(f"{tmp}/P-1.md", out.getvalue())
        self.assertIn("1 of 1 tasks", str(stop.exception))


class StepsTest(unittest.TestCase):
    def calls(self, step, name):
        log = []
        module = mock.Mock(**{f"{f}.side_effect": (lambda f: lambda *a, **kw: log.append((f, kw) if kw else f))(f)
                              for f in ("bundle", "claims", "verify", "accept", "publish")})
        with tempfile.TemporaryDirectory() as work, mock.patch.dict(sys.modules, {name: module}):
            step("texts", work, lambda d, model: log.append((os.path.relpath(d, work), model)))
        return log

    def test_blanks_reads_with_the_reader_and_verifies_twice(self):
        self.assertEqual(self.calls(run.blanks_step, "blanks"), [
            "bundle", ("blanks/read", run.READER), "claims", "verify", ("blanks/check", run.VERIFIER), "accept",
            "verify", ("blanks/recheck", run.SECOND_VERIFIER), "accept", "publish"])

    def test_filled_answers_one_retry_round_before_verifying_twice(self):
        self.assertEqual(self.calls(run.filled_step, "filled"), [
            "bundle", ("filled/read", run.READER), "claims", ("filled/read", run.READER), "claims",
            "verify", ("filled/check", run.VERIFIER), "accept", "verify", ("filled/recheck", run.SECOND_VERIFIER), "accept",
            ("publish", {"every": False})])

    def test_filled_can_bundle_and_publish_every_filled_cell(self):
        module = mock.Mock()
        with tempfile.TemporaryDirectory() as work, mock.patch.dict(sys.modules, {"filled": module}):
            run.filled_step("texts", work, lambda d, model: None, every=True)
        self.assertEqual(module.bundle.call_args.args[2], "every")
        self.assertEqual(module.publish.call_args.kwargs, {"every": True})


if __name__ == "__main__":
    unittest.main()
