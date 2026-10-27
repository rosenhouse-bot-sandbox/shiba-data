import contextlib, csv, io, json, os, pathlib, random, shutil, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import filled
from eoc import DATA, eoc

PLAN = "H2056-003-0"


def cite(page, quote):
    return {"page": page, "quote": quote}


def ok_unless_bad(page, quote):
    return "bad" not in quote


def fake_work(root, plan, page_text):
    """A texts.py work directory whose EOC for the plan has one page, read as running text."""
    work = pathlib.Path(root, "work")
    for sub in ("text", "layout", "items"):
        (work / sub).mkdir(parents=True, exist_ok=True)
    doc = eoc(plan)[0]
    for sub in ("text", "layout"):
        (work / sub / f"{doc}.txt").write_text(f"=====PAGE 1=====\n{page_text}\n")
    (work / "items" / f"{doc}.json").write_text(json.dumps({"1": {"strs": [page_text], "lefts": [0]}}))
    return work


def quiet(f, *args):
    with contextlib.redirect_stdout(io.StringIO()):
        return f(*args)


class MoneyTest(unittest.TestCase):
    def test_reads_amounts_and_percentages_with_zero_percent_as_zero_dollars(self):
        self.assertEqual(filled.money("max $1,500.00/year; COMP 20.0%; PREV 0%; 3 visits; $12.50"),
                         {"$1500", "20%", "$0", "$12.50"})

    def test_numbers_counts_every_number(self):
        self.assertEqual(filled.numbers("$0/$0; days 1-5; tiers 1,2; 1,000 rides"),
                         {"$0": 2, "1": 2, "5": 1, "2": 1, "1000": 1})


class TargetsTest(unittest.TestCase):
    site = {
        "docs": {"s": {"kind": "SB"}, "e": {"kind": "EOC"}},
        "main": {"rows": [{"plan_id": "A", "cells": {
            "G_specialist": {"value": "$40", "cites": [{"doc": "s"}]},
            "F_primary_care": {"value": "$0", "cites": [{"doc": "e"}]},
            "V_massage": {"value": "●", "cites": []},
            "D_premium_full_extra_help": {"value": "$10", "cites": []},
            "W_fitness": {"value": "", "cites": []}}}]},
        "dvha": {"rows": [{"plan_id": "A", "cells": {"J_extra_benefits": {"value": "Fitness; Meals", "cites": []}}}]},
    }

    def test_lists_checkable_cells_that_no_eoc_cites(self):
        self.assertEqual(filled.targets(self.site), {"A": {"main.G_specialist": "$40", "main.V_massage": "●"}})

    def test_every_includes_eoc_cited_cells(self):
        self.assertEqual(filled.targets(self.site, every=True)["A"],
                         {"main.G_specialist": "$40", "main.F_primary_care": "$0", "main.V_massage": "●"})


class PassagesTest(unittest.TestCase):
    def test_keeps_passages_that_show_one_of_the_amounts(self):
        layout = {1: "Specialist visit $40 copay", 2: "Specialist referral rules", 3: "Specialist $45"}
        self.assertEqual(filled.passages(layout, "main.G_specialist", "$40 | $45"),
                         "=====PAGE 1=====\nSpecialist visit $40 copay\n---\n=====PAGE 3=====\nSpecialist $45\n---")

    def test_keeps_every_passage_for_a_dot(self):
        self.assertIn("PAGE 2", filled.passages({2: "Massage therapy"}, "main.V_massage", "●"))


