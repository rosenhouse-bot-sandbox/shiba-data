import contextlib, glob, io, json, os, pathlib, sys, threading, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import document_facts, extract, facts, review
from test_extract import SHA, StepsTest, answer


class StepTest(StepsTest):
    def setUp(self):
        super().setUp()
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def test_writes_the_facts_the_versions_verifier_accepts(self):
        asked = []
        version = dict(groups=("imaging",), reader=("r", "high"), verifier=("v", "low"))

        def fake(task_dir, model, effort):
            asked.append((os.path.basename(task_dir), model, effort))
            for task in glob.glob(f"{task_dir}/*.md"):
                text = pathlib.Path(task).read_text()
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

    def test_a_versions_notes_reach_every_prompt(self):
        with open(self.data / "generated" / "documents_checked.csv", "w") as f:
            f.write(f"plan_ids,kind,sha256\nH1036-306-0;H1036-307-0,EOC,{SHA}\n")
        with open(self.data / "generated" / "plans.csv", "w") as f:
            f.write("plan_id,plan_name,organization\nH1036-306-0,Gold,Humana\nH1036-307-0,Silver,Humana\n")
        with open(self.work / "layout" / f"{SHA[:16]}.txt", "a") as f:
            f.write("=====PAGE 2=====\nThe list goes on.\n=====PAGE 0=====\nThe list starts.\n")
        prompts = {}

        def fake(task_dir, model, effort):
            for task in glob.glob(f"{task_dir}/*.md"):
                text = pathlib.Path(task).read_text()
                prompts[f"{os.path.basename(task_dir)}/{os.path.basename(task)}"] = text
                if os.path.basename(task).startswith("v-"):
                    items = json.loads(pathlib.Path(f"{task_dir}/items.json").read_text())
                    reply = [{"id": n, "ok": not c["decoy"]} for n, c in enumerate(items)]
                elif "## Facts already found" in text:
                    reply = [answer(page=1, network="out", amount="$0", quotes=["Outpatient X-rays $0"])]
                else:
                    reply = [answer(page=1)] + ([] if "## Earlier answers" in text else [answer(page=1, amount="$99")])
                with open(task[:-3] + ".json", "w") as f:
                    json.dump(reply, f)

        version = dict(groups=("imaging",), reader=("r", "high"), verifier=("v", "low"), notes={"imaging": "Read this."},
                       check_notes={"imaging": "Check this."}, recheck_notes={"imaging": "Look again."},
                       check_after={"imaging": 1}, check_before={"imaging": 1}, recheck={"imaging": ("H1036-306-0",)})
        with mock.patch.dict(document_facts.VERSIONS, {9: version}):
            document_facts.step(self.data, self.work, self.dir, fake, 9)
        self.assertEqual({name.split("/")[0] for name in prompts}, {"read", "check", "reread", "recheck"})
        self.assertTrue(any(name.endswith(".retry.md") for name in prompts))
        expected = {"read": version["notes"], "check": review.checker_notes(version),
                    "reread": review.joined(version["notes"], version["recheck_notes"]), "recheck": review.second_notes(version)}
        self.assertEqual([name for name, text in prompts.items()
                          if facts.describe("imaging", expected[name.split("/")[0]]) not in text], [])
        checking = {name: name.split("/")[0] in ("check", "recheck") for name in prompts}
        second = {name: name.split("/")[0] in ("reread", "recheck") for name in prompts}
        self.assertEqual([name for name, text in prompts.items() if ("Check this." in text) != checking[name]], [])
        self.assertEqual([name for name, text in prompts.items() if ("Look again." in text) != second[name]], [])
        self.assertEqual([name for name, text in prompts.items() if ("=====PAGE 2=====" in text) != checking[name]], [])
        self.assertEqual([name for name, text in prompts.items() if ("=====PAGE 0=====" in text) != checking[name]], [])

    def test_a_versions_zero_groups_let_every_reading_price_zeros_in_words(self):
        text = "There is no copayment for X-rays."
        for sub in ("text", "layout"):
            (self.work / sub / f"{SHA[:16]}.txt").write_text(f"=====PAGE 1=====\n{text}\n")
        (self.work / "items" / f"{SHA[:16]}.json").write_text(json.dumps({"1": {"strs": [text], "lefts": [0]}}))
        free = answer(page=1, amount="$0", quotes=["no copayment for X-rays"])

        def fake(task_dir, model, effort):
            for task in glob.glob(f"{task_dir}/*.md"):
                text = pathlib.Path(task).read_text()
                if os.path.basename(task).startswith("v-"):
                    reply = [{"id": n, "ok": True} for n in range(text.count('{"id": '))]
                else:
                    reply = [dict(free, network="out")] if "## Facts already found" in text else [free]
                with open(task[:-3] + ".json", "w") as f:
                    json.dump(reply, f)
        for zero, networks in (((), []), (("imaging",), ["in", "out"])):
            version = dict(groups=("imaging",), reader=("r", "high"), verifier=("v", "low"), zero_groups=zero,
                           recheck={"imaging": ("H1036-306-0",)})
            with mock.patch.dict(document_facts.VERSIONS, {9: version}):
                document_facts.step(self.data, self.work, self.dir, fake, 9)
            self.assertEqual(sorted(r["network"] for r in facts.read(self.data / "machine" / "document_facts.csv")), networks, zero)

    def test_a_merge_version_keeps_answers_that_differ_only_in_notes(self):
        def fake(task_dir, model, effort):
            for task in glob.glob(f"{task_dir}/*.md"):
                text = pathlib.Path(task).read_text()
                reply = ([{"id": n, "ok": True} for n in range(text.count('{"id": '))] if os.path.basename(task).startswith("v-")
                         else [answer(page=1, note="a"), answer(page=1, note="b")])
                with open(task[:-3] + ".json", "w") as f:
                    json.dump(reply, f)

        for more, count in ((dict(merge=False), 0), (dict(merge=True), 1), (dict(merge_limits=("imaging",)), 1),
                            (dict(merge_limits=("dental",)), 0)):
            version = dict(groups=("imaging",), reader=("r", "high"), verifier=("v", "low"), **more)
            with mock.patch.dict(document_facts.VERSIONS, {9: version}):
                document_facts.step(self.data, self.work, self.dir, fake, 9)
            self.assertEqual(len(facts.read(self.data / "machine" / "document_facts.csv")), count, more)

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
                rechecked.extend(json.loads(pathlib.Path(f"{task_dir}/items.json").read_text()))
            for task in glob.glob(f"{task_dir}/*.md"):
                text = pathlib.Path(task).read_text()
                if os.path.basename(task).startswith("v-"):
                    items = json.loads(pathlib.Path(f"{task_dir}/items.json").read_text())
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
        with open(self.dir / "imaging/reread" / extract.OUTCOMES) as f:
            self.assertEqual([o.get("skipped") for o in json.load(f)][:4],
                             [document_facts.FOUND_BEFORE, None, None, document_facts.NOT_RECHECKED])
        self.assertEqual([c["network"] for c in rechecked if not c["decoy"]], ["out"])
        self.assertTrue(any(c["decoy"] for c in rechecked))

    def test_a_reviewer_keeps_what_it_accepts_and_saves_what_a_later_run_trusts(self):
        def fake(task_dir, model, effort):
            for task in glob.glob(f"{task_dir}/*.md"):
                text = pathlib.Path(task).read_text()
                reply = ([{"id": n, "ok": True} for n in range(text.count('{"id": '))] if os.path.basename(task).startswith("v-")
                         else [] if "## Earlier answers" in text else [answer(page=1), answer(page=1, amount="$5")])
                with open(task[:-3] + ".json", "w") as f:
                    json.dump(reply, f)

        def gate(data, texts, work, answer_, trusted, rows, v, held):
            self.assertEqual((trusted, held), ({"old"}, {"held 2"}))
            return rows[:0], rows

        version = dict(groups=("imaging",), reader=("r", "high"), verifier=("v", "low"), reviewer=("m", "e"))
        with mock.patch.dict(document_facts.VERSIONS, {9: version}), \
                mock.patch.object(review, "trusted", lambda data, old, held: {"old"}), mock.patch.object(review, "gate", gate), \
                mock.patch.object(document_facts.present, "held", lambda data, version: {f"held {version}"}):
            document_facts.step(self.data, self.work, self.dir, fake, 9, present_version=2)
            self.assertEqual(facts.read(self.data / "machine" / "document_facts.csv"), [])
            self.assertEqual(len(facts.read(self.data / review.REVIEWED)), 1)
            document_facts.step(self.data, self.work, self.dir, fake, 9, reviewed=False)
            self.assertEqual(len(facts.read(self.data / "machine" / "document_facts.csv")), 1)

    def test_clears_the_outcomes_of_an_earlier_run(self):
        def fake(task_dir, model, effort):
            for task in glob.glob(f"{task_dir}/*.md"):
                with open(task[:-3] + ".json", "w") as f:
                    json.dump([], f)

        for groups in (("imaging", "ambulance"), ("imaging",)):
            with mock.patch.dict(document_facts.VERSIONS, {9: dict(groups=groups, reader=("r", "high"), verifier=("v", "low"))}):
                document_facts.step(self.data, self.work, self.dir, fake, 9)
        self.assertEqual(os.listdir(self.dir), ["imaging"])

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

    def test_version_14_rechecks_hearing_for_plans_with_no_routine_exam_price(self):
        v13, v14 = document_facts.VERSIONS[13], document_facts.VERSIONS[14]
        self.assertEqual(dict(v14, recheck=v13["recheck"]), v13)
        self.assertIn("H6815-038-0", v14["recheck"]["hearing"])
        self.assertIn("H9003-009-0", v14["recheck"]["hearing"])

    def test_version_15_merges_answers_that_differ_only_in_quotes(self):
        self.assertEqual(document_facts.VERSIONS[15], dict(document_facts.VERSIONS[14], merge=True))

    def test_version_16_reads_the_moop_and_part_d_deductible(self):
        v15 = document_facts.VERSIONS[15]
        self.assertEqual(document_facts.VERSIONS[16], dict(v15, groups=v15["groups"] + ("moop", "part_d_deductible")))

    def test_version_17_notes_how_to_read_dental_and_emergency_networks(self):
        v16, v17 = document_facts.VERSIONS[16], document_facts.VERSIONS[17]
        self.assertEqual(dict(v17, notes=None, review_cap=None), dict(v16, notes=None, review_cap=None))
        self.assertEqual(set(v17["notes"]), {"dental", "emergency"})

    def test_version_18_merges_dental_limits_and_notes_how_to_check_reimbursement(self):
        v17, v18 = document_facts.VERSIONS[17], document_facts.VERSIONS[18]
        self.assertEqual(dict(v18, merge_limits=None, check_notes=None), dict(v17, merge_limits=None, check_notes=None))
        self.assertEqual((v18["merge_limits"], set(v18["check_notes"])), (("dental",), {"dental"}))

    def test_version_19_shows_dental_checkers_the_next_page(self):
        v18, v19 = document_facts.VERSIONS[18], document_facts.VERSIONS[19]
        self.assertEqual(dict(v19, check_after=None), dict(v18, check_after=None))
        self.assertEqual(v19["check_after"], {"dental": 1})

    def test_version_20_takes_a_second_look_at_the_cells_readers_left_short(self):
        v19, v20 = document_facts.VERSIONS[19], document_facts.VERSIONS[20]
        more = ("zero_groups", "check_before", "recheck_notes", "recheck")
        self.assertEqual(dict(v20, **dict.fromkeys(more)), dict(v19, **dict.fromkeys(more)))
        self.assertEqual(v20["zero_groups"], extract.ZERO_GROUPS + ("part_d_deductible", "plan_premium"))
        self.assertEqual(v20["check_before"], {"hearing": 1})
        self.assertEqual(v20["recheck"], v19["recheck"] | {"plan_premium": ("H3817-010-0",),
                                                            "emergency": v19["recheck"]["emergency"] + ("H5439-019-0",)})
        self.assertEqual(set(v20["recheck_notes"]), {"plan_premium", "emergency", "tests", "surgery"})
        self.assertLessEqual(set(v20["recheck_notes"]), set(v20["recheck"]))

    def test_version_9_adds_vision_hearing_fitness_otc_and_packages_to_7(self):
        self.assertEqual(document_facts.VERSIONS[9], dict(document_facts.VERSIONS[7], groups=document_facts.VERSIONS[7]["groups"]
                                                          + ("vision", "hearing", "fitness", "otc", "packages")))

    def test_version_10_rechecks_the_cells_whose_readers_missed_a_price(self):
        v = document_facts.VERSIONS[10]
        self.assertEqual(dict(v, recheck=None), dict(document_facts.VERSIONS[9], recheck=None))
        kaiser = ("H9003-001-0", "H9003-006-0", "H9003-009-0")
        self.assertEqual(v["recheck"], {
            "tests": ("H2406-070-0", "H2923-009-0", "H3817-008-1", "H5439-010-0", "H5439-011-0", "H5439-015-0",
                      "H5439-019-0", "H7006-021-0"),
            "part_b_drugs": kaiser, "hearing": ("H9003-009-0",), "surgery": kaiser + ("H3817-008-1",)})

    def test_version_12_adds_the_dvha_groups_to_11(self):
        self.assertEqual(document_facts.VERSIONS[12], dict(document_facts.VERSIONS[11], groups=document_facts.VERSIONS[11]["groups"]
                         + ("plan_premium", "emergency", "foot_care", "meals", "other_supplemental")))

    def test_version_1_uses_the_models_the_evaluation_picked(self):
        self.assertEqual(document_facts.VERSIONS[1], dict(groups=("imaging",), reader=("claude-opus-5-5", "high"),
                                                          verifier=("claude-opus-5-5", "medium")))


del StepsTest

if __name__ == "__main__":
    unittest.main()
