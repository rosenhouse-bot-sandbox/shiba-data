import contextlib, io, json, os, pathlib, random, shutil, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ask, extract, facts
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

    def test_a_version_can_name_more_groups_that_price_zeros_in_words(self):
        pages = {7: "Because we have no deductible, this stage does not apply.", 6: "You don’t pay a separate monthly plan premium."}
        deductible = answer(benefit="part_d_deductible", cost_kind="deductible", amount="$0", page=7,
                            quotes=["Because we have no deductible"])
        premium = answer(benefit="plan_premium", cost_kind="premium", amount="$0", page=6,
                         quotes=["You don’t pay a separate monthly plan premium."])
        straight = dict(premium, quotes=["You do not pay a separate monthly plan premium."])
        pages[6] += " You don't pay a separate monthly plan premium. You do not pay a separate monthly plan premium."
        for group, a in (("part_d_deductible", deductible), ("plan_premium", premium), ("plan_premium", straight),
                         ("plan_premium", dict(premium, quotes=["You don't pay a separate monthly plan premium."]))):
            self.assertEqual(len(extract.doc_facts(DOC, group, [a], None, pages, ok_unless_bad)[0]), 0, group)
            zero = extract.ZERO_GROUPS + (group,)
            self.assertEqual(len(extract.doc_facts(DOC, group, [a], None, pages, ok_unless_bad, zero=zero)[0]), 1, group)

    def test_words_for_no_cost_show_0_in_groups_that_price_zeros(self):
        pages = {5: "This plan does not have a deductible.", 52: "There is no coinsurance, copayment, or deductible for flu vaccines"}
        deductible = dict(benefit="medical_deductible", cost_kind="deductible", amount="$0", page=5,
                          quotes=["This plan does not have a deductible."])
        vaccine = dict(benefit="part_b_drugs.vaccine", amount="$0", page=52,
                       quotes=["no coinsurance, copayment, or deductible for flu vaccines"])
        for group, a in (("medical_deductible", deductible), ("part_b_drugs", vaccine)):
            found, failed = extract.gate(DOC, group, [answer(**a)], pages, ok_unless_bad)
            self.assertEqual((len(found), failed), (1, []), group)
            found, ((_, why),) = extract.gate(DOC, group, [answer(**dict(a, amount="$5"))], pages, ok_unless_bad)
            self.assertEqual(why, "no quote shows $5")
        imaging = answer(amount="$0", page=52, quotes=["no coinsurance, copayment, or deductible for flu vaccines"])
        self.assertEqual(len(extract.gate(DOC, "imaging", [imaging], pages, ok_unless_bad)[1]), 1)

    def test_rejects_both_copies_of_a_conflict(self):
        found, failed = gate(answer(), answer(quotes=["MRI and CT scans $250 copay"], amount="$250"))
        self.assertEqual(found, [])
        self.assertEqual([why for _, why in failed], ["two answers for one fact on one page"] * 2)

    def test_lists_check_failures_before_clashes(self):
        found, failed = gate(answer(), answer(amount="$5"), answer(quotes=["MRI and CT scans $250 copay"], amount="$250"))
        self.assertEqual([why for _, why in failed], ["no quote shows $5"] + ["two answers for one fact on one page"] * 2)

    def test_keeps_one_copy_of_a_repeat(self):
        self.assertEqual(len(gate(answer(), answer())[0]), 1)


class DocFactsTest(unittest.TestCase):
    def run_it(self, first, retry):
        return extract.doc_facts(DOC, "imaging", first, retry, PAGES, ok_unless_bad)[:2]

    def test_first_answers_ask_for_a_retry(self):
        found, failed = self.run_it([answer(), answer(amount="$5")], None)
        self.assertEqual((len(found), [why for _, why in failed]), (1, ["no quote shows $5"]))

    def test_retry_adds_fixes_and_ends_the_retries(self):
        fixed = answer(benefit="imaging.diagnostic.advanced", amount="$250", quotes=["MRI and CT scans $250 copay"])
        found, failed = self.run_it([answer(), answer(amount="$5")], [fixed, answer()])
        self.assertEqual(sorted(f["benefit"] for f in found), ["imaging.diagnostic.advanced", "imaging.xray"])
        self.assertEqual(failed, [])


