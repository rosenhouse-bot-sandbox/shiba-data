import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import compare_reviewers


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
    def test_counts_agreement_on_each_kind_of_pinned_verdict_and_a_missing_one_as_a_reject(self):
        pinned = {"a": True, "b": True, "c": False, "d": False}
        got = {"a": True, "b": False, "c": True, "d": None}
        self.assertEqual(compare_reviewers.agreement(pinned, got), dict(accepts=(1, 2), rejects=(1, 2)))


if __name__ == "__main__":
    unittest.main()
