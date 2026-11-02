import json, os, random, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import extract, facts

SHA = "cd" * 32
DOC = {"id": SHA[:16], "sha256": SHA, "kind": "EOC", "plan_ids": ["H1036-306-0", "H1036-307-0"]}
NAMES = {"H1036-306-0": {"plan_name": "Gold", "organization": "Humana"},
         "H1036-307-0": {"plan_name": "Silver", "organization": "Humana"}}
PAGES = {3: "Index", 61: "Outpatient X-rays  $0 to $40 copay\nMRI and CT scans $250 copay", 62: "Dental X-rays"}


def answer(**changes):
    row = dict(plan_id="H1036-306-0", benefit="imaging.xray", setting="any", network="in", covered_by="medicare",
               cost_kind="copay", amount="$0-$40", unit="", limit="", page=61, quotes=["Outpatient X-rays  $0 to $40 copay"])
    row.update(changes)
    return row


def ok_unless_bad(page, quote):
    return "bad" not in quote


class PagesTest(unittest.TestCase):
    def test_keeps_pages_that_mention_the_group(self):
        self.assertEqual(sorted(extract.relevant(PAGES, "imaging")), [61, 62])


class TaskTest(unittest.TestCase):
    def test_shows_plans_vocabulary_and_pages(self):
        text = extract.task(DOC, NAMES, PAGES, "imaging")
        for part in ("H1036-306-0", "Gold", "H1036-307-0", "Silver", facts.describe("imaging"), "Seen in Humana",
                     "=====PAGE 61=====\nOutpatient X-rays", "=====PAGE 62====="):
            self.assertIn(part, text)
        self.assertNotIn("=====PAGE 3=====", text)

    def test_shows_failed_facts(self):
        text = extract.task(DOC, NAMES, PAGES, "imaging", [(answer(), "no quote shows $40")])
        self.assertIn("no quote shows $40", text)
        self.assertIn('"amount": "$0-$40"', text)

    def test_is_stable(self):
        self.assertEqual(extract.task(DOC, NAMES, PAGES, "imaging"), extract.task(DOC, dict(NAMES), dict(PAGES), "imaging"))


class GateTest(unittest.TestCase):
    def gate(self, *answers):
        return extract.gate(DOC, "imaging", list(answers), ok_unless_bad)

    def test_turns_a_good_answer_into_a_fact(self):
        (fact,), failed = self.gate(answer())
        self.assertEqual(failed, [])
        self.assertEqual(facts.check(fact), [])
        self.assertEqual((fact["source"], fact["doc_sha"], fact["page"]), ("EOC", SHA, "61"))
        self.assertEqual(json.loads(fact["quotes"]), ["Outpatient X-rays  $0 to $40 copay"])

    def test_rejects(self):
        cases = {
            "plan_id": answer(plan_id="H9003-001-0"),
            "benefit": answer(benefit="radiation_therapy"),
            "shows $45": answer(amount="$0-$45"),
            "quote": answer(quotes=["bad quote $0 $40"]),
            "page": answer(page="61"),
            "quotes": answer(quotes=[]),
            "setting": answer(setting="clinic"),
            "fields": answer(color="red"),
        }
        for words, a in cases.items():
            with self.subTest(words):
                found, ((got, why),) = self.gate(a)
                self.assertEqual((found, got), ([], a))
                self.assertIn(words, why)

    def test_needs_every_number_in_the_amount(self):
        self.assertEqual(len(self.gate(answer(amount="$40", quotes=["Outpatient X-rays  $0 to $40 copay"]))[0]), 1)
        self.assertEqual(len(self.gate(answer(cost_kind="covered", amount="", quotes=["Outpatient X-rays"]))[0]), 1)
        self.assertEqual(len(self.gate(answer(cost_kind="visit_limit", amount="4", quotes=["Outpatient X-rays"]))[1]), 1)

    def test_rejects_an_answer_that_is_not_an_object(self):
        self.assertEqual(self.gate("text")[1], [("text", "not an object")])

    def test_rejects_both_copies_of_a_conflict(self):
        found, failed = self.gate(answer(), answer(quotes=["MRI and CT scans $250 copay"], amount="$250"))
        self.assertEqual(found, [])
        self.assertEqual([why for _, why in failed], ["two answers for one fact on one page"] * 2)

    def test_keeps_one_copy_of_a_repeat(self):
        self.assertEqual(len(self.gate(answer(), answer())[0]), 1)


class DecoyTest(unittest.TestCase):
    def facts(self):
        return extract.gate(DOC, "imaging", [
            answer(setting="office", amount="$40", quotes=["$40 office"]),
            answer(setting="outpatient_hospital", amount="$145", quotes=["$145 hospital"]),
            answer(setting="freestanding", amount="$40", quotes=["$40 freestanding"]),
            answer(plan_id="H1036-307-0", setting="office", amount="$15", quotes=["$15 office"]),
            answer(benefit="imaging.diagnostic.advanced.mri", amount="$250", quotes=["MRI $250"]),
        ], ok_unless_bad)[0]

    def test_put_an_amount_under_a_key_that_has_another(self):
        real = self.facts()
        by_id = {f["fact_id"]: f for f in real}
        made = extract.decoys(real, random.Random(1), n=50)
        self.assertEqual(len(made), 6)
        for d in made:
            self.assertNotEqual(d["amount"], by_id[d["fact_id"]]["amount"])
            self.assertEqual(sum(d[k] != by_id[d["fact_id"]][k] for k in facts.KEY), 0)
            self.assertIn(d["amount"], {f["amount"] for f in real if f["quotes"] == d["quotes"]})
            self.assertEqual(facts.check(d), [])

    def test_is_seeded(self):
        self.assertEqual(extract.decoys(self.facts(), random.Random(3)), extract.decoys(self.facts(), random.Random(3)))


class AcceptTest(unittest.TestCase):
    items = [{"fact_id": "a", "decoy": False}, {"fact_id": "b", "decoy": True}, {"fact_id": "c", "decoy": False}]

    def test_keeps_facts_every_verdict_accepts(self):
        verdicts = [{"id": 0, "ok": True}, {"id": 1, "ok": False}, {"id": 2, "ok": True}, {"id": 2, "ok": False}]
        self.assertEqual(extract.accepted(self.items, verdicts), [{"fact_id": "a"}])

    def test_drops_items_without_a_verdict(self):
        self.assertEqual(extract.accepted(self.items, [{"id": 1, "ok": False}]), [])

    def test_fails_when_a_decoy_is_accepted(self):
        with self.assertRaisesRegex(SystemExit, "decoys \\[1\\]"):
            extract.accepted(self.items, [{"id": 1, "ok": True}])


class VerifierTaskTest(unittest.TestCase):
    def test_shows_items_without_saying_which_are_decoys(self):
        real = extract.gate(DOC, "imaging", [answer()], ok_unless_bad)[0]
        items = [dict(real[0], decoy=False), dict(real[0], plan_id="H1036-307-0", decoy=True)]
        text = extract.verifier_task(DOC, NAMES, PAGES, items)
        self.assertNotIn("decoy", text)
        self.assertIn(facts.describe("imaging"), text)
        self.assertIn('"id": 1', text)
        self.assertIn("=====PAGE 61=====", text)
        self.assertNotIn("=====PAGE 62=====", text)


if __name__ == "__main__":
    unittest.main()
