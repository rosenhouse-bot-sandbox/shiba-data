import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import built, facts, rereview, review, run
from test_review import DATA, committed_facts


def present_pin():
    return run.steps.versions(DATA, run.STEPS)["present"]


@built.check
class UnansweredTest(unittest.TestCase):
    def test_skips_answered_facts(self):
        self.assertEqual(rereview.unanswered(DATA, committed_facts(), lambda f: True, present_pin()), [])

    def test_lists_each_cited_trusted_fact_once(self):
        got = [review.row(f) for f in rereview.unanswered(DATA, committed_facts() * 2, lambda f: False, present_pin())]
        self.assertEqual(len(got), len(set(got)))
        self.assertEqual(set(got), review.cited(DATA, committed_facts(), present_pin())
                         & review.trusted(DATA, committed_facts(), present_pin()))


class FirstTest(unittest.TestCase):
    rows = [dict(dict.fromkeys(facts.COLUMNS, ""), fact_id=str(n)) for n in range(10)]

    def test_takes_the_same_rows_in_any_order(self):
        self.assertEqual(rereview.first(self.rows, 3), rereview.first(self.rows[::-1], 3))

    def test_a_rerun_without_the_answered_rows_takes_the_next_ones(self):
        taken = rereview.first(self.rows, 3)
        self.assertEqual(rereview.first([r for r in self.rows if r not in taken], 3), rereview.first(self.rows, 6)[3:])


if __name__ == "__main__":
    unittest.main()
