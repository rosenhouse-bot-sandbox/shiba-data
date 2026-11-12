import json, os, pathlib, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ask, blast, blobs, facts, run

READER = "reader-model"
DOC = {"id": "aaaaaaaaaaaaaaaa", "plan_ids": ["H1036-001-0", "H1036-002-0"]}
DOCS = {DOC["id"]: DOC}
VERSION = {"recheck": {"hearing": ("H1036-002-0",)}}


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
        got = self.answer("facts/review", "v-0.md", lines, reviewed=[(dict(fact_id=rejected["fact_id"], page="5"), False)])
        self.assertEqual(got, [{"id": 0, "ok": False}, {"id": 0, "ok": True}])


class TouchedTest(unittest.TestCase):
    def test_a_first_read_is_about_every_plan_of_its_document(self):
        for dir, task in (("read", f"{DOC['id']}.md"), ("read", f"{DOC['id']}.retry.md"), ("check", f"v-{DOC['id']}.md")):
            self.assertEqual(blast.touched(row(f"facts/hearing/{dir}", task), "", DOCS, VERSION),
                             {("hearing", "H1036-001-0"), ("hearing", "H1036-002-0")})

    def test_a_second_look_is_about_its_documents_rechecked_plans(self):
        decoy = '{"id": 1, "plan_id": "H1036-001-0", "benefit": "hearing.exam"}'
        for dir, task in (("reread", f"{DOC['id']}.md"), ("reread", f"{DOC['id']}.retry.md"), ("recheck", f"v-{DOC['id']}.md")):
            self.assertEqual(blast.touched(row(f"facts/hearing/{dir}", task), decoy, DOCS, VERSION), {("hearing", "H1036-002-0")})

    def test_a_review_is_about_the_plan_and_group_of_its_fact(self):
        text = 'Judge this.\n\n{"id": 0, "plan_id": "H9003-009-0", "benefit": "hearing.exam", "amount": "$0"}\n\n## Pages\n'
        self.assertEqual(blast.touched(row("facts/review", "v-0.md"), text, DOCS, VERSION), {("hearing", "H9003-009-0")})

    def test_a_task_about_no_plan_stops_the_check(self):
        with self.assertRaises(SystemExit):
            blast.touched(row("facts/review", "v-0.md"), "no items", DOCS, VERSION)


class ChangedTest(unittest.TestCase):
    def test_names_the_groups_and_plans_whose_rows_differ(self):
        before = dict(facts=[fact(), fact(plan_id="H1036-001-0")], presented=[dict(plan_id="H1036-001-0", value="$0")])
        after = dict(facts=[fact(amount="$5"), fact(plan_id="H1036-001-0")], presented=[dict(plan_id="H1036-001-0", value="$5")])
        self.assertEqual(blast.changed_plans(before, after), ({("hearing", "H1036-002-0")}, {"H1036-001-0"}))

    def test_lists_what_falls_outside_the_targets(self):
        pairs = {("hearing", "H1036-001-0"), ("hearing", "H1036-002-0"), ("dental", "H1036-002-0")}
        self.assertEqual(blast.outside(pairs, {"H1036-002-0", "H1036-003-0"}, {"hearing": ("H1036-002-0",)}),
                         [("dental", "H1036-002-0"), ("hearing", "H1036-001-0"), ("presented", "H1036-003-0")])


class LedgerTest(unittest.TestCase):
    def test_reads_no_rows_before_a_run(self):
        with tempfile.TemporaryDirectory() as work:
            self.assertEqual(blast.ledger(work), [])
            pathlib.Path(work, blobs.LEDGER).write_text("dir,task,model,effort,key,prompt\nd,t,m,e,k,p\n")
            self.assertEqual(blast.ledger(work), [dict(dir="d", task="t", model="m", effort="e", key="k", prompt="p")])


if __name__ == "__main__":
    unittest.main()
