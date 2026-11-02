import json, os, pathlib, re, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import evaluate
from test_extract import SHA, StepsTest, X_RAYS, answer

OPUS_HIGH = "claude-opus-5-5-high"


def fake_asker(model, text, effort):
    """Readers answer one true fact; Haiku adds a wrong one. The reviewer accepts only the true amount; others accept all."""
    usage = {"input_tokens": 1_000_000, "output_tokens": 0}
    if text.startswith("# Task\n\nYou check"):
        items = [json.loads(line) for line in text.splitlines() if line.startswith('{"id": ')]
        strict = (model, effort) == evaluate.REVIEWER
        return json.dumps([{"id": i["id"], "ok": not strict or i["amount"] == "$0-$40"} for i in items]), usage
    if "## Earlier answers" in text:
        return "[]", usage
    found = [answer(page=1)]
    if "haiku" in model:
        found.append(answer(page=1, network="out", amount="$40", quotes=["X-rays $0 to $40"]))
    return json.dumps(found), usage


class FunctionsTest(unittest.TestCase):
    def test_cost_prices_cache_tokens_as_input(self):
        self.assertAlmostEqual(evaluate.cost("claude-opus-5-5", {"input_tokens": 500_000, "cache_read_input_tokens": 500_000,
                                                                 "output_tokens": 100_000}), 4.0 + 2.0)

    def test_sample_keeps_one_document_per_carrier_and_kind(self):
        docs = [{"id": "a", "kind": "EOC", "plan_ids": ["P1"]}, {"id": "b", "kind": "EOC", "plan_ids": ["P2"]},
                {"id": "c", "kind": "SB", "plan_ids": ["P2"]}, {"id": "d", "kind": "EOC", "plan_ids": ["P3"]}]
        plans = {"P1": {"organization": "X"}, "P2": {"organization": "X"}, "P3": {"organization": "Y"}}
        self.assertEqual([d["id"] for d in evaluate.sample(docs, plans)], ["a", "c", "d"])

    def test_judged_needs_every_verdict(self):
        items = [{}, {}, {}]
        self.assertEqual(evaluate.judged(items, [{"id": 0, "ok": True}, {"id": 1, "ok": True}, {"id": 1, "ok": False}]),
                         {0: True, 1: False, 2: False})

    def test_cheapest_that_fits(self):
        scores = [{"role": "a", "dollars": 3, "x": 1}, {"role": "b", "dollars": 1, "x": 0}, {"role": "c", "dollars": 2, "x": 1}]
        self.assertEqual(evaluate.cheapest(scores, lambda s: s["x"]), "c")
        self.assertIsNone(evaluate.cheapest(scores, lambda s: False))


class RunTest(StepsTest):
    def evaluate(self, asker):
        root = self.dir.parent / "eval"
        with mock.patch.object(evaluate.years, "data_dir", return_value=self.data), \
             mock.patch.object(evaluate.ask, "api", return_value=asker), \
             mock.patch("sys.stdout"):
            evaluate.main("2027", str(self.work), str(root), "imaging", "all", "api")
        return json.loads((self.data / "evaluations" / "imaging" / "all.json").read_text()), root

    def test_scores_every_reader_and_verifier_against_the_reviewer(self):
        got, root = self.evaluate(fake_asker)
        readers = {s["role"]: s for s in got["readers"]}
        self.assertEqual(len(readers), 9)
        self.assertEqual((readers[OPUS_HIGH]["precision"], readers[OPUS_HIGH]["recall"]), (1.0, 1.0))
        self.assertEqual(readers["claude-haiku-5-5-low"]["precision"], 0.5)
        self.assertEqual(readers["claude-haiku-5-5-low"]["dollars"], 0.1)
        self.assertEqual(got["picks"]["reader"], "claude-sonnet-5-5-low")
        verifiers = {s["role"]: s for s in got["verifiers"]}
        self.assertEqual(len(verifiers), 8)
        self.assertEqual(verifiers["claude-sonnet-5-5-low"][evaluate.DISAGREE], 1.0)
        self.assertIsNone(got["picks"]["verifier"])
        self.assertEqual(got["documents"], [SHA[:16]])
        self.assertIn(f"| {OPUS_HIGH} | 1 | 1 | 1.0 | 1.0 |", (self.data / "evaluations" / "imaging" / "all.md").read_text())

    def test_rerun_asks_nothing(self):
        self.evaluate(fake_asker)
        first = (self.data / "evaluations" / "imaging" / "all.json").read_text()

        def refuse(*args):
            raise AssertionError("asked again")

        again, _ = self.evaluate(refuse)
        self.assertEqual(json.dumps(again, indent=1) + "\n", first)

    def test_stops_on_unanswered_tasks(self):
        with self.assertRaisesRegex(evaluate.Unanswered, "claude-haiku-5-5-low"):
            self.evaluate(None)


del StepsTest

if __name__ == "__main__":
    unittest.main()
