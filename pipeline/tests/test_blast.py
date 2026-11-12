import contextlib, io, json, os, pathlib, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ask, blast, blobs, facts, run
from test_reach import review

READER = "reader-model"
DOC = {"id": "aaaaaaaaaaaaaaaa", "plan_ids": ["H1036-001-0", "H1036-002-0"]}


def row(dir, task, prompt="p", key="k"):
    return dict(dir=dir, task=task, model=READER, effort="high", key=key, prompt=prompt)


def fact(**changes):
    f = dict.fromkeys(facts.COLUMNS, "") | dict(plan_id="H1036-002-0", benefit="hearing.exam", setting="any", network="in",
                                                covered_by="supplemental", cost_kind="copay", amount="$0", source="EOC",
                                                doc_sha="a" * 64, page="5", quotes=json.dumps(["$0"])) | changes
    return f | {"fact_id": facts.fact_id(f)}


class StubTest(unittest.TestCase):
    def answer(self, dir, task, text, pinned_rows=(), kept=(), reviewed=(), items=()):
        """The stub's answer to one task, given the pinned run's ledger rows, accepted facts and review verdicts."""
        with tempfile.TemporaryDirectory() as work:
            data, task_dir = pathlib.Path(work, "data"), pathlib.Path(work, dir)
            task_dir.mkdir(parents=True)
            (data / "answers").mkdir(parents=True)
            ask.write(f"{data}/answers/old.json", {"reply": '[{"amount": "$0"}]'})
            facts.write(f"{task_dir}/accepted.csv", list(kept))
            if reviewed:
                ask.write(f"{work}/facts/review/outcomes.json", [dict(fact=f, ok=ok) for f, ok in reviewed])
            pinned = blast.Pinned(work, list(pinned_rows))
            (task_dir / "items.json").write_text(json.dumps([dict(i, task=DOC["id"]) for i in items]))
            (task_dir / task).write_text(text)
            run.Answers(data, blast.Stub(pinned, data / "answers", work), work)(str(task_dir), READER, "high")
            return json.loads((task_dir / task.replace(".md", ".json")).read_text())

    def test_a_reader_gets_the_pinned_answer_for_the_same_document(self):
        self.assertEqual(self.answer("facts/hearing/reread", "a.md", "new", [row("facts/hearing/reread", "a.md", key="old")]),
                         [{"amount": "$0"}])

    def test_a_reader_the_pinned_run_did_not_ask_finds_nothing(self):
        self.assertEqual(self.answer("facts/hearing/reread", "a.md", "new", [row("facts/hearing/reread", "b.md", key="old")]), [])

    def test_a_verifier_keeps_what_the_pinned_run_kept_and_no_decoy(self):
        kept, dropped = fact(), fact(amount="$5")
        items = [dict(dropped, decoy=False), dict(kept, decoy=True), dict(kept, decoy=False)]
        self.assertEqual(self.answer("facts/hearing/recheck", f"v-{DOC['id']}.md", "new", kept=[kept], items=items),
                         [{"id": 0, "ok": False}, {"id": 1, "ok": False}, {"id": 2, "ok": True}])

    def test_a_reviewer_keeps_what_the_pinned_review_kept_and_passes_a_fact_it_never_saw(self):
        rejected, unseen = fact(), fact(plan_id="H1036-001-0")
        lines = "\n".join(json.dumps({"id": 0, **{k: v for k, v in f.items() if k in ("plan_id", "benefit", "setting", "network",
                          "covered_by", "cost_kind", "amount", "page") and v}}) for f in (rejected, unseen))
        got = self.answer("facts/review", "v-0.md", lines, reviewed=[(dict(fact_id=rejected["fact_id"], page=5), None)])
        self.assertEqual(got, [{"id": 0, "ok": False}, {"id": 0, "ok": True}])


class ChangedTest(unittest.TestCase):
    def test_names_the_groups_and_plans_whose_rows_differ(self):
        before = dict(facts=[fact(), fact(plan_id="H1036-001-0")], presented=[dict(plan_id="H1036-001-0", value="$0")])
        after = dict(facts=[fact(amount="$5"), fact(plan_id="H1036-001-0")], presented=[dict(plan_id="H1036-001-0", value="$5")])
        self.assertEqual(blast.changed_plans(before, after), ({("hearing", "H1036-002-0")}, {"H1036-001-0"}))


