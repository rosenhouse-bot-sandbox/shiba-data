import json, os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import document_facts, facts, layers, present, review, years

DATA = years.data_dir(years.LIVE)
COMMITTED = facts.read(DATA / "machine/document_facts.csv")
PLAN = "H2923-001-0"


def fact(plan_id=PLAN, source="EOC", **more):
    """A fact the X-ray rule cites for PLAN, or an uncited one with benefit radiation_therapy."""
    doc = next(d for d in layers.rows(DATA / "generated/documents_checked.csv")
               if plan_id in d["plan_ids"].split(";") and d["kind"] == source)
    row = dict.fromkeys(facts.COLUMNS, "")
    row.update(dict(plan_id=plan_id, source=source, benefit="imaging.xray", setting="office.pcp", network="in", covered_by="medicare",
                    cost_kind="copay", amount="$1", doc_sha=doc["sha256"], page="1",
                    quotes=json.dumps(["x"])), **more)
    row["fact_id"] = facts.fact_id(row)
    return row


def answering(rejected=(), asked=None):
    """An answer function that accepts each fact unless its task has one of the rejected texts."""
    def answer(task_dir, model, effort):
        for name in os.listdir(task_dir):
            if name.endswith(".md"):
                text = open(os.path.join(task_dir, name)).read()
                ok = not any(r in text for r in rejected)
                if asked is not None:
                    asked.append(name)
                with open(os.path.join(task_dir, name[:-3] + ".json"), "w") as f:
                    json.dump([{"id": 0, "ok": ok, "reason": "test"}], f)
    return answer


class ToReviewTest(unittest.TestCase):
    def test_reviews_only_new_facts_that_a_cell_cites(self):
        cited, uncited = fact(), fact(benefit="radiation_therapy", amount="$2")
        self.assertEqual(review.to_review(DATA, COMMITTED, COMMITTED + [cited, uncited]), [cited])

    def test_skips_facts_that_only_a_held_cell_cites(self):
        held = fact(plan_id="H6815-038-0", benefit="tests.diagnostic", setting="office.pcp", amount="$9")
        self.assertIn(("K_tests_labs", "H6815-038-0"), present.HELD)
        self.assertEqual(review.to_review(DATA, COMMITTED, COMMITTED + [held]), [])

    def test_an_unchanged_fact_set_needs_no_review(self):
        self.assertEqual(review.to_review(DATA, COMMITTED, COMMITTED), [])


class GateTest(unittest.TestCase):
    def gate(self, old, new, answer, cap=10):
        with tempfile.TemporaryDirectory() as work:
            return review.gate(DATA, None, work, answer, old, new, dict(reviewer=("m", "e"), review_cap=cap),
                               task_of=lambda f: json.dumps(f))

    def test_drops_the_facts_the_reviewer_rejects_and_keeps_the_rest(self):
        good, bad, uncited = fact(), fact(amount="$3", setting="office.specialist"), fact(benefit="radiation_therapy")
        kept = self.gate(COMMITTED, COMMITTED + [good, bad, uncited], answering(["$3"]))
        self.assertIn(good, kept)
        self.assertIn(uncited, kept)
        self.assertNotIn(bad, kept)

    def test_asks_nothing_when_no_cell_cites_a_new_fact(self):
        asked = []
        self.assertEqual(self.gate(COMMITTED, COMMITTED, answering((), asked)), COMMITTED)
        self.assertEqual(asked, [])

    def test_reviews_a_fact_that_a_rejected_fact_hid(self):
        fitness = dict(plan_id="H2406-070-0", benefit="fitness", setting="any", covered_by="supplemental",
                       cost_kind="covered", amount="")
        hiding, hidden = fact(**fitness, quotes='["bad"]'), fact(**fitness, source="SB")
        asked = []
        kept = self.gate(COMMITTED, COMMITTED + [hidden, hiding], answering(["bad"], asked))
        self.assertEqual(len(asked), 2)
        self.assertIn(hidden, kept)
        self.assertNotIn(hiding, kept)

    def test_stops_when_more_new_facts_need_review_than_the_cap(self):
        new = [fact(amount=f"${n}", setting=s) for n, s in ((7, "office.pcp"), (8, "office.specialist"))]
        with self.assertRaisesRegex(SystemExit, "2 facts need review"):
            self.gate(COMMITTED, COMMITTED + new, answering(), cap=1)


class VersionTest(unittest.TestCase):
    def test_version_11_is_10_with_a_reviewer(self):
        v = document_facts.VERSIONS[11]
        self.assertEqual(dict(v, reviewer=None, review_cap=None), dict(document_facts.VERSIONS[10], reviewer=None,
                                                                         review_cap=None))
        self.assertEqual(v["reviewer"], ("claude-opus-5-5", "high"))


if __name__ == "__main__":
    unittest.main()
