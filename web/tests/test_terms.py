import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import terms  # noqa: E402

REPO = HERE.parent.parent


class TermsTest(unittest.TestCase):
    def test_every_term_resolves_to_code_at_the_commit(self):
        got = terms.resolve(REPO, "abc123")
        self.assertEqual(set(got), set(terms.TERMS))
        rule = got["rule"]
        self.assertTrue(rule["code"].startswith("def ambulance("))
        self.assertRegex(rule["url"], r"^https://github\.com/rosenhouse-bot-sandbox/shiba-data/blob/abc123/pipeline/present\.py#L\d+-L\d+$")
        self.assertEqual(rule["where"], "pipeline/present.py: ambulance")

    def test_the_view_names_exactly_these_terms(self):
        script = ('import("./static/pipeline.js").then((m) => console.log(JSON.stringify('
                  'm.STEPS.flatMap((s) => [...s.paras, ...(s.example?.paras ?? [])].flat()).filter(Array.isArray).map((s) => s[0]))))')
        used = set(json.loads(subprocess.run(["node", "-e", script], cwd=HERE.parent, capture_output=True, text=True,
                                             check=True).stdout))
        self.assertEqual(used, set(terms.TERMS))

    def test_text_shown_for_any_cell_names_no_ambulance(self):
        script = ('import("./static/pipeline.js").then((m) => console.log(JSON.stringify('
                  'm.STEPS.flatMap((s) => s.paras.flat()))))')
        segments = json.loads(subprocess.run(["node", "-e", script], cwd=HERE.parent, capture_output=True, text=True,
                                             check=True).stdout)
        shown = [s if isinstance(s, str) else " ".join([s[1], terms.TERMS[s[0]]["title"], terms.TERMS[s[0]]["text"]])
                 for s in segments]
        self.assertEqual([s for s in shown if "mbulance" in s], [])

    def test_each_link_spans_exactly_the_code_shown(self):
        for name, t in terms.resolve(REPO, "abc123").items():
            if not t["code"]:
                continue
            path, lines = t["url"].split("/blob/abc123/")[1].split("#")
            start, end = (int(n) for n in lines.replace("L", "").split("-"))
            self.assertEqual("\n".join((REPO / path).read_text().splitlines()[start - 1:end]), t["code"], name)

    def test_an_annotated_constant_resolves(self):
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "m.py").write_text("X: int = 1\n")
            self.assertEqual(terms.locate(pathlib.Path(d), "m.py:X"), ("X: int = 1", 1, 1))

    def test_a_missing_file_fails_the_build(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(terms.TERMS, {"x": {"title": "", "text": "", "ref": "gone.js"}}, clear=True):
            with self.assertRaisesRegex(ValueError, "gone.js does not exist"):
                terms.resolve(pathlib.Path(d), "abc123")

    def test_a_constant_resolves_to_its_assignment(self):
        layer = terms.resolve(REPO, "abc123")["layer"]
        self.assertTrue(layer["code"].startswith("LAYERS = "))

    def test_a_file_term_links_the_file_with_no_code(self):
        worker = terms.resolve(REPO, "abc123")["worker"]
        self.assertEqual(worker["url"], "https://github.com/rosenhouse-bot-sandbox/shiba-data/blob/abc123/web/worker.js")
        self.assertEqual(worker["code"], "")

    def test_a_renamed_function_fails_the_build(self):
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "m.py").write_text("def renamed():\n    pass\n")
            with self.assertRaisesRegex(ValueError, "m.py has no gone"):
                terms.locate(pathlib.Path(d), "m.py:gone")


if __name__ == "__main__":
    unittest.main()
