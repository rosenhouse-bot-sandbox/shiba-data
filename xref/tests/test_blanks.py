import csv, json, os, pathlib, shutil, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import blanks
from eoc import DATA, Doc

PLAN = "H2056-003-0"
QUOTE = "Naturopath services Not covered under any condition"


class Stub:
    def __init__(self, id, flow, ok=True):
        self.id, self.flow, self.ok = id, flow, ok

    def quote_ok(self, page, quote):
        return self.ok


class SnippetsTest(unittest.TestCase):
    def test_merges_nearby_hits_and_splits_distant_ones(self):
        lines = [f"line {i}" for i in range(40)]
        lines[5] = lines[10] = lines[35] = "massage"
        got = blanks.snippets({3: "\n".join(lines)}, ["massage"])
        self.assertEqual([(p, s.split("\n")[0], s.split("\n")[-1]) for p, s in got],
                         [(3, "line 1", "line 18"), (3, "line 31", "line 39")])

    def test_passages_say_when_nothing_mentions_the_benefit(self):
        self.assertEqual(blanks.passages({1: "nothing here"}, "main.V_massage"), "(No passage mentions it.)")


class GateClaimsTest(unittest.TestCase):
    def test_keeps_claims_whose_quotes_all_pass(self):
        answers = [
            {"key": "main.U_naturopath", "result": "excluded", "citations": [{"page": "5", "quote": "good"}]},
            {"key": "main.V_massage", "result": "excluded", "citations": [{"page": 5, "quote": "good"}, {"page": 6, "quote": "bad"}]},
            {"key": "main.V_massage", "result": "medicare_only", "citations": [{"page": 5, "quote": "good"}]},
            {"key": "main.X_transportation", "result": "unclear", "citations": [{"page": 5, "quote": "good"}]},
            {"key": "main.T_chiropractic", "result": "medicare_only", "citations": []},
        ]
        got = blanks.gate_claims(PLAN, answers, lambda page, quote: quote == "good")
        self.assertEqual(got, [{"plan": PLAN, "key": "main.U_naturopath", "claim": "excluded",
                                "citations": [{"page": 5, "quote": "good"}]}])


class DecoysTest(unittest.TestCase):
    claim = {"plan": PLAN, "key": "main.U_naturopath", "claim": "excluded", "citations": [{"page": 9, "quote": QUOTE}]}

    def test_moves_a_claim_onto_a_plan_that_fills_the_cell(self):
        docs = {PLAN: Stub("a", {}), "B": Stub("a", {2: QUOTE}), "C": Stub("c", {1: "x", 4: f"y {QUOTE} z"})}
        got = blanks.decoys([self.claim], {"main.U_naturopath": ["B", "C"]}, docs.get)
        self.assertEqual(got, [dict(self.claim, plan="C", citations=[{"page": 4, "quote": QUOTE}], decoy=True)])

    def test_needs_the_quote_once_and_highlighted(self):
        docs = {PLAN: Stub("a", {}), "B": Stub("b", {2: QUOTE, 3: QUOTE}), "C": Stub("c", {4: QUOTE}, ok=False)}
        self.assertEqual(blanks.decoys([self.claim], {"main.U_naturopath": ["B", "C"]}, docs.get), [])


