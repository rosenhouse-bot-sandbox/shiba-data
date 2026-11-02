import contextlib, csv, io, json, os, pathlib, random, shutil, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import extract, facts
from eoc import DATA

SHA = "cd" * 32
DOC = {"id": SHA[:16], "sha256": SHA, "kind": "EOC", "plan_ids": ["H1036-306-0", "H1036-307-0"]}
NAMES = {"H1036-306-0": {"plan_name": "Gold", "organization": "Humana"},
         "H1036-307-0": {"plan_name": "Silver", "organization": "Humana"}}
X_RAYS = "Outpatient X-rays $0 to $40 copay"
PAGES = {3: "Index", 61: f"{X_RAYS}\nMRI and CT scans $250 copay", 62: "Dental X-rays"}


def answer(**changes):
    row = dict(plan_id="H1036-306-0", benefit="imaging.xray", setting="any", network="in", covered_by="medicare",
               cost_kind="copay", amount="$0-$40", page=61, quotes=[X_RAYS])
    row.update(changes)
    return row


def ok_unless_bad(page, quote):
    return "bad" not in quote


def gate(*answers):
    return extract.gate(DOC, "imaging", list(answers), PAGES, ok_unless_bad)


class PagesTest(unittest.TestCase):
    def test_keeps_pages_that_mention_the_group(self):
        self.assertEqual(sorted(extract.relevant(PAGES, "imaging")), [61, 62])


class TaskTest(unittest.TestCase):
    def test_shows_plans_vocabulary_and_pages(self):
        text = extract.task(DOC, NAMES, PAGES, "imaging", DATA)
        for part in ("H1036-306-0: Gold", "H1036-307-0: Silver", facts.describe("imaging"), "Seen in Humana",
                     "plan year 2027", f"=====PAGE 61=====\n{X_RAYS}", "=====PAGE 62=====\nDental X-rays"):
            self.assertIn(part, text)
        self.assertNotIn("=====PAGE 3=====", text)

    def test_asks_only_for_fixes_of_failed_answers(self):
        text = extract.task(DOC, NAMES, PAGES, "imaging", DATA, [(answer(), "no quote shows $40"), ("\ud800", "x")])
        self.assertIn('"quotes": ["Outpatient X-rays $0 to $40 copay"]}: no quote shows $40', text)
        self.assertIn("fixed versions of only these answers", text)
        text.encode()


class GateTest(unittest.TestCase):
    def test_turns_a_good_answer_into_a_fact(self):
        (fact,), failed = gate(answer())
        self.assertEqual(failed, [])
        self.assertEqual(facts.check(fact), [])
        self.assertEqual((fact["source"], fact["doc_sha"], fact["page"], fact["unit"]), ("EOC", SHA, "61", ""))
        self.assertEqual(json.loads(fact["quotes"]), [X_RAYS])

    def test_rejects(self):
        cases = [
            ("plan_id: this document covers", answer(plan_id="H9003-001-0")),
            ("benefit: radiation_therapy is not in imaging", answer(benefit="radiation_therapy")),
            ("no quote shows $45", answer(amount="$0-$45")),
            ("quote not found", answer(quotes=["bad quote $0 $40"])),
            ("whole number", answer(page="61")),
            ("whole number", answer(page=61.0)),
            ("whole number", answer(page=True)),
            ("no page 99", answer(page=99)),
            ("quotes:", answer(quotes=[])),
            ("quotes:", answer(quotes=X_RAYS)),
            ("quotes:", answer(quotes=[1])),
            ("setting: 'clinic'", answer(setting="clinic")),
            ("unknown fields: color", answer(color="red")),
            ("missing fields: quotes", {k: v for k, v in answer().items() if k != "quotes"}),
            ("give note, unit as text", answer(unit=None, note=None)),
            ("give plan_id as text", answer(plan_id=["H1036-306-0"])),
            ("not valid Unicode", answer(note="\ud800")),
            ("not an object", "text"),
        ]
        for words, a in cases:
            with self.subTest(words):
                found, ((got, why),) = gate(a)
                self.assertEqual((found, got), ([], a))
                self.assertIn(words, why)

    def test_needs_every_number_in_the_amount(self):
        self.assertEqual(len(gate(answer(amount="$40"))[0]), 1)
        self.assertEqual(len(gate({k: v for k, v in answer(cost_kind="covered").items() if k != "amount"})[0]), 1)
        self.assertEqual(len(gate(answer(cost_kind="visit_limit", amount="4"))[1]), 1)

    def test_rejects_both_copies_of_a_conflict(self):
        found, failed = gate(answer(), answer(quotes=["MRI and CT scans $250 copay"], amount="$250"))
        self.assertEqual(found, [])
        self.assertEqual([why for _, why in failed], ["two answers for one fact on one page"] * 2)

    def test_keeps_one_copy_of_a_repeat(self):
        self.assertEqual(len(gate(answer(), answer())[0]), 1)


