import json, os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import compare_reviewers, extract


class PinnedVerdictsTest(unittest.TestCase):
    def test_reads_the_gate_verdict_of_each_prompt(self):
        with tempfile.TemporaryDirectory() as replay:
            os.makedirs(f"{replay}/facts/review")
            with open(f"{replay}/facts/review/{extract.OUTCOMES}", "w") as f:
                json.dump([dict(prompt="a", ok=True), dict(prompt="b", ok=False), dict(prompt="c", ok=None)], f)
            self.assertEqual(compare_reviewers.pinned_verdicts(replay), {"a": True, "b": False, "c": False})


class ChosenTest(unittest.TestCase):
    pinned = {"a": True, "b": False, "c": True, "d": True, "e": False}

    def test_takes_every_reject_and_some_accepts(self):
        got = compare_reviewers.chosen(self.pinned, 2)
        self.assertEqual({p for p in got if not self.pinned[p]}, {"b", "e"})
        self.assertEqual(sum(self.pinned[p] for p in got), 2)

    def test_takes_the_same_accepts_in_any_order(self):
        backwards = dict(reversed(self.pinned.items()))
        self.assertEqual(set(compare_reviewers.chosen(self.pinned, 2)), set(compare_reviewers.chosen(backwards, 2)))


class AgreementTest(unittest.TestCase):
    def test_counts_a_missing_verdict_apart_from_agreement(self):
        pinned = {"a": True, "b": True, "c": False, "d": False}
        got = {"a": True, "b": False, "c": True, "d": None}
        self.assertEqual(compare_reviewers.agreement(pinned, got), dict(accepts=(1, 2), rejects=(0, 1), unanswered=1))


if __name__ == "__main__":
    unittest.main()
