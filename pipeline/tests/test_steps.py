import json, os, pathlib, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import steps

KNOWN = {"present": {1: None, 2: None}, "facts": {1: None, 2: None}}


class VersionsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = pathlib.Path(tmp.name)
        (self.data / "steps.json").write_text(json.dumps({"present": 1, "facts": 1}))

    def test_runs_the_pinned_versions(self):
        self.assertEqual(steps.versions(self.data, KNOWN), {"present": 1, "facts": 1})

    def test_a_candidate_replaces_its_steps_pin(self):
        self.assertEqual(steps.versions(self.data, KNOWN, "present@2"), {"present": 2, "facts": 1})

    def test_candidates_for_several_steps_run_together(self):
        self.assertEqual(steps.versions(self.data, KNOWN, "present@2, facts@2"), {"present": 2, "facts": 2})

    def test_checks_only_the_steps_it_knows(self):
        (self.data / "steps.json").write_text(json.dumps({"present": 1, "facts": 1, "other": 5}))
        self.assertEqual(steps.versions(self.data, KNOWN)["present"], 1)

    def test_rejects_an_unknown_candidate(self):
        for candidate in ("other@2", "present@3", "present", "present@two", "present@2,present@1"):
            with self.assertRaises(SystemExit, msg=candidate):
                steps.versions(self.data, KNOWN, candidate)

    def test_rejects_an_unknown_or_missing_pin(self):
        for pins in ({"present": 3, "facts": 1}, {"facts": 1}):
            (self.data / "steps.json").write_text(json.dumps(pins))
            with self.assertRaises(SystemExit, msg=pins):
                steps.versions(self.data, KNOWN)


if __name__ == "__main__":
    unittest.main()
