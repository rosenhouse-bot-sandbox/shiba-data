import csv, json, os, pathlib, shutil, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import blanks
import build
import fields
from eoc import DATA, Doc, eoc, norm

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
        lines[5] = lines[10] = lines[35] = "massage  "
        lines[12] = " "
        got = blanks.snippets({3: "\n".join(lines)}, ["massage"])
        self.assertEqual([(p, s.split("\n")[0], s.split("\n")[-1]) for p, s in got],
                         [(3, "line 1", "line 18"), (3, "line 31", "line 39")])
        self.assertNotIn("\n\n", got[0][1])
        self.assertIn("\nmassage\n", got[0][1])

    def test_passages_head_each_page_once(self):
        layout = {2: "massage\n" + "x\n" * 20 + "massage\n"}
        self.assertEqual(blanks.passages(layout, "main.V_massage").count("=====PAGE 2====="), 1)

    def test_passages_say_when_nothing_mentions_the_benefit(self):
        self.assertEqual(blanks.passages({1: "nothing here"}, "main.V_massage"), "(No passage mentions it.)")


class FillTest(unittest.TestCase):
    def test_fills_every_placeholder(self):
        text = blanks.fill("blank_prompt.md", PLAN_NAME="VALUE", PLAN_ID="VALUE", YEAR="VALUE")
        self.assertIn("VALUE", text)
        for text in (text, blanks.fill("vblank_prompt.md")):
            self.assertNotRegex(text, r"\{[A-Z_]+\}")

    def test_adds_what_the_plans_carrier_tends_to_do(self):
        for template in ("blank_prompt.md", "filled_prompt.md", "vfilled_prompt.md"):
            text = blanks.fill(template, PLAN_ID="H9003-001-0")
            self.assertIn(f"Seen in Kaiser Permanente EOCs: {fields.CARRIERS['Kaiser Permanente']}", text)
            self.assertNotIn("Seen in", blanks.fill(template, PLAN_ID="H2056-003-0"))

    def test_prompt_version_changes_with_each_template_and_fields_py(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(blanks, "HERE", tmp):
            for name in ("a.md", "b.md", "fields.py"):
                pathlib.Path(tmp, name).write_text(name)
            versions = [blanks.prompt_version("a.md", "b.md")]
            for name in ("a.md", "b.md", "fields.py"):
                pathlib.Path(tmp, name).write_text("changed " + name)
                versions.append(blanks.prompt_version("a.md", "b.md"))
        self.assertRegex(versions[0], r"^[0-9a-f]{12}$")
        self.assertEqual(len(set(versions)), 4)


class UncitedBlanksTest(unittest.TestCase):
    def test_lists_blank_cells_without_cites(self):
        cells = {"main.V_massage": {"A": {"value": "", "cites": []}, "B": {"value": " ", "cites": [{}]}, "C": {"value": "●", "cites": []}}}
        self.assertEqual(dict(blanks.uncited_blanks(cells)), {"A": ["main.V_massage"]})


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


    def test_one_decoy_per_document_and_at_most_max_per_key(self):
        other = dict(self.claim, plan="P2")
        docs = {PLAN: Stub("a", {}), "P2": Stub("a", {}), "B": Stub("b", {2: QUOTE}), "C": Stub("c", {4: QUOTE})}
        filled = {"main.U_naturopath": ["B", "C"]}
        self.assertEqual(sorted(d["plan"] for d in blanks.decoys([self.claim, other], filled, docs.get)), ["B", "C"])
        self.assertEqual(len(blanks.decoys([self.claim, other], filled, docs.get, max_per_key=1)), 1)


class VerifierItemsTest(unittest.TestCase):
    def test_mixes_decoys_among_claims(self):
        found = [{"n": i} for i in range(20)]
        planted = [{"n": i, "decoy": True} for i in range(5)]
        items = blanks.verifier_items(found, planted)
        self.assertCountEqual(items, found + planted)
        self.assertNotEqual(items[-5:], planted)

    def test_accepted_rejects_an_item_without_a_verdict(self):
        other = dict(DecoysTest.claim, plan="P-2")
        self.assertEqual(blanks.accepted([DecoysTest.claim, other], [{"id": 1, "ok": True}], lambda plan: None), [other])


class ExclusionTest(unittest.TestCase):
    def test_states_exclusion_needs_the_benefit_and_an_unconditional_negation(self):
        self.assertTrue(blanks.states_exclusion("main.V_massage", "Therapeutic massage Not covered under any condition"))
        self.assertFalse(blanks.states_exclusion("main.V_massage", "Therapeutic massage"))
        self.assertFalse(blanks.states_exclusion("main.V_massage", "Not covered under any condition"))
        self.assertFalse(blanks.states_exclusion("main.V_massage", "massage is not covered if ordered by a chiropractor"))
        self.assertFalse(blanks.states_exclusion("main.S_acupuncture", "You do not need a referral for acupuncture"))
        self.assertTrue(blanks.states_exclusion("main.R_dental", "This plan doesn’t cover routine dental care"))

    def test_completes_a_bare_exclusion_row_and_drops_other_quotes(self):
        cites = [{"page": 4, "quote": "Therapeutic massage"}, {"page": 5, "quote": "Not covered under any condition Shoes"}]
        got = blanks.exclusion_cites("main.V_massage", cites, lambda page, q: q.endswith("condition."))
        self.assertEqual(got, [{"page": 4, "quote": "Therapeutic massage Not covered under any condition."}])

    def test_accepted_rejects_a_run_that_passes_a_decoy(self):
        items = [dict(DecoysTest.claim, decoy=True)]
        with self.assertRaises(SystemExit):
            blanks.accepted(items, [{"id": 0, "ok": True}], lambda plan: None)

    def test_accepted_needs_every_verdict_to_accept(self):
        got = blanks.accepted([DecoysTest.claim], [{"id": 0, "ok": True}, {"id": 0, "ok": False}], lambda plan: None)
        self.assertEqual(got, [])

    def test_accepted_keeps_verified_claims_with_a_stated_exclusion(self):
        items = [DecoysTest.claim, dict(DecoysTest.claim, citations=[{"page": 1, "quote": "Naturopath services"}]),
                 dict(DecoysTest.claim, plan="B")]
        got = blanks.accepted(items, [{"id": 0, "ok": True}, {"id": 1, "ok": True}, {"id": 2, "ok": False}],
                              lambda plan: lambda page, q: False)
        self.assertEqual(got, [DecoysTest.claim])


class PublishTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = pathlib.Path(self.tmp.name) / DATA.name
        shutil.copytree(DATA, self.data)
        self.blank = next((plan, key) for key, by_plan in blanks.cells(self.data).items()
                          for plan, c in by_plan.items() if not c["value"].strip() and not c["cites"])

    def tearDown(self):
        self.tmp.cleanup()

    def accepted(self, plan, key):
        path = self.data / "accepted.json"
        path.write_text(json.dumps([{"plan": plan, "key": key, "claim": "excluded", "citations": [{"page": 7, "quote": "q, r"}]}]))
        return path

    def test_cells_holds_only_fields_an_eoc_can_show(self):
        self.assertLessEqual(set(blanks.cells(self.data)), set(blanks.FIELDS))

    def test_replaces_the_steps_rows_with_a_blank_valued_citation(self):
        plan, key = self.blank
        for _ in range(2):
            blanks.publish(self.accepted(plan, key), self.data)
        raw = (self.data / "machine/blanks.csv").read_bytes()
        self.assertTrue(raw.endswith(b'"q, r"\r\n'))
        rows = list(csv.DictReader(open(self.data / "machine/blanks.csv")))
        self.assertEqual([(r["step"], r["prompt"], r["sheet"], r["plan_id"], r["column"], r["line"], r["value"], r["pdf_page"])
                          for r in rows],
                         [("blanks", blanks.prompt_version("blank_prompt.md", "vblank_prompt.md"), key.split(".")[0], plan,
                           key.split(".")[1], "", "", "7")])
        site = build.site_data(self.data)
        row = next(r for r in site[key.split(".")[0]]["rows"] if r["plan_id"] == plan)
        self.assertEqual(row["cells"][key.split(".")[1]]["cites"][0]["quote"], "q, r")

    def test_refuses_a_cell_that_is_not_an_uncited_blank(self):
        plan, key = next((plan, key) for key, by_plan in blanks.cells(self.data).items()
                         for plan, c in by_plan.items() if c["value"].strip())
        with self.assertRaises(SystemExit):
            blanks.publish(self.accepted(plan, key), self.data)


class DocTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.data, self.work = root / "data", root / "work"
        for d in (self.data, self.work / "text", self.work / "items"):
            d.mkdir(parents=True)
        (self.data / "generated").mkdir()
        (self.data / "generated/documents_checked.csv").write_text(
            "kind,url,sha256,pages,plan_ids\nSB,https://x/sb.pdf,0000000000000000ff,2,P-1;P-3\n"
            "EOC,https://x/eoc.pdf,abcdef0123456789ff,2,P-1;P-2\n")
        (self.work / "text" / "abcdef0123456789.txt").write_text(
            "=====PAGE 1=====\nMassage Not covered\nTwice Twice\nFlowtwice Flowtwice\nItemstwice\nLOUD\n=====PAGE 2=====\nother\n")
        items = [("Massage", 10), ("Not covered", 300), ("Twice", 10), ("Twice", 10), ("Flowtwice", 10), ("Itemstwice", 10),
                 ("Itemstwice", 10), ("LOUD", 10), ("Acupuncture", 10), ("$0", 300), ("covered", 10), ("copay", 300)]
        (self.work / "items" / "abcdef0123456789.json").write_text(json.dumps({
            "1": {"strs": [s for s, _ in items], "lefts": [x for _, x in items]}}))
        self.doc = Doc.of_plan(str(self.work), "P-1", self.data)

    def tearDown(self):
        self.tmp.cleanup()

    def test_finds_the_plans_eoc(self):
        self.assertEqual(eoc("P-2", self.data), ("abcdef0123456789", "https://x/eoc.pdf"))
        self.assertEqual(self.doc.id, "abcdef0123456789")
        with self.assertRaises(LookupError):
            eoc("P-3", self.data)

    def test_quote_ok_needs_one_highlight_and_at_most_one_flow_match(self):
        self.assertTrue(self.doc.quote_ok(1, "Massage  Not covered"))
        self.assertTrue(self.doc.quote_ok(1, "loud"))
        self.assertTrue(self.doc.quote_ok(1, "Acupuncture covered"))
        self.assertFalse(self.doc.quote_ok(1, "Flowtwice"))
        self.assertFalse(self.doc.quote_ok(1, "Itemstwice"))
        self.assertFalse(self.doc.quote_ok(2, "Massage"))

    def test_norm_drops_pdfium_soft_hyphens_and_extra_space(self):
        self.assertEqual(norm(" a\ufffeb  c\n"), "ab c")


if __name__ == "__main__":
    unittest.main()