class DocFactsTest(unittest.TestCase):
    def run_it(self, first, retry):
        return extract.doc_facts(DOC, "imaging", first, retry, PAGES, ok_unless_bad)

    def test_first_answers_ask_for_a_retry(self):
        found, failed = self.run_it([answer(), answer(amount="$5")], None)
        self.assertEqual((len(found), [why for _, why in failed]), (1, ["no quote shows $5"]))

    def test_retry_adds_fixes_and_ends_the_retries(self):
        fixed = answer(benefit="imaging.diagnostic.advanced", amount="$250", quotes=["MRI and CT scans $250 copay"])
        found, failed = self.run_it([answer(), answer(amount="$5")], [fixed, answer()])
        self.assertEqual(sorted(f["benefit"] for f in found), ["imaging.diagnostic.advanced", "imaging.xray"])
        self.assertEqual(failed, [])


class DecoyTest(unittest.TestCase):
    def facts(self, *more):
        return gate(answer(setting="office", amount="$40", quotes=["$40 office"]),
                    answer(setting="outpatient_hospital", amount="$145", quotes=["$145 hospital"]),
                    answer(setting="freestanding", amount="$40", quotes=["$40 freestanding"]),
                    answer(plan_id="H1036-307-0", setting="office", amount="$15", quotes=["$15 office"]),
                    answer(benefit="imaging.diagnostic.advanced.mri", amount="$250", quotes=["MRI $250"]), *more)[0]

    def test_put_an_amount_under_a_key_that_never_has_it(self):
        real = self.facts()
        amounts = {f["fact_id"]: f["amount"] for f in real}
        made = extract.decoys(real, random.Random(1), n=50)
        self.assertEqual(len(made), 6)
        for d in made:
            self.assertNotEqual(d["amount"], amounts[d["fact_id"]])
            self.assertEqual(d["fact_id"], facts.fact_id(d))
            self.assertIn((d["amount"], d["quotes"]), {(f["amount"], f["quotes"]) for f in real})
            self.assertEqual(facts.check(d), [])

    def test_skips_amounts_the_key_has_on_another_page(self):
        made = extract.decoys(self.facts(answer(setting="office", amount="$145", page=62, quotes=["$145 Dental X-rays"])),
                              random.Random(1), n=50)
        self.assertNotIn(("office", "H1036-306-0", "$145"), {(d["setting"], d["plan_id"], d["amount"]) for d in made})

    def test_never_moves_to_a_covering_setting(self):
        real = self.facts(answer(setting="office.pcp", amount="$5", quotes=["$5 pcp"]))
        settings = {(d["setting"], d["amount"]) for d in extract.decoys(real, random.Random(1), n=50)}
        self.assertNotIn(("office", "$5"), settings)
        self.assertNotIn(("office.pcp", "$40"), settings)

    def test_samples_by_seed(self):
        real = self.facts()
        self.assertEqual(extract.decoys(real, random.Random(3)), extract.decoys(real, random.Random(3)))
        self.assertNotEqual(extract.decoys(real, random.Random(3)), extract.decoys(real, random.Random(4)))