class MergeTest(unittest.TestCase):
    def run_it(self, *answers):
        return extract.doc_facts(DOC, "imaging", list(answers), None, PAGES, ok_unless_bad, merge=True)[:2]

    def test_merges_answers_that_differ_only_in_quotes_and_notes(self):
        found, failed = self.run_it(answer(note="a"), answer(quotes=[X_RAYS, "MRI and CT scans $250 copay"], note="b"))
        self.assertEqual(failed, [])
        self.assertEqual([(json.loads(f["quotes"]), f["note"]) for f in found],
                         [([X_RAYS, "MRI and CT scans $250 copay"], "a b")])

    def test_still_rejects_answers_with_different_amounts(self):
        found, failed = self.run_it(answer(), answer(quotes=["MRI and CT scans $250 copay"], amount="$250"))
        self.assertEqual((found, [why for _, why in failed]), ([], [extract.CLASH] * 2))

    def test_merging_limits_drops_the_limits_that_differ(self):
        two = answer(note="a", limit="1 per year"), answer(note="b", limit="2 per year")
        self.assertEqual(self.run_it(*two)[0], [])
        found, failed = extract.doc_facts(DOC, "imaging", list(two), None, PAGES, ok_unless_bad, merge="limits")[:2]
        self.assertEqual((failed, [f["limit"] for f in found]), ([], [""]))

    def test_merging_limits_keeps_the_limits_of_a_cap(self):
        two = answer(cost_kind="max", note="a", limit="per year"), answer(cost_kind="max", note="b", limit="per visit")
        found, failed = extract.doc_facts(DOC, "imaging", list(two), None, PAGES, ok_unless_bad, merge="limits")[:2]
        self.assertEqual((found, [why for _, why in failed]), ([], [extract.CLASH] * 2))

    def test_merging_limits_keeps_a_shared_limit(self):
        found = extract.doc_facts(DOC, "imaging", [answer(note="a", limit="1 per year"), answer(note="b", limit="1 per year")],
                                  None, PAGES, ok_unless_bad, merge="limits")[0]
        self.assertEqual([f["limit"] for f in found], ["1 per year"])

    def test_merging_prices_drops_the_units_and_limits_that_differ(self):
        two = answer(note="a", unit="per visit", limit="1 per year"), answer(note="b", unit="per exam", limit="2 per year")
        self.assertEqual(extract.doc_facts(DOC, "imaging", list(two), None, PAGES, ok_unless_bad, merge="limits")[0], [])
        found, failed = extract.doc_facts(DOC, "imaging", list(two), None, PAGES, ok_unless_bad, merge="prices")[:2]
        self.assertEqual((failed, [(f["unit"], f["limit"]) for f in found]), ([], [("", "")]))

    def test_merging_prices_keeps_units_that_count_ears_or_pairs(self):
        two = answer(note="a", unit="per ear"), answer(note="b", unit="per pair")
        found, failed = extract.doc_facts(DOC, "imaging", list(two), None, PAGES, ok_unless_bad, merge="prices")[:2]
        self.assertEqual((found, [why for _, why in failed]), ([], [extract.CLASH] * 2))

    def test_merging_prices_still_rejects_different_amounts(self):
        two = answer(unit="per visit"), answer(quotes=["MRI and CT scans $250 copay"], amount="$250", unit="per exam")
        found, failed = extract.doc_facts(DOC, "imaging", list(two), None, PAGES, ok_unless_bad, merge="prices")[:2]
        self.assertEqual((found, [why for _, why in failed]), ([], [extract.CLASH] * 2))

    def test_without_merge_both_copies_clash(self):
        found, failed = extract.doc_facts(DOC, "imaging", [answer(note="a"), answer(note="b")], None, PAGES,
                                          ok_unless_bad)[:2]
        self.assertEqual((found, [why for _, why in failed]), ([], [extract.CLASH] * 2))


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

    def test_shows_the_pages_after_an_items_page_that_its_group_asks_for(self):
        items = [dict(gate(answer())[0][0], decoy=False)]
        self.assertIn("=====PAGE 62=====\nDental X-rays", extract.verifier_task(DOC, NAMES, PAGES, items, DATA, after={"imaging": 1}))
        self.assertNotIn("=====PAGE 62=====", extract.verifier_task(DOC, NAMES, PAGES, items, DATA, after={"dental": 1}))
        self.assertIn("=====PAGE 3=====\nIndex", extract.verifier_task(DOC, NAMES, PAGES, items, DATA, before={"imaging": 58}))
        last = [dict(items[0], page="62")]
        self.assertIn("=====PAGE 62=====", extract.verifier_task(DOC, NAMES, PAGES, last, DATA, after={"imaging": 1}))


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

    def known(self, **changes):
        row = {c: "" for c in facts.COLUMNS}
        row.update(plan_id="H1036-306-0", benefit="imaging.xray", setting="any", network="in", covered_by="medicare",
                   cost_kind="copay", amount="$0-$40", source="EOC", doc_sha=SHA, page="1", quotes=json.dumps([X_RAYS]))
        row.update(changes)
        return row

    def test_reread_shows_the_facts_found_and_asks_for_the_rest(self):
        with open(self.data / "generated" / "documents_checked.csv", "w") as f:
            f.write(f"plan_ids,kind,sha256\nH1036-306-0;H1036-307-0,EOC,{SHA}\n")
        found = self.known()
        other_doc = self.known(doc_sha="ef" * 32, amount="$9")
        other_plan = self.known(plan_id="H1036-307-0", amount="$7")
        self.step(extract.reread, self.work, self.dir, "imaging", plan_ids={"H1036-306-0"},
                  known=[found, other_doc, other_plan])
        self.assertEqual(os.listdir(self.dir), [f"{SHA[:16]}.md"])
        text = (self.dir / f"{SHA[:16]}.md").read_text()
        self.assertIn("Earlier readers found these facts for H1036-306-0:\n\n- "
                      + extract.printable(extract.shown(found)) + "\n\nEarlier readers may have missed", text)
        self.assertIn("only the facts for H1036-306-0 that the list lacks", text)
        self.assertNotIn("$9", text)
        self.assertNotIn("$7", text)
        self.assertLess(text.index("## Facts already found"), text.index("## Pages"))

    def test_a_tasks_notes_add_the_plan_notes_of_its_plans_only(self):
        plans = {"H1036-306-0"}
        notes = {"imaging": "Read this.", "dental": "Teeth."}
        self.assertEqual(extract.for_plans(notes, {}, plans), notes)
        self.assertEqual(extract.for_plans(notes, {"imaging": {"H0000-000-0": "No."}}, plans), notes)
        self.assertEqual(extract.for_plans(notes, {"imaging": {"H1036-306-0": "Mind page 2."}, "vision": {"H1036-306-0": "Eyes."}}, plans),
                         {"imaging": "Read this. Mind page 2.", "dental": "Teeth.", "vision": "Eyes."})

    def test_reread_says_when_no_facts_were_found(self):
        self.step(extract.reread, self.work, self.dir, "imaging", plan_ids={"H1036-306-0"}, known=[])
        text = (self.dir / f"{SHA[:16]}.md").read_text()
        self.assertIn("Earlier readers found no facts for H1036-306-0.\n\nEarlier readers may have missed", text)
        self.assertIn("only the facts for H1036-306-0 that the pages state", text)

    def test_verify_makes_decoys_from_known_facts_without_checking_them_again(self):
        with open(self.dir.parent / "new.json", "w") as f:
            json.dump([self.known(network="out", amount="$0", quotes=json.dumps(["Outpatient X-rays $0"]))], f)
        self.step(extract.verify, self.work, self.dir.parent / "new.json", self.dir, known=[self.known()])
        items = json.loads((self.dir / "items.json").read_text())
        self.assertEqual([c["network"] for c in items if not c["decoy"]], ["out"])
        self.assertTrue(any(c["decoy"] for c in items))

    def test_reread_skips_documents_for_other_plans(self):
        self.step(extract.reread, self.work, self.dir, "imaging", plan_ids={"H0000-000-0"}, known=[])
        self.assertEqual(os.listdir(self.dir), [])

    def test_facts_retries_once_then_verify_writes_tasks_and_items(self):
        self.step(extract.read, self.work, self.dir, "imaging")
        good, bad = answer(page=1), answer(page=1, amount="$5")
        (self.dir / f"{SHA[:16]}.json").write_text(json.dumps([good, bad, "text", answer(page=1, plan_id=["a", "b"])]))
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

    def test_facts_records_each_answers_outcome(self):
        self.step(extract.read, self.work, self.dir, "imaging")
        good, bad = answer(page=1), answer(page=1, amount="$5")
        (self.dir / f"{SHA[:16]}.json").write_text(json.dumps([good, bad]))
        out = self.dir / "facts.json"
        self.step(extract.extract_facts, self.work, self.dir, "imaging", out)
        (self.dir / f"{SHA[:16]}.retry.json").write_text(json.dumps([good]))
        self.step(extract.extract_facts, self.work, self.dir, "imaging", out)
        (found,) = json.loads(out.read_text())
        prompt, retry = (ask.sha((self.dir / f"{SHA[:16]}{end}").read_text()) for end in (".md", ".retry.md"))
        self.assertEqual(json.loads((self.dir / extract.OUTCOMES).read_text()), [
            dict(prompt=prompt, item=0, doc_sha=SHA, stated=good, problem=None, fact=extract.named(found)),
            dict(prompt=prompt, item=1, doc_sha=SHA, stated=bad, problem="no quote shows $5", fact=None),
            dict(prompt=retry, item=0, doc_sha=SHA, stated=good, problem=None, fact=extract.named(found))])

    def test_numbers_each_verdict_within_its_task(self):
        items = [dict(answer(), page="1", quotes="[]", fact_id="a", source="EOC", doc_sha=SHA, task=t, decoy=False)
                 for t in ("x", "y", "x")]
        got = extract.outcomes(str(self.dir), items, [dict(id=2, ok=True)])
        self.assertEqual([(o["item"], o["ok"]) for o in got], [(0, None), (0, None), (1, True)])

    def test_accept_records_each_verdict(self):
        new = self.known(network="out", amount="$0", quotes=json.dumps(["Outpatient X-rays $0"]))
        with open(self.dir.parent / "new.json", "w") as f:
            json.dump([dict(new, fact_id=facts.fact_id(new))], f)
        self.step(extract.verify, self.work, self.dir.parent / "new.json", self.dir, known=[self.known()])
        items = json.loads((self.dir / "items.json").read_text())
        real = next(n for n, c in enumerate(items) if not c["decoy"])
        (self.dir / f"v-{SHA[:16]}.json").write_text(json.dumps(
            [{"id": n, "ok": n == real, "reason": f"r{n}"} for n in range(len(items) - 1)]))
        with contextlib.redirect_stdout(io.StringIO()):
            extract.accept(str(self.dir), str(self.dir / "accepted.csv"))
        prompt = ask.sha((self.dir / f"v-{SHA[:16]}.md").read_text())
        self.assertEqual(json.loads((self.dir / extract.OUTCOMES).read_text()), [
            dict(prompt=prompt, item=n, decoy=c["decoy"], shown=extract.shown(c),
                 fact=None if c["decoy"] else extract.named(c),
                 ok=n == real if n < len(items) - 1 else None, reason=f"r{n}" if n < len(items) - 1 else "")
            for n, c in enumerate(items)])


