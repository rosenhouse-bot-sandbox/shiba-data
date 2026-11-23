import contextlib, io, os, pathlib, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import built


def suite(ran=None):
    """A plain test, a marked test and a test in a marked class, which note their names in ran."""
    class Plain(unittest.TestCase):
        def test_plain(self):
            ran.append("test_plain")

        @built.check
        def test_marked(self):
            ran.append("test_marked")

    @built.check
    class Marked(unittest.TestCase):
        def test_in_a_marked_class(self):
            ran.append("test_in_a_marked_class")

    loader = unittest.TestLoader()
    return unittest.TestSuite([loader.loadTestsFromTestCase(Plain), loader.loadTestsFromTestCase(Marked)])


def names(tests):
    return sorted(t.id().rsplit(".", 1)[1] for t in tests)


class SplitTest(unittest.TestCase):
    def test_a_marked_test_or_class_is_a_check(self):
        code, checks = built.split(suite())
        self.assertEqual(names(code), ["test_plain"])
        self.assertEqual(names(checks), ["test_in_a_marked_class", "test_marked"])

    def test_a_module_that_fails_to_load_fails_both(self):
        failed = unittest.TestLoader().loadTestsFromName("no_such_module_anywhere")
        code, checks = built.split(failed)
        self.assertEqual((code.countTestCases(), checks.countTestCases()), (1, 1))


class WithoutBuiltTest(unittest.TestCase):
    def test_copies_a_year_but_its_outputs_and_run_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = pathlib.Path(tmp, "data"), pathlib.Path(tmp, "copy")
            dirs = [f"{name}/a.json" for name in built.RUN_STATE if not name.endswith(".csv")]
            for name in ("config.json", "comments.csv", "generated/documents_checked.csv", "evaluations/imaging/all.md",
                         *built.OUTPUTS, "machine/reviewed_facts.csv", *dirs):
                path = src / "2027" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("x")
            built.without_built(src, dst)
            kept = sorted(str(p.relative_to(dst / "2027")) for p in dst.rglob("*") if p.is_file())
        self.assertEqual(kept, ["comments.csv", "config.json", "evaluations/imaging/all.md", "generated/documents_checked.csv"])


class MainTest(unittest.TestCase):
    def main(self, kind, discover):
        with mock.patch.object(unittest.TestLoader, "discover", discover), contextlib.redirect_stderr(io.StringIO()):
            return built.main(kind)

    def test_runs_only_the_kind_asked_for(self):
        for kind, expected in (("code", ["test_plain"]), ("checks", ["test_marked", "test_in_a_marked_class"])):
            ran = []
            self.assertTrue(self.main(kind, lambda loader, start: suite(ran)))
            self.assertEqual(sorted(ran), sorted(expected))

    def test_code_tests_see_data_without_built_files(self):
        seen = {}

        def discover(loader, start):
            seen["data"] = os.environ["SHIBA_DATA"]
            seen["outputs"] = [p for p in built.OUTPUTS if pathlib.Path(seen["data"], "2027", p).exists()]
            seen["config"] = pathlib.Path(seen["data"], "2027", "config.json").exists()
            return unittest.TestSuite()
        before = os.environ.get("SHIBA_DATA")
        self.main("code", discover)
        self.assertEqual((seen["outputs"], seen["config"]), ([], True))
        self.assertNotEqual(seen["data"], before)
        self.assertEqual(os.environ.get("SHIBA_DATA"), before)

    def test_checks_read_the_data_as_it_is(self):
        seen = {}

        def discover(loader, start):
            seen["data"] = os.environ.get("SHIBA_DATA")
            return unittest.TestSuite()
        self.main("checks", discover)
        self.assertEqual(seen["data"], os.environ.get("SHIBA_DATA"))

    def test_fails_when_a_test_fails(self):
        class Failing(unittest.TestCase):
            def test_fails(self):
                self.fail()
        failing = unittest.TestLoader().loadTestsFromTestCase(Failing)
        self.assertFalse(self.main("code", lambda loader, start: failing))


if __name__ == "__main__":
    unittest.main()