class ProblemTest(unittest.TestCase):
    def test_none_when_the_quotes_pass_and_show_every_amount(self):
        cites = [cite(4, "Specialist $0 copay"), cite(5, "Specialist visits 20% coinsurance")]
        self.assertIsNone(filled.problem("main.G_specialist", "$0-20%", cites, ok_unless_bad))

    def test_names_quotes_that_fail_the_check(self):
        got = filled.problem("main.G_specialist", "$40", [cite(4, "$40 copay"), cite(5, "bad $40")], ok_unless_bad)
        self.assertEqual(got, 'not found exactly once on its page as running text or down one column: page 5 "bad $40"')

    def test_names_amounts_no_quote_shows(self):
        got = filled.problem("main.G_specialist", "$40 | $80", [cite(4, "$40 copay")], ok_unless_bad)
        self.assertEqual(got, "no quote shows $80")

    def test_quotes_show_each_number_as_often_as_the_value(self):
        def why(key, value, *quotes):
            return filled.problem(key, value, [cite(4, q) for q in quotes], ok_unless_bad)

        self.assertEqual(why("main.H_inpatient", "$395 | 1-5", "$395 per day for days 1-7"), "no quote shows 5")
        self.assertEqual(why("main.K_tests_labs", "$0/$0", "$0 copay for lab services"), "no quote shows $0 2 times")
        self.assertIsNone(why("main.K_tests_labs", "$0/$0", "$0 copay for lab services", "$0 copay for diagnostic tests"))

    def test_a_dot_needs_a_quote_that_names_the_benefit_as_covered_routine_care(self):
        why = "no quote names the benefit without saying it is excluded, Medicare-covered or optional"
        for dot in filled.DOTS:
            for quote in ("Covered", "Routine dental care is not covered.", "Medicare-covered dental services",
                          "Optional supplemental dental package"):
                self.assertEqual(filled.problem("main.R_dental", dot, [cite(4, quote)], ok_unless_bad), why, quote)
            for quote in ("Routine dental cleanings", "non-Medicare covered routine dental services",
                          "Dental care not covered by Original Medicare, up to 2 visits a year"):
                self.assertIsNone(filled.problem("main.R_dental", dot, [cite(4, "Covered"), cite(5, quote)], ok_unless_bad), quote)

    def test_needs_a_quote(self):
        self.assertEqual(filled.problem("main.V_massage", "●", [], ok_unless_bad), "no quotes")


class GateTest(unittest.TestCase):
    def test_splits_cite_answers_into_claims_and_failures(self):
        values = {"main.G_specialist": "$40", "main.F_primary_care": "$0", "main.V_massage": "●"}
        answers = [
            {"key": "main.G_specialist", "result": "cite", "citations": [{"page": "4", "quote": "Specialist $40"}]},
            {"key": "main.V_massage", "result": "cite", "citations": [{"page": 6, "quote": "bad massage"}]},
            {"key": "main.W_fitness", "result": "cite", "citations": [{"page": 6, "quote": "Fitness"}]},
            {"key": "main.F_primary_care", "result": "skip"},
        ]
        claims, failed = filled.gate(PLAN, values, answers, ok_unless_bad)
        self.assertEqual(claims, [{"plan": PLAN, "key": "main.G_specialist", "value": "$40",
                                   "citations": [cite(4, "Specialist $40")]}])
        self.assertEqual(failed, {"main.V_massage": ([cite(6, "bad massage")],
                                                     'not found exactly once on its page as running text or down one column: page 6 "bad massage"')})

    def test_ignores_a_cell_answered_twice(self):
        answer = {"key": "main.G_specialist", "result": "cite", "citations": [cite(4, "Specialist $40")]}
        self.assertEqual(filled.gate(PLAN, {"main.G_specialist": "$40"}, [answer, answer], ok_unless_bad), ([], {}))

    def test_fails_a_citation_without_one_page_number_and_a_quote(self):
        for bad in ({"page": "4-5", "quote": "Specialist $40"}, {"page": 4, "quote": None}, {"page": 4}):
            answers = [{"key": "main.G_specialist", "result": "cite", "citations": [bad]}]
            self.assertEqual(filled.gate(PLAN, {"main.G_specialist": "$40"}, answers, ok_unless_bad),
                             ([], {"main.G_specialist": ([bad], "each citation needs one page number and a quote")}))


class AnswersTest(unittest.TestCase):
    def test_retry_answers_replace_first_answers(self):
        with tempfile.TemporaryDirectory() as d:
            pathlib.Path(d, f"a-{PLAN}.json").write_text(json.dumps([{"key": "a", "result": "cite"}, {"key": "b"}]))
            self.assertEqual(filled.answers(d, PLAN), [{"key": "a", "result": "cite"}, {"key": "b"}])
            pathlib.Path(d, f"r-{PLAN}.json").write_text(json.dumps([{"key": "a", "result": "skip"}]))
            self.assertEqual(filled.answers(d, PLAN), [{"key": "a", "result": "skip"}, {"key": "b"}])


