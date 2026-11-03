import glob, json, os, sys, threading, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import document_facts, facts, present
from test_extract import SHA, StepsTest, answer


# HELD cells with wrong facts, which a second reader cannot fix.
WRONG = {"H6815-038-0", "H1036-317-0"}


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

    def test_a_second_reader_adds_new_facts_for_the_plans_it_rechecks(self):
        with open(self.data / "generated" / "documents_checked.csv", "w") as f:
            f.write(f"plan_ids,kind,sha256\nH1036-306-0;H1036-307-0,EOC,{SHA}\n")
        with open(self.data / "generated" / "plans.csv", "w") as f:
            f.write("plan_id,plan_name,organization\nH1036-306-0,Gold,Humana\nH1036-307-0,Silver,Humana\n")
        asked, rechecked = [], []
        version = dict(groups=("imaging",), reader=("r", "high"), verifier=("v", "low"),
                       recheck={"imaging": ("H1036-306-0",)})

        def fake(task_dir, model, effort):
            asked.append(os.path.basename(task_dir))
            if asked[-1] == "recheck":
                rechecked.extend(json.load(open(f"{task_dir}/items.json")))
            for task in glob.glob(f"{task_dir}/*.md"):
                text = open(task).read()
                if os.path.basename(task).startswith("v-"):
                    items = json.load(open(f"{task_dir}/items.json"))
                    reply = [{"id": n, "ok": not c["decoy"]} for n, c in enumerate(items)]
                elif "## Facts already found" in text:
                    reply = [answer(page=1), answer(page=1, amount="$5"), answer(page=1, network="out", amount="$0", quotes=["Outpatient X-rays $0"]),
                             answer(page=1, plan_id="H1036-307-0", network="out", amount="$0", quotes=["Outpatient X-rays $0"])]
                else:
                    reply = [answer(page=1), answer(page=1, plan_id="H1036-307-0")]
                with open(task[:-3] + ".json", "w") as f:
                    json.dump(reply, f)

        with mock.patch.dict(document_facts.VERSIONS, {9: version}):
            document_facts.step(self.data, self.work, self.dir, fake, 9)
        rows = facts.read(self.data / "machine" / "document_facts.csv")
        self.assertEqual(sorted((r["plan_id"], r["network"], r["amount"]) for r in rows),
                         [("H1036-306-0", "in", "$0-$40"), ("H1036-306-0", "out", "$0"),
                          ("H1036-307-0", "in", "$0-$40")])
        self.assertEqual(asked, ["read", "read", "check", "reread", "reread", "recheck"])
        self.assertEqual([c["network"] for c in rechecked if not c["decoy"]], ["out"])
        self.assertTrue(any(c["decoy"] for c in rechecked))

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

    def test_version_8_is_7_without_dental(self):
        self.assertEqual(document_facts.VERSIONS[8], dict(document_facts.VERSIONS[7], groups=tuple(
            g for g in document_facts.VERSIONS[7]["groups"] if g != "dental")))

    def test_version_9_adds_vision_hearing_fitness_otc_and_packages_to_7(self):
        self.assertEqual(document_facts.VERSIONS[9], dict(document_facts.VERSIONS[7], groups=document_facts.VERSIONS[7]["groups"]
                                                          + ("vision", "hearing", "fitness", "otc", "packages")))

    def test_version_10_rechecks_the_cells_whose_readers_missed_a_price(self):
        v = document_facts.VERSIONS[10]
        self.assertEqual(dict(v, recheck=None), dict(document_facts.VERSIONS[9], recheck=None))
        self.assertEqual(set(v["recheck"]) - set(v["groups"]), set())
        held = {(c, p) for c, p in present.HELD}
        for group, column in (("tests", "K_tests_labs"), ("part_b_drugs", "M_part_b_drugs"), ("hearing", "Q_hearing")):
            self.assertEqual({p for p in v["recheck"][group]} | {p for c, p in held if c == column and p in WRONG},
                             {p for c, p in held if c == column}, group)

    def test_version_1_uses_the_models_the_evaluation_picked(self):
        self.assertEqual(document_facts.VERSIONS[1], dict(groups=("imaging",), reader=("claude-opus-5-5", "high"),
                                                          verifier=("claude-opus-5-5", "medium")))


del StepsTest

if __name__ == "__main__":
    unittest.main()
