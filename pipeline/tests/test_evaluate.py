import json, os, sys, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import evaluate
from test_extract import SHA, StepsTest, answer

OPUS_HIGH = "claude-opus-5-5-high"
MILLION = {"input_tokens": 1_000_000}
TRUE = answer(page=1)
WRONG = answer(page=1, network="out", amount="$40", quotes=["X-rays $0 to $40"])


def fake_asker(model, text, effort):
    """Readers state the true fact, and Haiku a wrong one too. The reviewer accepts only the true fact; other verifiers accept all."""
    if text.startswith("# Task\n\nYou check"):
        items = [json.loads(line) for line in text.splitlines() if line.startswith('{"id": ')]
        strict = (model, effort) == evaluate.REVIEWER
        return json.dumps([{"id": i["id"], "ok": not strict or (i["network"], i["amount"]) == ("in", "$0-$40")}
                           for i in items]), MILLION
    if "## Earlier answers" in text:
        return "[]", MILLION
    return json.dumps([TRUE, WRONG] if "haiku" in model else [TRUE]), MILLION


def score(role, dollars, precision, recall, unanswered=0):
    return {"role": role, "dollars": dollars, "unanswered": unanswered,
            "precision": evaluate.share(*precision), "recall": evaluate.share(*recall)}


def verifier(role, dollars, decoys, agrees, unanswered=0):
    return {"role": role, "dollars": dollars, "unanswered": unanswered,
            "decoys_accepted": evaluate.share(*decoys), "agrees_accepted": evaluate.share(*agrees)}


REVIEW = {"decoys_accepted": evaluate.share(0, 5)}


class FunctionsTest(unittest.TestCase):
    def test_cost_prices_each_kind_of_token(self):
        usage = {"input_tokens": 1e6, "output_tokens": 1e6, "cache_read_input_tokens": 1e6, "cache_creation_input_tokens": 1e6}
        self.assertAlmostEqual(evaluate.cost("claude-opus-5-5", usage), 4 + 20 + 0.2 + 5)

    def test_haiku_never_verifies(self):
        self.assertFalse([r for r in evaluate.VERIFIERS if "haiku" in r[0]])
        self.assertNotIn(evaluate.REVIEWER, evaluate.VERIFIERS)

    def test_sample_keeps_one_document_per_carrier_and_kind(self):
        docs = [{"id": "a", "kind": "EOC", "plan_ids": ["P1"]}, {"id": "b", "kind": "EOC", "plan_ids": ["P2"]},
                {"id": "c", "kind": "SB", "plan_ids": ["P2"]}, {"id": "d", "kind": "EOC", "plan_ids": ["P3"]}]
        plans = {"P1": {"organization": "X"}, "P2": {"organization": "X"}, "P3": {"organization": "Y"}}
        self.assertEqual([d["id"] for d in evaluate.sample(docs, plans)], ["a", "c", "d"])

    def test_judged_needs_every_verdict(self):
        verdicts = [{"id": 0, "ok": True}, {"id": 1, "ok": True}, {"id": 1, "ok": False}]
        self.assertEqual(evaluate.judged([{}, {}, {}], verdicts), {0: True, 1: False, 2: False})

    def test_wilson(self):
        self.assertEqual(evaluate.wilson(10, 10), (0.722, 1.0))
        self.assertIsNone(evaluate.wilson(0, 0))

    def test_reader_precision_uses_its_own_items(self):
        mine, theirs = dict(answer(), quotes='["mine"]', fact_id="f", doc_sha="d"), dict(answer(), quotes='["theirs"]', fact_id="f", doc_sha="d")
        mine.update(note="", source="EOC", provider_tier="", condition="", package="", pool="", unit="", limit="")
        theirs.update({k: mine[k] for k in mine if k != "quotes"})
        got = evaluate.score_reader([mine], {evaluate.seen(mine): False, evaluate.seen(theirs): True},
                                    {evaluate.claim(theirs)})
        self.assertEqual((got["precision"]["hits"], got["recall"]["hits"], got["recall"]["n"]), (0, 0, 1))

    def test_expected_lines_need_every_number_in_network(self):
        wanted = [{"plan_id": "P", "value": "$0 | $40"}, {"plan_id": "P", "value": "$5"}, {"plan_id": "Q", "value": "$1"}]
        found = [{"plan_id": "P", "benefit": "imaging.xray", "network": "in", "amount": "$0-$40"},
                 {"plan_id": "P", "benefit": "imaging.xray", "network": "out", "amount": "$5"},
                 {"plan_id": "P", "benefit": "radiation_therapy", "network": "in", "amount": "$5"}]
        got = evaluate.score_expected(found, wanted, [{"plan_ids": ["P"]}], "imaging")
        self.assertEqual((got["hits"], got["n"]), (1, 2))