class ClaimsTest(unittest.TestCase):
    def test_keeps_passing_answers_and_writes_one_retry_round(self):
        values = filled.targets(filled.build.site_data(DATA), every=True)
        plan, (one, two) = next((p, [(k, v) for k, v in sorted(c.items()) if filled.money(v)][:2])
                                for p, c in sorted(values.items()) if sum(bool(filled.money(v)) for v in c.values()) > 1)
        quote = f"Cell one {one[1]}"
        with tempfile.TemporaryDirectory() as tmp:
            work, answers = fake_work(tmp, plan, quote), pathlib.Path(tmp, "answers")
            answers.mkdir()
            (answers / f"a-{plan}.json").write_text(json.dumps([
                {"key": one[0], "result": "cite", "citations": [cite(1, quote)]},
                {"key": two[0], "result": "cite", "citations": [cite(1, "Missing text")]}]))

            def run():
                quiet(filled.claims, str(work), str(answers), str(answers / "claims.json"))
                return [c["key"] for c in filled.load(answers / "claims.json")]

            self.assertEqual(run(), [one[0]])
            retry = (answers / f"{plan}.retry.md").read_text()
            self.assertEqual(retry.count("\n### "), 1)
            self.assertIn(f"### {two[0]}", retry)
            self.assertIn(f"{answers}/r-{plan}.json", retry)
            self.assertIn('Earlier quotes: [{"page": 1, "quote": "Missing text"}]', retry)
            (answers / f"{plan}.retry.md").unlink()
            (answers / f"r-{plan}.json").write_text(json.dumps([
                {"key": two[0], "result": "cite", "citations": [cite(1, "Still missing")]}]))
            self.assertEqual(run(), [one[0]])
            self.assertFalse((answers / f"{plan}.retry.md").exists())


class BundleTest(unittest.TestCase):
    def test_writes_one_task_per_plan_for_the_cells_asked_for(self):
        for every, want in (("", False), ("every", True)):
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(filled, "targets", return_value={PLAN: {"main.G_specialist": "$40"}}) as targets:
                filled.bundle(str(fake_work(tmp, PLAN, "Specialist $40")), f"{tmp}/out", every)
                self.assertEqual(targets.call_args.args[1], want)
                task = pathlib.Path(tmp, "out", f"{PLAN}.md").read_text()
            self.assertIn(f"({PLAN}), plan year {filled.years.config(DATA)['year']}.", task)
            self.assertIn(f"{tmp}/out/a-{PLAN}.json", task)
            self.assertIn("### main.G_specialist", task)

    def test_refuses_an_unknown_mode(self):
        with self.assertRaises(SystemExit):
            filled.bundle("work", "out", "all")


class SectionTest(unittest.TestCase):
    def test_shows_the_value_and_any_earlier_failure(self):
        layout = {3: "Massage therapy"}
        first = filled.section("main.V_massage", "●", layout)
        self.assertIn("Value: `●`", first)
        self.assertNotIn("Earlier", first)
        again = filled.section("main.V_massage", "●", layout, ([cite(3, "Massage")], "no quote names the benefit"))
        self.assertIn('Earlier quotes: [{"page": 3, "quote": "Massage"}]. They failed the check: no quote names the benefit.',
                      again)


class FillTest(unittest.TestCase):
    def test_fills_every_placeholder(self):
        for template in ("filled_prompt.md", "vfilled_prompt.md"):
            text = filled.fill(template, PLAN_NAME="VALUE", PLAN_ID="VALUE", YEAR="VALUE", ANSWER="VALUE")
            self.assertNotRegex(text, r"\{[A-Z_]+\}")