class VerifierTaskTest(unittest.TestCase):
    def test_shows_items_and_their_pages_without_notes_or_decoy_flags(self):
        real = gate(answer(note="unsure"))[0]
        items = [dict(real[0], decoy=False), dict(real[0], plan_id="H1036-307-0", decoy=True)]
        text = extract.verifier_task(DOC, NAMES, PAGES, items, DATA)
        for part in ('{"id": 0, "plan_id": "H1036-306-0"', '{"id": 1, "plan_id": "H1036-307-0"',
                     facts.describe("imaging"), f"=====PAGE 61=====\n{X_RAYS}"):
            self.assertIn(part, text)
        for part in ("decoy", "unsure", "=====PAGE 62====="):
            self.assertNotIn(part, text)


class StepsTest(unittest.TestCase):
    """read, facts and verify on a work directory with two documents."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name)
        self.data, self.work, self.dir = root / "2027", root / "work", root / "read"
        (self.data / "generated").mkdir(parents=True)
        shutil.copy(f"{DATA}/config.json", self.data)
        with open(self.data / "generated" / "documents_checked.csv", "w") as f:
            f.write(f"plan_ids,kind,sha256\nH1036-306-0,EOC,{SHA}\nH1036-306-0,SB,{'ef' * 32}\nH1036-306-0,EOC,\n")
        with open(self.data / "generated" / "plans.csv", "w") as f:
            f.write("plan_id,plan_name,organization\nH1036-306-0,Gold,Humana\n")
        for sub in ("text", "layout", "items"):
            (self.work / sub).mkdir(parents=True)
        for doc, text in ((SHA[:16], X_RAYS), ("ef" * 8, "Dental cleanings")):
            for sub in ("text", "layout"):
                (self.work / sub / f"{doc}.txt").write_text(f"=====PAGE 1=====\n{text}\n")
            (self.work / "items" / f"{doc}.json").write_text(json.dumps({"1": {"strs": [text], "lefts": [0]}}))

    def step(self, f, *args, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            f(*map(str, args), data=self.data, **kwargs)
        return out.getvalue()

    def test_read_writes_tasks_for_documents_that_mention_the_group(self):
        self.step(extract.read, self.work, self.dir, "imaging")
        self.assertEqual(os.listdir(self.dir), [f"{SHA[:16]}.md"])

    def test_read_can_skip_documents(self):
        self.step(extract.read, self.work, self.dir, "imaging", ids=set())
        self.assertEqual(os.listdir(self.dir), [])

    def test_facts_retries_once_then_verify_writes_tasks_and_items(self):
        self.step(extract.read, self.work, self.dir, "imaging")
        good, bad = answer(page=1), answer(page=1, amount="$5")
        (self.dir / f"{SHA[:16]}.json").write_text(json.dumps([good, bad]))
        out = self.dir / "facts.json"
        self.assertEqual(self.step(extract.extract_facts, self.work, self.dir, "imaging", out), "1 facts; 1 retry tasks\n")
        self.assertIn("no quote shows $5", (self.dir / f"{SHA[:16]}.retry.md").read_text())
        (self.dir / f"{SHA[:16]}.retry.md").unlink()
        (self.dir / f"{SHA[:16]}.retry.json").write_text("not json")
        self.assertEqual(self.step(extract.extract_facts, self.work, self.dir, "imaging", out), "1 facts; 0 retry tasks\n")
        self.assertFalse((self.dir / f"{SHA[:16]}.retry.md").exists())

        check = self.dir.parent / "check"
        self.assertEqual(self.step(extract.verify, self.work, out, check), "1 facts 0 decoys\n")
        items = json.loads((check / "items.json").read_text())
        self.assertEqual([(i["task"], i["decoy"], i["amount"]) for i in items], [(SHA[:16], False, "$0-$40")])
        self.assertIn(X_RAYS, (check / f"v-{SHA[:16]}.md").read_text())


if __name__ == "__main__":
    unittest.main()