class PicksTest(unittest.TestCase):
    readers = [score(OPUS_HIGH, 10, (9, 10), (9, 10)), score("cheap-recall", 1, (9, 10), (2, 10)),
               score("cheap-precision", 2, (3, 10), (9, 10)), score("fine", 3, (8, 10), (8, 10)),
               score("unanswered", 0.5, (9, 10), (9, 10), unanswered=1)]
    verifiers = [verifier("decoy", 1, (1, 5), (10, 10)), verifier("strict", 2, (0, 5), (5, 10)),
                 verifier("good", 3, (0, 5), (9, 10)), verifier("unanswered", 0.5, (0, 5), (10, 10), unanswered=1),
                 verifier("no-decoys", 0.1, (0, 0), (10, 10))]

    def test_cheapest_reader_whose_intervals_reach_the_reviewers_model(self):
        self.assertEqual(evaluate.picks(self.readers, self.verifiers, REVIEW)["reader"], "fine")

    def test_cheapest_verifier_that_rejects_decoys_and_agrees(self):
        self.assertEqual(evaluate.picks(self.readers, self.verifiers, REVIEW)["verifier"], "good")

    def test_no_picks_when_the_yardstick_fails(self):
        none = {"reader": None, "verifier": None}
        self.assertEqual(evaluate.picks(self.readers, self.verifiers, {"decoys_accepted": evaluate.share(1, 5)}), none)
        self.assertEqual(evaluate.picks(self.readers, self.verifiers, {"decoys_accepted": evaluate.share(0, 0)}), none)
        self.assertEqual(evaluate.picks(self.readers[1:], self.verifiers, REVIEW), none)
        self.assertEqual(evaluate.picks([score(OPUS_HIGH, 1, (0, 0), (0, 0))], self.verifiers, REVIEW), none)


class RunTest(StepsTest):
    def evaluate(self, asker, which="all", budget="100"):
        root = self.dir.parent / "eval"
        with mock.patch.object(evaluate.years, "data_dir", return_value=self.data), \
             mock.patch.object(evaluate.ask, "api", return_value=asker), mock.patch("sys.stdout"):
            evaluate.main("2027", str(self.work), str(root), "imaging", which, budget, "api")
        return json.loads((self.data / "evaluations" / "imaging" / f"{which}.json").read_text())

    def test_scores_every_role_against_the_reviewer(self):
        got = self.evaluate(fake_asker)
        readers = {s["role"]: s for s in got["readers"]}
        self.assertEqual(len(readers), 9)
        self.assertEqual(readers[OPUS_HIGH]["precision"]["share"], 1.0)
        self.assertEqual((readers["claude-haiku-5-5-low"]["precision"]["share"], readers["claude-haiku-5-5-low"]["dollars"]),
                         (0.5, 0.1))
        self.assertEqual(readers["claude-sonnet-5-5-low"]["expected"]["n"], 1)
        self.assertEqual([s["role"] for s in got["verifiers"]], [evaluate.name(r) for r in evaluate.VERIFIERS])
        self.assertEqual(got["verifiers"][0]["agrees_rejected"]["share"], 0.0)
        self.assertEqual(got["reviewer"]["dollars"], 4.0)
        self.assertEqual(got["documents"], [SHA[:16]])
        report = (self.data / "evaluations" / "imaging" / "all.md").read_text()
        self.assertIn(f"| {OPUS_HIGH} | 1/1 (0.207-1.0) | 1/1", report)

    def test_rerun_asks_nothing(self):
        first = self.evaluate(fake_asker)

        def refuse(*args):
            raise AssertionError("asked again")

        self.assertEqual(self.evaluate(refuse), first)

    def test_counts_unanswered_tasks_and_goes_on(self):
        def prose_from_haiku(model, text, effort):
            return ("I think", MILLION) if "haiku" in model else fake_asker(model, text, effort)

        got = self.evaluate(prose_from_haiku)
        self.assertEqual([s["unanswered"] for s in got["readers"][:3]], [1, 1, 1])
        self.assertEqual(len(got["readers"]), 9)

    def test_stops_starting_roles_over_budget(self):
        got = self.evaluate(fake_asker, budget="0.25")
        self.assertEqual([s["role"] for s in got["readers"]], ["claude-haiku-5-5-low", "claude-haiku-5-5-medium",
                                                               "claude-haiku-5-5-high"])
        self.assertEqual(got["verifiers"], [])
        self.assertEqual(got["picks"], {"reader": None, "verifier": None})

    def test_without_api_stops_on_unanswered_tasks(self):
        with self.assertRaisesRegex(evaluate.Unanswered, "claude-haiku-5-5-low"):
            self.evaluate(None)


del StepsTest

if __name__ == "__main__":
    unittest.main()