class ExclusionTest(unittest.TestCase):
    def test_states_exclusion_needs_the_benefit_and_an_unconditional_negation(self):
        self.assertTrue(blanks.states_exclusion("main.V_massage", "Therapeutic massage Not covered under any condition"))
        self.assertFalse(blanks.states_exclusion("main.V_massage", "Therapeutic massage"))
        self.assertFalse(blanks.states_exclusion("main.V_massage", "Not covered under any condition"))
        self.assertFalse(blanks.states_exclusion("main.V_massage", "massage is not covered if ordered by a chiropractor"))

    def test_completes_a_bare_exclusion_row_and_drops_other_quotes(self):
        cites = [{"page": 4, "quote": "Therapeutic massage"}, {"page": 5, "quote": "Not covered under any condition Shoes"}]
        got = blanks.exclusion_cites("main.V_massage", cites, lambda page, q: q.endswith("condition."))
        self.assertEqual(got, [{"page": 4, "quote": "Therapeutic massage Not covered under any condition."}])

    def test_accepted_rejects_a_run_that_passes_a_decoy(self):
        items = [dict(DecoysTest.claim, decoy=True)]
        with self.assertRaises(SystemExit):
            blanks.accepted(items, [{"id": 0, "ok": True}], lambda plan: None)

    def test_accepted_keeps_verified_claims_with_a_stated_exclusion(self):
        items = [DecoysTest.claim, dict(DecoysTest.claim, citations=[{"page": 1, "quote": "Naturopath services"}]),
                 dict(DecoysTest.claim, plan="B")]
        got = blanks.accepted(items, [{"id": 0, "ok": True}, {"id": 1, "ok": True}, {"id": 2, "ok": False}],
                              lambda plan: lambda page, q: False)
        self.assertEqual(got, [DecoysTest.claim])


class PublishTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = pathlib.Path(self.tmp.name)
        shutil.copytree(DATA, self.data, dirs_exist_ok=True)
        self.blank = next((plan, key) for key, by_plan in blanks.cells(self.data).items()
                          for plan, c in by_plan.items() if not c["value"].strip() and not c["cites"])

    def tearDown(self):
        self.tmp.cleanup()

    def accepted(self, plan, key):
        path = self.data / "accepted.json"
        path.write_text(json.dumps([{"plan": plan, "key": key, "claim": "excluded", "citations": [{"page": 7, "quote": "q, r"}]}]))
        return path

    def test_appends_a_blank_valued_citation(self):
        plan, key = self.blank
        blanks.publish(self.accepted(plan, key), self.data)
        raw = (self.data / "eoc_citations.csv").read_bytes()
        self.assertTrue(raw.endswith(b'"q, r"\r\n'))
        last = list(csv.DictReader(open(self.data / "eoc_citations.csv")))[-1]
        self.assertEqual((last["sheet"], last["plan_id"], last["column"], last["value"], last["pdf_page"]),
                         (key.split(".")[0], plan, key.split(".")[1], "", "7"))
        self.assertEqual(blanks.cells(self.data)[key][plan]["cites"][0]["quote"], "q, r")

    def test_refuses_a_cell_that_is_no_longer_an_uncited_blank(self):
        plan, key = self.blank
        blanks.publish(self.accepted(plan, key), self.data)
        with self.assertRaises(SystemExit):
            blanks.publish(self.accepted(plan, key), self.data)


class DocTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.data, self.work = root / "data", root / "work"
        for d in (self.data, self.work / "text", self.work / "items"):
            d.mkdir(parents=True)
        (self.data / "documents_checked.csv").write_text(
            "kind,url,sha256,pages,plan_ids\nEOC,https://x/eoc.pdf,abcdef0123456789ff,2,P-1;P-2\n")
        (self.work / "text" / "abcdef0123456789.txt").write_text(
            "=====PAGE 1=====\nMassage Not covered\nTwice Twice\n=====PAGE 2=====\nother\n")
        (self.work / "items" / "abcdef0123456789.json").write_text(json.dumps({
            "1": {"strs": ["Massage", "Not covered", "Twice", "Twice", "Acupuncture", "$0", "covered", "copay"],
                  "lefts": [10, 300, 10, 10, 10, 300, 10, 300]}}))

    def tearDown(self):
        self.tmp.cleanup()

    def test_quote_ok_needs_one_highlight_on_the_page(self):
        doc = Doc(str(self.work), "P-2", self.data)
        self.assertEqual(doc.url, "https://x/eoc.pdf")
        self.assertTrue(doc.quote_ok(1, "Massage  Not covered"))
        self.assertFalse(doc.quote_ok(1, "Twice"))
        self.assertFalse(doc.quote_ok(2, "Massage"))
        self.assertTrue(doc.quote_ok(1, "Acupuncture covered"))


if __name__ == "__main__":
    unittest.main()