class VerdictsTest(unittest.TestCase):
    def test_numbers_counts_every_number(self):
        self.assertEqual(extract.numbers("$0/$0; days 1-5; tiers 1,2; 1,000 rides; 0%"),
                         {"$0": 3, "1": 2, "5": 1, "2": 1, "1000": 1})

    def test_verdicts_count_ids_within_each_task_and_drop_bad_ones(self):
        items = [{"task": "A"}, {"task": "B"}, {"task": "A"}]
        with tempfile.TemporaryDirectory() as d:
            pathlib.Path(d, "v-A.json").write_text(json.dumps([{"id": 1, "ok": True}, {"id": 2, "ok": True}, {"ok": True}]))
            pathlib.Path(d, "v-B.json").write_text(json.dumps([{"id": 0, "ok": False}, {"id": "0", "ok": True}]))
            self.assertEqual(extract.verdicts(items, d), [{"id": 2, "ok": True}, {"id": 1, "ok": False}])
            self.assertEqual(extract.missing_verdicts(items, extract.verdicts(items, d)), [0])

    def test_accepted_keeps_items_every_verdict_accepts(self):
        items = [dict(n=0, decoy=False, task="A"), dict(n=1, decoy=True, task="A"), dict(n=2, decoy=False, task="A")]
        verdicts = [{"id": 0, "ok": True}, {"id": 1, "ok": False}, {"id": 2, "ok": True}, {"id": 2, "ok": "yes"}]
        self.assertEqual(extract.accepted(items, verdicts), [{"n": 0}])

    def test_accepted_fails_when_a_decoy_is_accepted(self):
        with self.assertRaises(SystemExit):
            extract.accepted([dict(n=0, decoy=True)], [{"id": 0, "ok": True}])


if __name__ == "__main__":
    unittest.main()
