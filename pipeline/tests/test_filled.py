import contextlib, csv, io, json, os, pathlib, random, shutil, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import filled
from eoc import DATA, eoc

PLAN = "H2056-003-0"


def cite(page, quote):
    return {"page": page, "quote": quote}


def ok_unless_bad(page, quote):
    return "bad" not in quote


class MoneyTest(unittest.TestCase):
    def test_reads_amounts_and_percentages_with_zero_percent_as_zero_dollars(self):
        self.assertEqual(filled.money("max $1,500.00/year; COMP 20%; PREV 0%; 3 visits; $12.50"),
                         {"$1500", "20%", "$0", "$12.50"})


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
        self.assertEqual(got, 'not once on its page as running text or down one column: page 5 "bad $40"')

    def test_names_amounts_no_quote_shows(self):
        got = filled.problem("main.G_specialist", "$40 | $80", [cite(4, "$40 copay")], ok_unless_bad)
        self.assertEqual(got, "no quote shows $80")

    def test_a_dot_needs_a_quote_that_names_the_benefit(self):
        self.assertEqual(filled.problem("main.V_massage", "●", [cite(4, "Covered")], ok_unless_bad),
                         "no quote names the benefit")
        self.assertIsNone(filled.problem("main.V_massage", "●", [cite(4, "Massage therapy covered")], ok_unless_bad))

    def test_needs_a_quote(self):
        self.assertEqual(filled.problem("main.V_massage", "●", [], ok_unless_bad), "no quotes")


class GateTest(unittest.TestCase):
    def test_splits_cite_answers_into_claims_and_failures(self):
        values = {"main.G_specialist": "$40", "main.V_massage": "●"}
        answers = [
            {"key": "main.G_specialist", "result": "cite", "citations": [{"page": "4", "quote": "Specialist $40"}]},
            {"key": "main.V_massage", "result": "cite", "citations": [{"page": 6, "quote": "bad massage"}]},
            {"key": "main.W_fitness", "result": "cite", "citations": [{"page": 6, "quote": "Fitness"}]},
            {"key": "main.G_specialist", "result": "skip"},
        ]
        claims, failed = filled.gate(PLAN, values, answers, ok_unless_bad)
        self.assertEqual(claims, [{"plan": PLAN, "key": "main.G_specialist", "value": "$40",
                                   "citations": [cite(4, "Specialist $40")]}])
        self.assertEqual(failed, {"main.V_massage": ([cite(6, "bad massage")],
                                                     'not once on its page as running text or down one column: page 6 "bad massage"')})


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
            work, answers = pathlib.Path(tmp, "work"), pathlib.Path(tmp, "answers")
            for sub in ("text", "layout", "items", "answers"):
                (work / sub).mkdir(parents=True)
            answers.mkdir()
            doc = eoc(plan)[0]
            for sub in ("text", "layout"):
                (work / sub / f"{doc}.txt").write_text(f"=====PAGE 1=====\n{quote}\n")
            (work / "items" / f"{doc}.json").write_text(json.dumps({"1": {"strs": [quote], "lefts": [0]}}))
            (answers / f"a-{plan}.json").write_text(json.dumps([
                {"key": one[0], "result": "cite", "citations": [cite(1, quote)]},
                {"key": two[0], "result": "cite", "citations": [cite(1, "Missing text")]}]))

            def run():
                with contextlib.redirect_stdout(io.StringIO()):
                    filled.claims(str(work), str(answers), str(answers / "claims.json"))
                return [c["key"] for c in filled.load(answers / "claims.json")]

            self.assertEqual(run(), [one[0]])
            retry = (answers / f"{plan}.retry.md").read_text()
            self.assertEqual(retry.count("\n### "), 1)
            self.assertIn(f"### {two[0]}", retry)
            self.assertIn(f"{answers}/r-{plan}.json", retry)
            (answers / f"{plan}.retry.md").unlink()
            (answers / f"r-{plan}.json").write_text(json.dumps([
                {"key": two[0], "result": "cite", "citations": [cite(1, "Still missing")]}]))
            self.assertEqual(run(), [one[0]])
            self.assertFalse((answers / f"{plan}.retry.md").exists())


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
    def test_bump_raises_the_first_amount(self):
        self.assertEqual(filled.bump("$1,990 | $40"), "$2,000 | $40")
        self.assertEqual(filled.bump("PREV 0%; COMP 50%"), "PREV 10%; COMP 50%")
        self.assertIsNone(filled.bump("●"))

    def test_bumps_two_values_and_gives_a_cell_another_cells_quotes(self):
        claims = [{"key": "main.G_specialist", "value": "$40", "citations": [cite(1, "a")]},
                  {"key": "main.F_primary_care", "value": "$0", "citations": [cite(2, "b")]},
                  {"key": "main.V_massage", "value": "●", "citations": [cite(3, "c")]}]
        got = filled.decoys(claims, random.Random(1))
        self.assertEqual(sorted(d["value"] for d in got[:2]), ["$10", "$50"])
        self.assertEqual(len(got), 3)
        swapped = got[2]
        self.assertNotEqual(swapped["citations"], next(c for c in claims if c["key"] == swapped["key"])["citations"])

    def test_swaps_only_main_sheet_amounts_with_different_quotes(self):
        claims = [{"key": "main.G_specialist", "value": "$40", "citations": [cite(1, "a")]},
                  {"key": "main.K_tests_labs", "value": "$0/$0", "citations": [cite(1, "a")]},
                  {"key": "dvha.F_dental", "value": "PREV $0", "citations": [cite(2, "b")]},
                  {"key": "main.R_dental", "value": "●", "citations": [cite(3, "c")]}]
        for seed in range(5):
            got = filled.decoys(claims, random.Random(seed))
            self.assertEqual(len(got), 2)
            self.assertTrue(all(d["value"] != c["value"] for d in got for c in claims if c["key"] == d["key"]))


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


class LeadTest(unittest.TestCase):
    def test_puts_quotes_with_amounts_other_than_zero_first_and_drops_quotes_without_amounts(self):
        cites = [cite(1, "$0 for labs"), cite(2, "Specialist"), cite(3, "$40 copay")]
        self.assertEqual(filled.lead("main.G_specialist", "$0-$40", cites), [cite(3, "$40 copay"), cite(1, "$0 for labs")])

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

    def test_appends_the_quotes_that_show_the_value(self):
        filled.publish(self.accepted(self.value), data=self.data)
        self.assertTrue((self.data / "eoc_citations.csv").read_bytes().endswith(f'"pay {self.value}, then"\r\n'.encode()))
        last = list(csv.DictReader(open(self.data / "eoc_citations.csv")))[-1]
        sheet, column = self.key.split(".")
        self.assertEqual((last["sheet"], last["plan_id"], last["column"], last["value"], last["pdf_page"]),
                         (sheet, self.plan, column, self.value, "8"))
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
        before = (self.data / "eoc_citations.csv").read_bytes()
        filled.publish(self.accepted(self.value), out, data=self.data)
        filled.publish(self.accepted(self.value), out, data=self.data)
        rows = list(csv.DictReader(open(out)))
        self.assertEqual([(r["plan_id"], r["value"], r["quote"]) for r in rows], [(self.plan, self.value, f"pay {self.value}, then")])
        self.assertEqual((self.data / "eoc_citations.csv").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