class DecoysTest(unittest.TestCase):
    claims = [{"plan": PLAN, "key": "main.G_specialist", "value": "$40", "citations": [cite(1, "Specialist $40")]},
              {"plan": PLAN, "key": "main.F_primary_care", "value": "$0", "citations": [cite(2, "Primary care $0")]},
              {"plan": PLAN, "key": "main.K_tests_labs", "value": "$0/$0", "citations": [cite(3, "$0 lab"), cite(3, "$0 tests")]},
              {"plan": PLAN, "key": "main.I_outpatient_surgery", "value": "$0",
               "citations": [cite(4, "Outpatient surgery and primary care $0")]},
              {"plan": PLAN, "key": "main.J_outpatient_rehab", "value": "$0", "citations": [cite(5, "$0 copay")]},
              {"plan": PLAN, "key": "dvha.H_hearing", "value": "exam $0", "citations": [cite(5, "Routine hearing exam $0")]},
              {"plan": PLAN, "key": "main.V_massage", "value": "●", "citations": [cite(6, "Massage therapy")]}]

    def test_moves_a_cell_with_quotes_that_name_its_benefit_to_a_field_of_its_sheet_they_do_not_name(self):
        moves = set()
        for seed in range(50):
            got = filled.decoys(self.claims, random.Random(seed))
            self.assertEqual(len(got), 3)
            for d in got:
                source = next(c for c in self.claims if c["citations"] == d["citations"])
                moves.add((source["key"], d["key"]))
                self.assertEqual(d["plan"], PLAN)
                self.assertEqual(d["value"], source["value"])
                self.assertIsNone(filled.problem(d["key"], d["value"], d["citations"], ok_unless_bad))
        sources = ("main.G_specialist", "main.F_primary_care", "main.K_tests_labs", "main.I_outpatient_surgery")
        self.assertEqual(moves, {(a, b) for a in sources for b in sources + ("main.J_outpatient_rehab",) if a != b}
                         - {("main.I_outpatient_surgery", "main.F_primary_care")})


class VerifyTest(unittest.TestCase):
    def test_writes_shuffled_tasks_with_decoys_the_verifier_cannot_tell_apart(self):
        other = "H3805-048-0"
        quotes = ["Specialist $40", "Primary care $0", "Hearing aids $500"]
        found = [{"plan": p, "key": k, "value": v, "citations": [cite(1, q)]} for p in (PLAN, other)
                 for k, v, q in zip(("main.G_specialist", "main.F_primary_care", "main.Q_hearing"), ("$40", "$0", "●"), quotes)]
        with tempfile.TemporaryDirectory() as tmp:
            for plan in (PLAN, other):
                work = fake_work(tmp, plan, "\n".join(quotes))
            pathlib.Path(tmp, "claims.json").write_text(json.dumps(found))
            quiet(filled.verify, str(work), f"{tmp}/claims.json", f"{tmp}/v")
            items = filled.load(f"{tmp}/v/items.json")
            tasks = {p: pathlib.Path(tmp, "v", f"v-{p}.md").read_text() for p in (PLAN, other)}
        self.assertEqual(len(items), 10)
        orders = []
        for plan, task in tasks.items():
            mine = [i for i, c in enumerate(items) if c["plan"] == plan]
            self.assertEqual([c["decoy"] for c in items[mine[0]:mine[-1] + 1]].count(True), 2)
            orders.append([items[i]["decoy"] for i in mine])
            shown = [json.loads(line) for line in task.splitlines() if line.startswith("{")]
            self.assertEqual([s["id"] for s in shown], mine)
            self.assertEqual([{k: s[k] for k in ("value", "citations")} for s in shown],
                             [{k: items[i][k] for k in ("value", "citations")} for i in mine])
            self.assertTrue(all(set(s) == {"id", "field", "meaning", "value", "citations"} for s in shown))
            self.assertIn(f"=====PAGE 1=====\n{quotes[0]}", task)
            self.assertIn(f"{tmp}/v/ans-{plan}.json", task)
            self.assertIn(f"plan year {filled.years.config(DATA)['year']}.", task)
        self.assertNotEqual(orders, [[False] * 3 + [True] * 2] * 2)


