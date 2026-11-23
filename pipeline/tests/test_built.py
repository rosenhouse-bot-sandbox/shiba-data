import contextlib, io, os, pathlib, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import built


class Plain(unittest.TestCase):
    def test_plain(self):
        pass

    @built.check
    def test_marked(self):
        pass


@built.check
class Marked(unittest.TestCase):
    def test_in_a_marked_class(self):
        pass


def names(suite):
    return sorted(t.id().rsplit(".", 1)[1] for t in suite)


class SplitTest(unittest.TestCase):
    def test_a_marked_test_or_class_is_a_check(self):
        loader = unittest.TestLoader()
        suite = unittest.TestSuite([loader.loadTestsFromTestCase(Plain), loader.loadTestsFromTestCase(Marked)])
        code, checks = built.split(suite)
        self.assertEqual(names(code), ["test_plain"])
        self.assertEqual(names(checks), ["test_in_a_marked_class", "test_marked"])

    def test_a_module_that_fails_to_load_is_code(self):
        failed = unittest.TestLoader().loadTestsFromName("no_such_module_anywhere")
        code, checks = built.split(failed)
        self.assertEqual((code.countTestCases(), checks.countTestCases()), (1, 0))


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
    def test_code_tests_see_data_without_built_files(self):
        seen = {}

        def discover(loader, start):
            seen["data"] = os.environ.get("SHIBA_DATA")
            seen["outputs"] = [p for p in built.OUTPUTS if pathlib.Path(seen["data"], "2027", p).exists()]
            seen["config"] = pathlib.Path(seen["data"], "2027", "config.json").exists()
            return unittest.TestSuite()
        with mock.patch.object(unittest.TestLoader, "discover", discover), contextlib.redirect_stderr(io.StringIO()):
            self.assertTrue(built.main("code"))
        self.assertEqual((seen["outputs"], seen["config"]), ([], True))
        self.assertNotEqual(seen["data"], os.environ.get("SHIBA_DATA"))

    def test_checks_read_the_data_as_it_is(self):
        seen = {}

        def discover(loader, start):
            seen["data"] = os.environ.get("SHIBA_DATA")
            return unittest.TestSuite()
        with mock.patch.object(unittest.TestLoader, "discover", discover), contextlib.redirect_stderr(io.StringIO()):
            self.assertTrue(built.main("checks"))
        self.assertEqual(seen["data"], os.environ.get("SHIBA_DATA"))

    def test_fails_when_a_test_fails(self):
        class Failing(unittest.TestCase):
            def test_fails(self):
                self.fail()
        suite = unittest.TestLoader().loadTestsFromTestCase(Failing)
        with mock.patch.object(unittest.TestLoader, "discover", lambda loader, start: suite), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertFalse(built.main("code"))


if __name__ == "__main__":
    unittest.main()