class MainTest(unittest.TestCase):
    """main with the model steps faked: the pinned run lists no tasks, and the candidate run lists the given tasks."""

    def main(self, tasks=(), saved=(), status="", before=None, after=None, candidate="document_facts@23"):
        """main's order of steps and its output, for candidate tasks as (key, prompt text) and saved answer keys."""
        order, out = [], io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            data, work = pathlib.Path(tmp, "data"), pathlib.Path(tmp, "work")
            (data / "answers").mkdir(parents=True)
            (data / "steps.json").write_text(json.dumps({"document_facts": 21, "present": 16}))
            for key in saved:
                ask.write(f"{data}/answers/{key}.json", {"reply": "[]"})

            def model_steps(data_, work_, versions, asker, copy):
                order.append(("model_steps", versions["document_facts"]))
                if asker is None:
                    return []
                order.append(("copy", sorted(os.listdir(copy))))
                ask.write(f"{copy}/stand-in.json", {"reply": "[]"})
                os.makedirs(f"{work_}/{blobs.PROMPTS}", exist_ok=True)
                for key, text in tasks:
                    pathlib.Path(work_, blobs.PROMPTS, ask.sha(text)).write_text(text)
                return [row("facts/review", "v-0.md", ask.sha(text), key) for key, text in tasks]

            outs = iter([before or dict(facts=[], presented=[]), after or dict(facts=[], presented=[])])
            with mock.patch.multiple(blast, model_steps=model_steps, outputs=lambda d: order.append("outputs") or next(outs),
                                     git=lambda *a: order.append(a) or status,
                                     restore=lambda d: order.append("restore")), \
                 mock.patch.object(blast.years, "data_dir", lambda year: data), \
                 mock.patch.object(blast.extract, "documents", lambda d: []), \
                 contextlib.redirect_stdout(out):
                try:
                    blast.main("2027", str(work), candidate)
                    failed = None
                except SystemExit as e:
                    failed = str(e)
            self.assertEqual(sorted(os.listdir(data / "answers")), sorted(f"{k}.json" for k in saved))
        return order, failed, out.getvalue()

    def test_fails_when_a_new_task_is_about_a_plan_outside_the_targets(self):
        _, failed, _ = self.main(tasks=[("new", review("H1036-001-0"))])
        self.assertIn("hearing H1036-001-0", failed)

    def test_passes_when_only_tasks_about_its_targets_are_new(self):
        _, failed, out = self.main(tasks=[("new", review("H9003-009-0")), ("old", review("H1036-001-0"))], saved=["old"])
        self.assertIsNone(failed)
        self.assertIn("1 of 2 tasks would call the API.", out)

    def test_fails_when_facts_outside_the_targets_change(self):
        _, failed, _ = self.main(before=dict(facts=[fact()], presented=[]), after=dict(facts=[], presented=[]))
        self.assertIn("hearing H1036-002-0", failed)

    def test_compares_each_runs_outputs_and_restores_the_data_after_each_run(self):
        order, _, _ = self.main(saved=["old"])
        self.assertEqual(order[1:], [("model_steps", 21), "outputs", "restore", ("model_steps", 23), ("copy", ["old.json"]),
                                     "outputs", "restore"])

    def test_refuses_data_with_uncommitted_or_ignored_files(self):
        order, failed, _ = self.main(status=" M answers/x.json")
        self.assertEqual([a[:3] for a in order], [("status", "--porcelain", "--ignored")])
        self.assertIn("uncommitted changes", failed)

    def test_refuses_more_than_one_candidate(self):
        order, failed, _ = self.main(candidate="present@16,document_facts@23")
        self.assertEqual((order, failed), ([], "blast.py checks one document_facts candidate."))


class ModelStepsTest(unittest.TestCase):
    def run_steps(self, asker, saved=()):
        """The ledger rows and output of blast.model_steps for one reader task, and whether it left a ledger."""
        with tempfile.TemporaryDirectory() as tmp:
            data, work, copy = pathlib.Path(tmp, "data"), pathlib.Path(tmp, "work"), pathlib.Path(tmp, "copy")
            copy.mkdir()
            for key in saved:
                ask.write(f"{copy}/{key}.json", {"reply": "[]"})

            def model_steps(data_, texts, work_, answer, versions):
                print("progress")
                os.makedirs(f"{work_}/facts/hearing/read")
                pathlib.Path(work_, "facts/hearing/read/a.md").write_text("task")
                answer(f"{work_}/facts/hearing/read", READER)

            out = io.StringIO()
            with mock.patch.object(blast.run, "model_steps", model_steps), contextlib.redirect_stdout(out):
                try:
                    got = blast.model_steps(data, str(work), {}, asker, str(copy))
                except SystemExit as e:
                    got = str(e)
            return got, out.getvalue(), os.path.exists(f"{work}/{blobs.LEDGER}")

    def test_answers_from_the_copy_quietly_and_leaves_no_ledger(self):
        rows, out, left = self.run_steps(None, saved=[ask.key(READER, "task")])
        self.assertEqual(([r["task"] for r in rows], out, left), (["a.md"], "", False))

    def test_shows_its_output_when_the_pinned_run_lacks_answers(self):
        got, out, left = self.run_steps(None)
        self.assertEqual(got, "The pinned version has tasks without saved answers.")
        self.assertIn("progress", out)
        self.assertFalse(left)


if __name__ == "__main__":
    unittest.main()