class AcceptedTest(unittest.TestCase):
    claim = {"plan": PLAN, "key": "main.G_specialist", "value": "$40", "citations": [cite(1, "$40")]}

    def test_keeps_claims_every_verdict_accepts(self):
        items = [dict(self.claim, decoy=False), dict(self.claim, value="$50", decoy=True), dict(self.claim, decoy=False)]
        verdicts = [{"id": 0, "ok": True}, {"id": 1, "ok": False}, {"id": 2, "ok": True}, {"id": 2, "ok": "yes"}]
        self.assertEqual(filled.accepted(items, verdicts), [self.claim])

    def test_fails_when_a_decoy_is_accepted(self):
        with self.assertRaises(SystemExit):
            filled.accepted([dict(self.claim, decoy=True)], [{"id": 0, "ok": True}])

    def test_fails_when_a_verdict_is_missing(self):
        with self.assertRaises(SystemExit):
            filled.accepted([dict(self.claim, decoy=False)] * 2, [{"id": 0, "ok": True}])

    def test_accept_reads_every_verifier_answer(self):
        with tempfile.TemporaryDirectory() as d:
            pathlib.Path(d, "items.json").write_text(json.dumps([dict(self.claim, decoy=False)] * 2))
            pathlib.Path(d, "ans-A.json").write_text(json.dumps([{"id": 0, "ok": True}]))
            pathlib.Path(d, "ans-B.json").write_text(json.dumps([{"id": 1, "ok": True}]))
            quiet(filled.accept, d, f"{d}/accepted.json")
            self.assertEqual(filled.load(f"{d}/accepted.json"), [self.claim, self.claim])


class LeadTest(unittest.TestCase):
    def test_puts_quotes_with_amounts_other_than_zero_first(self):
        cites = [cite(1, "$0 for labs"), cite(2, "Specialist"), cite(3, "$40 copay")]
        self.assertEqual(filled.lead("main.G_specialist", "$0-$40", cites),
                         [cite(3, "$40 copay"), cite(1, "$0 for labs"), cite(2, "Specialist")])

    def test_puts_quotes_that_name_the_benefit_first_for_a_dot(self):
        cites = [cite(1, "Covered"), cite(2, "Massage therapy")]
        self.assertEqual(filled.lead("main.V_massage", "●", cites), [cite(2, "Massage therapy"), cite(1, "Covered")])


class PublishTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = pathlib.Path(tmp.name) / DATA.name
        shutil.copytree(DATA, self.data)
        targets = filled.targets(filled.build.site_data(self.data))
        self.plan, cells = next((p, c) for p, c in targets.items() if any(filled.money(v) for v in c.values()))
        self.key, self.value = next((k, v) for k, v in cells.items() if filled.money(v))

    def accepted(self, value):
        path = self.data / "accepted.json"
        path.write_text(json.dumps([{"plan": self.plan, "key": self.key, "value": value,
                                     "citations": [cite(7, "no amount"), cite(8, f"pay {self.value}, then")]}]))
        return path

    def test_appends_every_quote_with_those_that_show_the_value_first(self):
        filled.publish(self.accepted(self.value), data=self.data)
        self.assertTrue((self.data / "machine/eoc_citations.csv").read_bytes().endswith(b"no amount\r\n"))
        rows = list(csv.DictReader(open(self.data / "machine/eoc_citations.csv")))[-2:]
        sheet, column = self.key.split(".")
        prompt = filled.blanks.prompt_version("filled_prompt.md", "vfilled_prompt.md")
        self.assertEqual([(r["step"], r["prompt"], r["sheet"], r["plan_id"], r["column"], r["line"], r["value"], r["pdf_page"])
                          for r in rows], [("filled", prompt, sheet, self.plan, column, "", self.value, page) for page in ("8", "7")])
        self.assertNotIn(self.key, filled.targets(filled.build.site_data(self.data)).get(self.plan, {}))

    def test_refuses_a_cell_whose_value_changed_or_that_an_eoc_now_cites(self):
        with self.assertRaises(SystemExit):
            filled.publish(self.accepted(self.value + "0"), data=self.data)
        filled.publish(self.accepted(self.value), data=self.data)
        with self.assertRaises(SystemExit):
            filled.publish(self.accepted(self.value), data=self.data)

    def test_writes_rows_to_another_file_even_for_cells_an_eoc_cites(self):
        out = self.data / "machine.csv"
        filled.publish(self.accepted(self.value), data=self.data)
        before = (self.data / "machine/eoc_citations.csv").read_bytes()
        filled.publish(self.accepted(self.value), out, data=self.data)
        filled.publish(self.accepted(self.value), out, data=self.data)
        rows = list(csv.DictReader(open(out)))
        self.assertEqual([(r["plan_id"], r["value"], r["quote"]) for r in rows],
                         [(self.plan, self.value, f"pay {self.value}, then"), (self.plan, self.value, "no amount")])
        self.assertEqual((self.data / "machine/eoc_citations.csv").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
