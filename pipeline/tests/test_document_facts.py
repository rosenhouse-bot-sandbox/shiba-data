import glob, json, os, sys, threading, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import document_facts, facts
from test_extract import StepsTest, answer


class StepTest(StepsTest):
    def test_writes_the_facts_the_versions_verifier_accepts(self):
        asked = []
        version = dict(groups=("imaging",), reader=("r", "high"), verifier=("v", "low"))

        def fake(task_dir, model, effort):
            asked.append((os.path.basename(task_dir), model, effort))
            for task in glob.glob(f"{task_dir}/*.md"):
                text = open(task).read()
                if os.path.basename(task).startswith("v-"):
                    reply = [{"id": n, "ok": True} for n in range(text.count('{"id": '))]
                else:
                    reply = ([answer(page=1, cost_kind="covered", amount="")] if "## Earlier answers" in text
                             else [answer(page=1), answer(page=1, amount="$5")])
                with open(task[:-3] + ".json", "w") as f:
                    json.dump(reply, f)

        with mock.patch.dict(document_facts.VERSIONS, {9: version}):
            document_facts.step(self.data, self.work, self.dir, fake, 9)
        rows = facts.read(self.data / "machine" / "document_facts.csv")
        self.assertEqual(sorted((r["cost_kind"], r["amount"], r["source"]) for r in rows),
                         [("copay", "$0-$40", "EOC"), ("covered", "", "EOC")])
        self.assertEqual(asked, [("read", "r", "high"), ("read", "r", "high"), ("check", "v", "low")])

    def test_groups_run_at_the_same_time(self):
        both_reading = threading.Barrier(2, timeout=10)

        def fake(task_dir, model, effort):
            if task_dir.endswith("read"):
                both_reading.wait()
            for task in glob.glob(f"{task_dir}/*.md"):
                with open(task[:-3] + ".json", "w") as f:
                    json.dump([], f)

        version = dict(groups=("imaging", "ambulance"), reader=("r", "high"), verifier=("v", "low"))
        with mock.patch.dict(document_facts.VERSIONS, {9: version}):
            document_facts.step(self.data, self.work, self.dir, fake, 9)

    def test_version_3_adds_ambulance_with_the_same_models(self):
        self.assertEqual(document_facts.VERSIONS[3], dict(document_facts.VERSIONS[1], groups=("imaging", "ambulance")))

    def test_version_4_adds_surgery_with_the_same_models(self):
        self.assertEqual(document_facts.VERSIONS[4],
                         dict(document_facts.VERSIONS[1], groups=("imaging", "ambulance", "surgery")))

    def test_version_6_adds_tests_visits_rehab_and_inpatient(self):
        self.assertEqual(document_facts.VERSIONS[6], dict(document_facts.VERSIONS[4], groups=document_facts.VERSIONS[4]["groups"]
                                                          + ("tests", "visits", "rehab", "inpatient")))

    def test_version_7_adds_part_b_deductible_dental_and_extras(self):
        self.assertEqual(document_facts.VERSIONS[7], dict(document_facts.VERSIONS[6], groups=document_facts.VERSIONS[6]["groups"]
                                                          + ("giveback", "part_b_drugs", "medical_deductible", "dental", "extras")))

    def test_version_1_uses_the_models_the_evaluation_picked(self):
        self.assertEqual(document_facts.VERSIONS[1], dict(groups=("imaging",), reader=("claude-opus-5-5", "high"),
                                                          verifier=("claude-opus-5-5", "medium")))


del StepsTest

if __name__ == "__main__":
    unittest.main()
