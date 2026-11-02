import json, os, pathlib, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import steps

KNOWN = {"filled": {1: None, 2: None}}


class VersionsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = pathlib.Path(tmp.name)
        (self.data / "steps.json").write_text(json.dumps({"filled": 1}))

    def test_runs_the_pinned_versions(self):
        self.assertEqual(steps.versions(self.data, KNOWN), {"filled": 1})

    def test_a_candidate_replaces_its_steps_pin(self):
        self.assertEqual(steps.versions(self.data, KNOWN, "filled@2"), {"filled": 2})

    def test_checks_only_the_steps_it_knows(self):
        (self.data / "steps.json").write_text(json.dumps({"filled": 1, "other": 5}))
        self.assertEqual(steps.versions(self.data, KNOWN)["filled"], 1)

    def test_rejects_an_unknown_candidate(self):
        for candidate in ("blanks@2", "filled@3", "filled", "filled@two"):
            with self.assertRaises(SystemExit, msg=candidate):
                steps.versions(self.data, KNOWN, candidate)

    def test_rejects_an_unknown_or_missing_pin(self):
        for pins in ({"filled": 3}, {}):
            (self.data / "steps.json").write_text(json.dumps(pins))
            with self.assertRaises(SystemExit, msg=pins):
                steps.versions(self.data, KNOWN)


if __name__ == "__main__":
    unittest.main()
